"""One patient, end to end: fetch -> verify -> run Sybil -> render -> cache.

Used by both the job queue (live mode) and scripts/prepare_pool.py, so the
curated pool and a live run produce byte-identical artifacts.
"""
from __future__ import annotations

import datetime as dt
import logging
import shutil
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.config import settings
from app.data import get_candidate, outcome_payload, without_outcome
from app.demo_data import DEMO_PATIENT_ID, demo_dicom_paths
from app.fetch import fetch_series, verify_series
from app.render import render_patient
from app.runner import run_sybil
from app.store import store

log = logging.getLogger(__name__)

Emit = Callable[..., None]


def _noop(stage: str, **payload: Any) -> None:
    pass


class PipelineError(RuntimeError):
    def __init__(self, message: str, stage: str):
        super().__init__(message)
        self.stage = stage


@dataclass
class Processed:
    patient_id: str
    risk_by_year: List[float]
    from_cache: bool
    seconds: float


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def model_info() -> Dict[str, Any]:
    import sybil
    import torch

    return {
        "name": settings.model_name,
        "device": settings.device,
        "threads": settings.threads,
        "sybil_version": sybil.__version__,
        "sybil_commit": "d9fc81b93c1c6239a570c1c570c1f2a2e6266a4a",
        "torch": torch.__version__,
    }


def process_patient(
    patient_id: str,
    emit: Optional[Emit] = None,
    *,
    force: bool = False,
    keep_dicoms: bool = False,
) -> Processed:
    """Make `patient_id` ready to display. Idempotent unless `force`."""
    emit = emit or _noop
    t_start = dt.datetime.now()

    if store.is_ready(patient_id) and not force:
        store.touch(patient_id)
        result = store.result(patient_id) or {}
        emit("done", patient_id=patient_id, cached=True)
        return Processed(patient_id, result.get("risk_by_year", []), True, 0.0)

    is_demo = patient_id == DEMO_PATIENT_ID
    candidate = None if is_demo else get_candidate(patient_id)
    if not is_demo and candidate is None:
        raise PipelineError(f"unknown patient {patient_id}", stage="lookup")

    tmp = store.tmp_dir_for(patient_id)
    try:
        # --- 1. the scan ------------------------------------------------
        if is_demo:
            emit("downloading", bytes_done=0, bytes_total=0, detail="offline demo scan")
            paths = demo_dicom_paths()
            fetch_seconds, fetched_bytes = 0.0, 0
        else:
            size_mb = float(candidate["series_size_mb"])
            emit("downloading", bytes_done=0, bytes_total=int(size_mb * 1e6))

            def on_bytes(done: int, total: int) -> None:
                emit("downloading", bytes_done=done, bytes_total=total)

            try:
                fetched = fetch_series(
                    candidate["series_uid"], tmp, expected_mb=size_mb, progress=on_bytes
                )
            except Exception as exc:  # network, s5cmd, missing series
                raise PipelineError(str(exc), stage="downloading") from exc
            paths, fetch_seconds, fetched_bytes = (
                fetched.paths, fetched.seconds, fetched.bytes_downloaded,
            )

        # --- 2. trust the header, not the index -------------------------
        try:
            series_info = verify_series(paths)
        except Exception as exc:
            raise PipelineError(f"could not read the DICOM header: {exc}", stage="reading") from exc
        series_info["size_mb"] = round(fetched_bytes / 1e6, 1) if fetched_bytes else None
        series_info["download_seconds"] = round(fetch_seconds, 1)
        if candidate is not None:
            expected = float(candidate["thickness_mm"])
            if abs(series_info["thickness_mm"] - expected) > 0.05:
                # SeriesDescription field 7 is parsed from observed data, so a
                # mismatch is worth recording rather than trusting blindly.
                log.warning("%s: thickness %s from DICOM vs %s parsed from "
                            "SeriesDescription", patient_id,
                            series_info["thickness_mm"], expected)
                series_info["thickness_mismatch"] = expected

        # --- 3. the model ------------------------------------------------
        try:
            result = run_sybil(paths, emit=emit)
        except Exception as exc:
            raise PipelineError(str(exc), stage="model") from exc

        # --- 4. pictures -------------------------------------------------
        emit("rendering")
        out_dir = store.dir_for(patient_id)
        try:
            rendered = render_patient(
                result.serie, result.attention_grid, result.geometry, out_dir
            )
        except Exception as exc:
            raise PipelineError(str(exc), stage="rendering") from exc

        # --- 5. write the three JSONs ------------------------------------
        store.write_meta(
            patient_id,
            {
                "patient_id": patient_id,
                "created_at": _now(),
                "is_demo": is_demo,
                # outcome fields are stripped: meta.json feeds the person card
                "candidate": without_outcome(candidate) if candidate else None,
                "series": series_info,
            },
        )
        store.write_result(
            patient_id,
            {
                "patient_id": patient_id,
                "created_at": _now(),
                "risk_by_year": [round(v, 6) for v in result.calibrated],
                "raw_mean": [round(v, 6) for v in result.raw_mean],
                "raw_per_model": [[round(v, 6) for v in row] for row in result.raw_per_model],
                "geometry": result.geometry.as_dict(),
                # 25x16x16, ~100 KB: enough to redraw every overlay without
                # running the ensemble again
                "attention_grid": [[[round(float(v), 7) for v in row] for row in plane]
                                   for plane in result.attention_grid],
                "timings": {**result.timings, "download": round(fetch_seconds, 1)},
                "model": model_info(),
                **rendered.as_dict(),
            },
        )
        if is_demo:
            store.write_outcome(
                patient_id,
                {
                    "patient_id": patient_id,
                    "available": False,
                    "note": "Upstream's demo scan has no outcome attached, so there is "
                            "nothing to reveal for this person.",
                },
            )
        else:
            store.write_outcome(patient_id, {**outcome_payload(candidate), "available": True})

        store.touch(patient_id)
    finally:
        if not keep_dicoms:
            shutil.rmtree(tmp, ignore_errors=True)

    evicted = store.evict()
    if evicted:
        log.info("evicted %d patient(s) to stay under %s MB",
                 len(evicted), settings.cache_max_mb)

    seconds = (dt.datetime.now() - t_start).total_seconds()
    emit("done", patient_id=patient_id, cached=False, seconds=round(seconds, 1))
    log.info("%s ready in %.1fs (%.1f MB on disk)",
             patient_id, seconds, store.size_mb(patient_id))
    return Processed(patient_id, [round(v, 6) for v in result.calibrated], False, seconds)
