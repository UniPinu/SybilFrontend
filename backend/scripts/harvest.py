"""Run Sybil on T0, T1 and T2 of every eligible participant, on the GPU.

  uv run python scripts/harvest.py run                 # start, or resume where it stopped
  uv run python scripts/harvest.py run --limit 200     # stop after 200 more participants
  uv run python scripts/harvest.py stop                # from another window: stop after the current scan
  uv run python scripts/harvest.py status              # progress, speed, time left
  uv run python scripts/harvest.py compile             # -> data/trajectories.csv and friends

Ctrl+C once stops after the current scan; twice stops at once. Either way, and
even if the machine loses power, nothing on disk is ever half-written (see
app/harvest.py), so `run` simply carries on from the last finished scan.

Pipeline: `--workers` threads each download a series with s5cmd and turn it
into Sybil's input volume on the CPU, deleting the DICOMs straight away; the
main thread runs the five networks on the GPU and saves. Downloading and
reading the DICOMs is the slow part, so the GPU is kept busy by several workers.

Participants are taken in a seeded random order, scan by scan, so whatever
has finished when you stop is a random sample of complete T0/T1/T2 triples.
"""
from __future__ import annotations

import argparse
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, List, Optional

from app.config import settings
from app.harvest import (HarvestDir, compile_dataset, default_dir, eligible, load_model,
                         order, scan_record, score_volume)
from app.trajectory import ROUNDS

log = logging.getLogger("harvest")
AWS_ENDPOINT = "https://s3.amazonaws.com"
DOWNLOAD_TRIES = 3
# Download failures are usually the network, so they are retried on the next run;
# anything later (an unreadable or rejected series) is final unless --retry-failed.
TRANSIENT_STAGES = {"download"}


class Stopping(Exception):
    """Raised inside a worker when a stop was requested mid-task."""


@dataclass
class Task:
    nlst_pid: str
    round: int
    exam_id: str
    years: float


@dataclass
class Prepared:
    task: Task
    volume: Any = None
    series: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    error: Optional[str] = None
    stage: str = ""


# --- stopping -------------------------------------------------------------------

class StopSignal:
    """Set by Ctrl+C, Ctrl+Break, or the STOP file; a second Ctrl+C quits at once."""

    def __init__(self, stop_file: Path):
        self.stop_file = stop_file
        self.event = threading.Event()
        self.presses = 0

    def install(self) -> None:
        signal.signal(signal.SIGINT, self._on_signal)
        if hasattr(signal, "SIGBREAK"):  # Windows Ctrl+Break
            signal.signal(signal.SIGBREAK, self._on_signal)

    def _on_signal(self, signum, frame) -> None:
        self.presses += 1
        if self.presses > 1:
            raise KeyboardInterrupt
        log.warning("stopping after the current scan (Ctrl+C again to stop right now; "
                    "nothing will be corrupted either way)")
        self.event.set()

    def requested(self) -> bool:
        if not self.event.is_set() and self.stop_file.exists():
            log.warning("STOP file found: stopping after the current scan")
            self.event.set()
        return self.event.is_set()


