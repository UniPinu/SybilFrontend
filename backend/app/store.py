"""The on-disk cache of processed patients.

Layout (MVP.md section 5.5):

    cache/patients/{patient_id}/
        meta.json      person card, series info, timings
        result.json    calibrated + raw scores, slice attention, hotspot
        outcome.json   the reveal -- served only from /outcome
        slices/000.webp ...
        overlay/000.webp ...
        coronal.webp
    cache/pool.json    which patients are pinned (curated pool + reference)
    cache/tmp/         DICOMs mid-flight, deleted as soon as result.json lands

Curated and reference patients are pinned; live-mode patients are evicted
oldest-first once the cache passes CACHE_MAX_MB.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from app.config import settings

log = logging.getLogger(__name__)

META = "meta.json"
RESULT = "result.json"
OUTCOME = "outcome.json"
POOL_FILE = "pool.json"


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False, default=str)
    tmp.replace(path)


@dataclass(frozen=True)
class PoolSets:
    pool: List[str]
    reference: List[str]

    @property
    def pinned(self) -> set[str]:
        return set(self.pool) | set(self.reference)


class PatientStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = root or settings.patients_dir
        self.cache_root = self.root.parent
        self.root.mkdir(parents=True, exist_ok=True)

    # --- paths -----------------------------------------------------------
    def dir_for(self, patient_id: str) -> Path:
        safe = patient_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self.root / safe

    def slice_path(self, patient_id: str, index: int) -> Path:
        return self.dir_for(patient_id) / "slices" / f"{index:03d}.webp"

    def overlay_path(self, patient_id: str, index: int) -> Path:
        return self.dir_for(patient_id) / "overlay" / f"{index:03d}.webp"

    def coronal_path(self, patient_id: str) -> Path:
        return self.dir_for(patient_id) / "coronal.webp"

    # --- reads -----------------------------------------------------------
    def is_ready(self, patient_id: str) -> bool:
        d = self.dir_for(patient_id)
        return (d / RESULT).exists() and (d / META).exists()

    def meta(self, patient_id: str) -> Optional[dict]:
        return _read_json(self.dir_for(patient_id) / META)

    def result(self, patient_id: str) -> Optional[dict]:
        return _read_json(self.dir_for(patient_id) / RESULT)

    def outcome(self, patient_id: str) -> Optional[dict]:
        return _read_json(self.dir_for(patient_id) / OUTCOME)

    def list_ready(self) -> List[str]:
        return sorted(p.name for p in self.root.iterdir()
                      if p.is_dir() and (p / RESULT).exists())

    # --- writes ----------------------------------------------------------
    def write_meta(self, patient_id: str, meta: dict) -> None:
        _write_json(self.dir_for(patient_id) / META, meta)

    def write_result(self, patient_id: str, result: dict) -> None:
        _write_json(self.dir_for(patient_id) / RESULT, result)

    def write_outcome(self, patient_id: str, outcome: dict) -> None:
        _write_json(self.dir_for(patient_id) / OUTCOME, outcome)

    def remove(self, patient_id: str) -> None:
        shutil.rmtree(self.dir_for(patient_id), ignore_errors=True)

    def touch(self, patient_id: str) -> None:
        """Mark a patient as recently used, for LRU eviction."""
        d = self.dir_for(patient_id)
        if d.exists():
            marker = d / ".used"
            marker.write_text(str(time.time()), encoding="utf-8")

    def last_used(self, patient_id: str) -> float:
        d = self.dir_for(patient_id)
        marker = d / ".used"
        if marker.exists():
            try:
                return float(marker.read_text(encoding="utf-8"))
            except ValueError:
                pass
        try:
            return d.stat().st_mtime
        except OSError:
            return 0.0

    # --- pinning ---------------------------------------------------------
    def pool_sets(self) -> PoolSets:
        data = _read_json(self.cache_root / POOL_FILE) or {}
        return PoolSets(pool=list(data.get("pool", [])),
                        reference=list(data.get("reference", [])))

    def write_pool_sets(self, pool: List[str], reference: List[str]) -> None:
        _write_json(self.cache_root / POOL_FILE,
                    {"pool": sorted(set(pool)), "reference": sorted(set(reference))})

    # --- size / eviction --------------------------------------------------
    def size_mb(self, patient_id: Optional[str] = None) -> float:
        target = self.dir_for(patient_id) if patient_id else self.root
        if not target.exists():
            return 0.0
        total = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
        return round(total / 1e6, 2)

    def evict(self, max_mb: Optional[float] = None) -> List[str]:
        """Drop least-recently-used *unpinned* patients until under the cap."""
        cap = settings.cache_max_mb if max_mb is None else max_mb
        pinned = self.pool_sets().pinned
        evicted: List[str] = []
        while self.size_mb() > cap:
            candidates = [p for p in self.list_ready() if p not in pinned]
            if not candidates:
                log.warning("cache over %s MB but every patient is pinned", cap)
                break
            oldest = min(candidates, key=self.last_used)
            log.info("evicting %s (cache %.0f MB > %s MB)", oldest, self.size_mb(), cap)
            self.remove(oldest)
            evicted.append(oldest)
        return evicted

    # --- temp DICOMs ------------------------------------------------------
    def tmp_dir_for(self, patient_id: str) -> Path:
        d = settings.tmp_dir / self.dir_for(patient_id).name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def clear_tmp(self, patient_id: Optional[str] = None) -> None:
        target = settings.tmp_dir / self.dir_for(patient_id).name if patient_id else settings.tmp_dir
        shutil.rmtree(target, ignore_errors=True)

    def stats(self) -> Dict[str, object]:
        sets = self.pool_sets()
        ready = set(self.list_ready())
        return {
            "cache_mb": self.size_mb(),
            "cache_max_mb": settings.cache_max_mb,
            "patients_ready": len(ready),
            # pool.json is written as the pool is built, so count only what is usable now
            "pool": len([p for p in sets.pool if p in ready]),
            "reference": len([p for p in sets.reference if p in ready]),
            "tmp_mb": round(sum(p.stat().st_size for p in settings.tmp_dir.rglob("*")
                                if p.is_file()) / 1e6, 2) if settings.tmp_dir.exists() else 0.0,
        }


store = PatientStore()
