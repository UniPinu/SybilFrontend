"""One inference at a time, narrated over Server-Sent Events.

A single worker thread runs the pipeline FIFO -- two 3-D CNNs at once would
thrash a laptop, and the stem activation alone is ~0.84 GB. Progress events are
pushed from that thread onto each subscriber's asyncio queue, and also kept in
the job so a browser that connects late (or reconnects) replays what it missed.

Event names and payloads are the table in MVP.md section 6.3.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import threading
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.pipeline import PipelineError, process_patient

log = logging.getLogger(__name__)

TERMINAL = {"done", "error"}


@dataclass
class Event:
    name: str
    data: Dict[str, Any]
    # monotonic per job, so a late subscriber can tell replay from live
    seq: int = 0
    at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))

    def as_sse(self) -> Dict[str, Any]:
        # sse-starlette stringifies a non-str payload with str(), which would
        # put Python reprs ({'a': 1}) on the wire, so encode JSON ourselves.
        return {"event": self.name, "data": json.dumps({**self.data, "at": self.at})}

    def as_dict(self) -> Dict[str, Any]:
        return {"event": self.name, "data": {**self.data, "at": self.at}}


@dataclass
class Job:
    id: str
    patient_id: str
    state: str = "queued"
    events: List[Event] = field(default_factory=list)
    seq: int = 0
    error: Optional[str] = None
    error_stage: Optional[str] = None
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    future: Optional[Future] = None

    def as_dict(self) -> dict:
        return {
            "job_id": self.id,
            "patient_id": self.patient_id,
            "state": self.state,
            "error": self.error,
            "error_stage": self.error_stage,
            "created_at": self.created_at,
            "events": [e.as_dict() for e in self.events],
        }


FRIENDLY = {
    "queued": "Waiting for Sybil…",
    "downloading": "Fetching the scan…",
    "reading": "Reading the scan…",
    "standardizing": "Making every scan look alike…",
    "model": "The experts are looking…",
    "calibrating": "Turning votes into honest percentages…",
    "rendering": "Preparing the pictures…",
    "done": "Ready.",
    "error": "Something went wrong.",
}


class JobManager:
    def __init__(self, max_history: int = 64):
        self._jobs: Dict[str, Job] = {}
        self._order: deque[str] = deque(maxlen=max_history)
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sybil-worker")
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending: deque[str] = deque()
        self._running: Optional[str] = None
        self._closed = False

    # --- wiring ----------------------------------------------------------
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attach to the app's event loop, and recover from a previous run.

        The app can be started more than once in one process (every test client
        does it). Whatever was queued when the last one shut down is gone, so
        those jobs are failed explicitly -- otherwise a client asking to run
        that patient again would be handed a job that will never progress.
        """
        self._loop = loop
        with self._lock:
            if self._closed:
                self._executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="sybil-worker"
                )
                self._closed = False
            stale = [j for j in self._jobs.values() if j.state not in TERMINAL]
            self._pending.clear()
            self._running = None
        for job in stale:
            job.state = "error"
            job.error, job.error_stage = "server restarted", "shutdown"
            self._record(job, "error", message="The server restarted. Please try again.",
                         stage="shutdown")

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    # --- queries ---------------------------------------------------------
    def job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def job_for_patient(self, patient_id: str) -> Optional[Job]:
        for job_id in reversed(self._order):
            job = self._jobs.get(job_id)
            if job and job.patient_id == patient_id and job.state not in TERMINAL:
                return job
        return None

    def stats(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "queued": list(self._pending),
                "jobs_tracked": len(self._jobs),
            }

    # --- submission ------------------------------------------------------
    def submit(self, patient_id: str) -> Job:
        existing = self.job_for_patient(patient_id)
        if existing:
            return existing

        job = Job(id=uuid.uuid4().hex[:12], patient_id=patient_id)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._order) == self._order.maxlen:
                self._jobs.pop(self._order[0], None)
            self._order.append(job.id)
            self._pending.append(job.id)
            position = len(self._pending) - 1 + (1 if self._running else 0)

        self._record(job, "queued", position=position, text=FRIENDLY["queued"])
        job.future = self._executor.submit(self._run, job)
        return job

    # --- worker ----------------------------------------------------------
    def _run(self, job: Job) -> None:
        with self._lock:
            if job.id in self._pending:
                self._pending.remove(job.id)
            self._running = job.id
        job.state = "running"
        try:
            process_patient(job.patient_id, emit=lambda stage, **kw: self._record(job, stage, **kw))
        except PipelineError as exc:
            job.state = "error"
            job.error, job.error_stage = str(exc), exc.stage
            log.exception("job %s failed at %s", job.id, exc.stage)
            self._record(job, "error", message=_friendly_error(exc), stage=exc.stage)
        except Exception as exc:  # noqa: BLE001 - the UI still needs to hear about it
            job.state = "error"
            job.error, job.error_stage = str(exc), "unknown"
            log.exception("job %s failed", job.id)
            self._record(job, "error", message=_friendly_error(exc), stage="unknown")
        finally:
            with self._lock:
                self._running = None
            if job.state != "error":
                job.state = "done"
            self._promote_queue()

    def _promote_queue(self) -> None:
        """Tell everyone still waiting that they moved up."""
        with self._lock:
            pending = list(self._pending)
        for position, job_id in enumerate(pending):
            job = self._jobs.get(job_id)
            if job and job.state == "queued":
                self._record(job, "queued", position=position, text=FRIENDLY["queued"])

    # --- events ----------------------------------------------------------
    def _record(self, job: Job, name: str, **data: Any) -> None:
        if name == "done":
            job.state = "done"
        event = Event(name=name, data={"text": FRIENDLY.get(name), **data}, seq=job.seq)
        job.seq += 1
        job.events.append(event)
        # Progress bytes arrive several times a second; keep the replay buffer
        # from growing without bound.
        if len(job.events) > 400:
            job.events = job.events[:1] + job.events[-200:]
        self._fanout(job.id, event)

    def _fanout(self, job_id: str, event: Event) -> None:
        loop = self._loop
        queues = self._subscribers.get(job_id, [])
        if not loop or not queues:
            return
        for queue in list(queues):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # loop closed during shutdown
                pass

    async def stream(self, job_id: str):
        """Async generator of SSE dicts: replay, then live, then close."""
        job = self._jobs.get(job_id)
        if job is None:
            yield {"event": "error",
                   "data": json.dumps({"message": "Unknown job.", "stage": "lookup"})}
            return

        queue: asyncio.Queue = asyncio.Queue()
        # Subscribe first, then replay: anything emitted in between lands in the
        # queue, and `replayed` stops it being sent a second time.
        self._subscribers.setdefault(job_id, []).append(queue)
        try:
            replayed_to = -1
            for event in list(job.events):
                replayed_to = event.seq
                yield event.as_sse()
                if event.name in TERMINAL:
                    return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # keep-alive so proxies and browsers hold the connection
                    yield {"event": "ping", "data": json.dumps({"state": job.state})}
                    if job.state in TERMINAL and queue.empty():
                        return
                    continue
                if event.seq <= replayed_to:
                    continue
                yield event.as_sse()
                if event.name in TERMINAL:
                    return
        finally:
            subs = self._subscribers.get(job_id, [])
            if queue in subs:
                subs.remove(queue)
            if not subs:
                self._subscribers.pop(job_id, None)


def _friendly_error(exc: Exception) -> str:
    stage = getattr(exc, "stage", "")
    text = str(exc)
    if stage == "downloading":
        return ("Could not download this scan from Imaging Data Commons. "
                "Check your connection and try another person.")
    if stage == "model":
        return f"Sybil could not read this scan ({text}). Try another person."
    if stage == "lookup":
        return "That person is not in the candidate list."
    return f"Something went wrong: {text}"


jobs = JobManager()