class RunLock:
    """One harvest per directory. The OS drops the lock if the process dies."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.fh = open(self.path, "a+")
        try:
            self.fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        return True

    def held_elsewhere(self) -> bool:
        if self.acquire():
            self.release()
            return False
        return True

    def release(self) -> None:
        if self.fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None


# --- workers: download + prepare on the CPU -------------------------------------------

class Downloader:
    """s5cmd straight from the public IDC bucket, so several can run at once."""

    def __init__(self, stop: StopSignal):
        from app.idc import get_client

        client = get_client()
        self.s5cmd = client.s5cmdPath
        index = client.index[["SeriesInstanceUID", "aws_bucket", "crdc_series_uuid"]]
        self.urls = {uid: f"s3://{bucket}/{uuid}/*" for uid, bucket, uuid
                     in index.itertuples(index=False)}
        self.stop = stop

    def fetch(self, series_uid: str, dest: Path) -> List[str]:
        url = self.urls.get(series_uid)
        if url is None:
            raise RuntimeError(f"series {series_uid} is not in the IDC index")
        dest.mkdir(parents=True, exist_ok=True)
        cmd = [self.s5cmd, "--no-sign-request", "--endpoint-url", AWS_ENDPOINT, "cp", url, f"{dest}{os.sep}"]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        while True:
            try:
                _, err = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if self.stop.requested():
                    proc.kill()
                    proc.communicate()
                    raise Stopping()
        if proc.returncode != 0:
            raise RuntimeError(f"s5cmd exit {proc.returncode}: {err.decode(errors='replace')[-300:]}")
        paths = sorted(str(p) for p in dest.rglob("*") if p.is_file() and p.suffix.lower() in {".dcm", ""})
        if not paths:
            raise RuntimeError(f"no DICOM files downloaded for series {series_uid}")
        return paths


def prepare(task: Task, exam: dict, dl: Downloader, hd: HarvestDir, stop: StopSignal) -> Prepared:
    from sybil import Serie

    from app.fetch import verify_series

    out = Prepared(task)
    dest = hd.tmp / task.exam_id
    try:
        t0 = time.time()
        out.stage = "download"
        for attempt in range(1, DOWNLOAD_TRIES + 1):
            shutil.rmtree(dest, ignore_errors=True)
            try:
                paths = dl.fetch(exam["series_uid"], dest)
                break
            except Stopping:
                raise
            except Exception as exc:
                if attempt == DOWNLOAD_TRIES:
                    raise
                log.warning("%s download attempt %d failed (%s), retrying", task.exam_id, attempt, exc)
                if stop.event.wait(15 * attempt):
                    raise Stopping()
        out.timings["download"] = round(time.time() - t0, 1)

        t0 = time.time()
        out.stage = "reading"
        out.series = verify_series(paths)
        serie = Serie(paths)  # rejects > 5 mm slices
        out.volume = serie.get_volume()
        out.timings["prepare"] = round(time.time() - t0, 1)
    except Stopping:
        out.error, out.stage = "stopped", "stopped"
    except Exception as exc:
        # Ctrl+C reaches s5cmd too, so a failure during a stop is the stop
        out.error = "stopped" if stop.event.is_set() else f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(dest, ignore_errors=True)  # the volume is in memory now
    return out


def worker(tasks: Iterator[Task], tasks_lock: threading.Lock, ready: "queue.Queue",
           exams_by_id, dead: set, dl: Downloader, hd: HarvestDir, stop: StopSignal) -> None:
    while not stop.requested():
        with tasks_lock:
            task = next(tasks, None)
            while task is not None and task.nlst_pid in dead:
                task = next(tasks, None)
        if task is None:
            break
        item = prepare(task, exams_by_id[task.exam_id], dl, hd, stop)
        while True:  # a bounded queue keeps at most a few volumes (~150 MB each) in memory
            try:
                ready.put(item, timeout=0.5)
                break
            except queue.Full:
                if stop.requested() and item.error == "stopped":
                    break
    ready.put(None)


# --- commands ----------------------------------------------------------------------

def pick_device(choice: str) -> str:
    import torch

    if choice != "auto":
        if choice.startswith("cuda") and not torch.cuda.is_available():
            raise SystemExit("--device cuda, but torch sees no CUDA GPU. Is the NVIDIA driver installed, "
                             f"and is torch the +cu117 build? (torch {torch.__version__})")
        return choice
    if torch.cuda.is_available():
        return "cuda"
    log.warning("no CUDA GPU visible to torch %s -- running on the CPU, ~1.5 min per scan", torch.__version__)
    return "cpu"


def verify(model, device: str, rel_tol: float) -> None:
    """Run upstream's demo scan and compare with its published scores before spending days."""
    from sybil import Serie

    from app.demo_data import EXPECTED_DEMO_SCORES, demo_dicom_paths

    t0 = time.time()
    scored = score_volume(model, Serie(demo_dicom_paths()).get_volume())
    worst = max(abs(a - e) / e for a, e in zip(scored.calibrated, EXPECTED_DEMO_SCORES))
    log.info("check on upstream's demo scan (%s): max relative difference %.2e in %.1fs",
             device, worst, time.time() - t0)
    if worst > rel_tol:
        raise SystemExit(f"{device} scores differ from the published ones by {worst:.2e} "
                         f"(> {rel_tol:g}). Not starting; try --device cpu to compare.")


def cmd_run(args) -> int:
    hd = HarvestDir(args.out)
    hd.ensure()
    lock = RunLock(hd.lock_file)
    if not lock.acquire():
        raise SystemExit(f"a harvest is already running in {hd.root}")
    try:
        return _run(args, hd)
    finally:
        lock.release()


def _run(args, hd: HarvestDir) -> int:
    from app.data import exams

    hd.stop_file.unlink(missing_ok=True)
    hd.clean_leftovers()
    stop = StopSignal(hd.stop_file)
    stop.install()

    pool = eligible()
    exam_table = exams()
    done = hd.done()
    failed = hd.failed()
    final = {e for e, rec in failed.items() if rec["stage"] not in TRANSIENT_STAGES and not args.retry_failed}
    dead = {failed[e]["nlst_pid"] for e in final}

    exam_of = {r: pool[f"exam_t{r}"].to_dict() for r in ROUNDS}
    years_of = {r: pool[f"t{r}_years"].to_dict() for r in ROUNDS}
    pids = [p for p in order(pool, args.seed, args.cancer_first) if p not in dead]
    remaining = [p for p in pids if any(exam_of[r][p] not in done for r in ROUNDS)]
    if args.limit is not None:
        remaining = remaining[:args.limit]
    task_list = [Task(p, r, exam_of[r][p], float(years_of[r][p]))
                 for p in remaining for r in ROUNDS if exam_of[r][p] not in done]
    log.info("%d participants have three eligible scans; %d scans already done, %d participants "
             "skipped after a failure; %d scans (%d participants) to go this run",
             len(pool), len(done), len(dead), len(task_list), len(remaining))
    if not task_list:
        return _compile(hd, args)

    device = pick_device(args.device)
    if device.startswith("cuda"):
        import torch
        log.info("GPU: %s", torch.cuda.get_device_name(0))
    model = load_model(device)
    if not args.skip_check:
        verify(model, device, args.rel_tol)

    exams_by_id = exam_table.loc[[t.exam_id for t in task_list]].to_dict("index")
    dl = Downloader(stop)
    tasks, tasks_lock = iter(task_list), threading.Lock()
    ready: "queue.Queue[Optional[Prepared]]" = queue.Queue(maxsize=max(2, args.workers))
    threads = [threading.Thread(target=worker, name=f"prep-{i}", daemon=True,
                                args=(tasks, tasks_lock, ready, exams_by_id, dead, dl, hd, stop))
               for i in range(args.workers)]
    for t in threads:
        t.start()

    finished, failures, alive, t_start = 0, 0, len(threads), time.time()
    try:
        while alive:
            try:
                item = ready.get(timeout=1.0)
            except queue.Empty:
                stop.requested()  # notice the STOP file even while waiting
                continue
            if item is None:
                alive -= 1
                continue
            task = item.task
            if item.error == "stopped":
                continue
            if item.error:
                failures += 1
                dead.add(task.nlst_pid)
                hd.record_failure(task.exam_id, task.nlst_pid, item.stage, item.error)
                log.error("%s (T%d of %s) failed at %s: %s", task.exam_id, task.round,
                          task.nlst_pid, item.stage, item.error)
                continue
            t0 = time.time()
            try:
                scored = score_volume(model, item.volume)
            except Exception as exc:
                failures += 1
                dead.add(task.nlst_pid)
                hd.record_failure(task.exam_id, task.nlst_pid, "model", f"{type(exc).__name__}: {exc}")
                log.exception("%s failed in the model", task.exam_id)
                continue
            finally:
                item.volume = None
            item.timings["model"] = round(time.time() - t0, 2)
            hd.save(scan_record(task.exam_id, task.nlst_pid, task.round, task.years,
                                exams_by_id[task.exam_id], item.series, scored, device, item.timings),
                    scored)
            finished += 1
            rate = finished / max(time.time() - t_start, 1e-9) * 3600
            left = len(task_list) - finished - failures
            log.info("%s T%d of %s: 6y risk %.1f%% | %s | %d done, %d to go, %.0f scans/h, ~%.1f h left",
                     task.exam_id, task.round, task.nlst_pid, scored.calibrated[-1] * 100,
                     " ".join(f"{k} {v}s" for k, v in item.timings.items()),
                     finished, left, rate, left / max(rate, 1e-9))
    except KeyboardInterrupt:
        log.warning("stopped at once; %d scans saved this run, run again to resume", finished)
        return 130

    log.info("%s: %d scans saved, %d failed this run, in %.1f h",
             "stopped" if stop.event.is_set() else "finished", finished, failures,
             (time.time() - t_start) / 3600)
    hd.stop_file.unlink(missing_ok=True)
    return _compile(hd, args)


def _compile(hd: HarvestDir, args) -> int:
    target = None if args.no_csv else Path(args.csv)
    summary = compile_dataset(hd, target)
    log.info("compiled %d scans, %d complete participants%s", summary["scans"],
             summary["participants_complete"],
             f" -> {summary['trajectories_csv']}" if summary.get("trajectories_csv") else "")
    if len(summary.get("devices", [])) > 1:
        log.warning("scans come from more than one device (%s); scores can differ slightly",
                    ", ".join(summary["devices"]))
    return 0


def cmd_compile(args) -> int:
    return _compile(HarvestDir(args.out), args)


def cmd_stop(args) -> int:
    hd = HarvestDir(args.out)
    if not RunLock(hd.lock_file).held_elsewhere():
        print("no harvest is running")
        return 0
    hd.stop_file.write_text("stop requested\n", encoding="utf-8")
    print("asked the harvest to stop; it finishes the scan on the GPU and exits within a minute")
    return 0


def cmd_status(args) -> int:
    import datetime as dt

    hd = HarvestDir(args.out)
    hd.ensure()
    running = RunLock(hd.lock_file).held_elsewhere()
    pool = eligible()
    done = hd.done()
    failed = hd.failed()
    done_pids = {}
    exam_to_pid = {e: p for r in ROUNDS for p, e in pool[f"exam_t{r}"].items()}
    for e in done:
        if e in exam_to_pid:
            done_pids[exam_to_pid[e]] = done_pids.get(exam_to_pid[e], 0) + 1
    complete = sum(1 for n in done_pids.values() if n == len(ROUNDS))
    total = len(pool) * len(ROUNDS)
    print(f"{'running' if running else 'not running'}  ({hd.root})")
    print(f"scans          {len(done):>7} of {total} ({len(done) / total:.1%})")
    print(f"participants   {complete:>7} of {len(pool)} complete")
    print(f"failed scans   {len(failed):>7}  (see failed.jsonl)")

    recent = sorted(hd.scans.glob("*.json"), key=lambda p: p.stat().st_mtime)[-200:]
    if len(recent) >= 2:
        span = recent[-1].stat().st_mtime - recent[0].stat().st_mtime
        if span > 0:
            rate = (len(recent) - 1) / span * 3600
            left = (total - len(done)) / rate
            print(f"speed          {rate:>7.0f} scans/h over the last {len(recent)}; "
                  f"~{left / 24:.1f} days left")
        last = dt.datetime.fromtimestamp(recent[-1].stat().st_mtime)
        print(f"last scan      {last:%Y-%m-%d %H:%M:%S}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=default_dir(), help="harvest directory (default: %(default)s)")
    sub = ap.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="start or resume")
    run.add_argument("--workers", type=int, default=4, help="parallel download + prepare threads")
    run.add_argument("--limit", type=int, default=None, help="at most this many more participants")
    run.add_argument("--device", default="auto", help="auto (CUDA if available), cuda, cuda:1, cpu")
    run.add_argument("--seed", type=int, default=20261027, help="participant order")
    run.add_argument("--cancer-first", action="store_true",
                     help="do the 455 participants diagnosed within 6 years first -- not a random sample")
    run.add_argument("--retry-failed", action="store_true", help="try scans that failed for good before")
    run.add_argument("--skip-check", action="store_true", help="skip the demo-scan check at start-up")
    run.add_argument("--rel-tol", type=float, default=1e-3, help="allowed difference in that check")

    for p in (run, sub.add_parser("compile", help="rebuild the tables from the finished scans")):
        p.add_argument("--csv", default=str(settings.data_dir / "trajectories.csv"),
                       help="where complete participants go (default: %(default)s)")
        p.add_argument("--no-csv", action="store_true", help="don't write that CSV")
    sub.add_parser("stop", help="ask a running harvest to stop after the current scan")
    sub.add_parser("status", help="progress and speed")
    args = ap.parse_args()

    if args.command == "run":
        args.out.mkdir(parents=True, exist_ok=True)
        handlers = [logging.StreamHandler(sys.stdout),
                    logging.FileHandler(args.out / "harvest.log", encoding="utf-8")]
        logging.basicConfig(level=logging.INFO, handlers=handlers,
                            format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return {"run": cmd_run, "compile": cmd_compile, "stop": cmd_stop, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
