"""M4: build the curated pool and the reference sample.

  uv run python scripts/prepare_pool.py --pool 16 --reference 12

Downloads, runs and renders one person at a time (~83 MB and ~2 min each), and
deletes every DICOM as soon as the result lands. Safe to interrupt: already
prepared people are skipped, so re-running resumes.

Why a curated pool at all: only ~3% of screened participants are diagnosed
within six years, so random picks would almost always be "healthy, low risk".
The pool is deliberately half cancer / half not, which the UI states plainly.
The reference sample stays *unbalanced*, because that is what defines a typical
screening participant on the risk chart.
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from typing import List, Optional, Sequence

import pandas as pd

from app.config import settings
from app.data import candidates
from app.pipeline import PipelineError, process_patient
from app.store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("prepare_pool")


def _choose(
    df: pd.DataFrame,
    n: int,
    rng: random.Random,
    *,
    used_pids: set[str],
    prefer_regression: bool = True,
) -> List[str]:
    """Pick n exams, at most one per participant, regression-set series first."""
    picked: List[str] = []
    groups: List[pd.DataFrame] = []
    if prefer_regression:
        groups.append(df[df.in_regression_set])
    groups.append(df[~df.in_regression_set] if prefer_regression else df)

    for group in groups:
        rows = group.sample(frac=1.0, random_state=rng.randrange(1 << 30)) if len(group) else group
        for row in rows.itertuples(index=False):
            if len(picked) >= n:
                return picked
            if row.nlst_pid in used_pids:
                continue
            used_pids.add(row.nlst_pid)
            picked.append(row.patient_id)
    return picked


def plan(pool_size: int, reference_size: int, seed: int) -> tuple[List[str], List[str]]:
    rng = random.Random(seed)
    df = candidates()
    used: set[str] = set()

    cancer = df[df.cancer_within_6y]
    healthy = df[~df.cancer_within_6y]
    half = pool_size // 2
    pool = _choose(cancer, half, rng, used_pids=used)
    pool += _choose(healthy, pool_size - len(pool), rng, used_pids=used)

    # The reference sample must look like the real population: unbalanced,
    # no regression-set preference.
    reference = _choose(df, reference_size, rng, used_pids=used, prefer_regression=False)
    return pool, reference


def prepare(ids: Sequence[str], label: str, *, pool: List[str], reference: List[str],
            fallbacks: Optional[List[str]] = None, pin: bool = True,
            force: bool = False) -> List[str]:
    """Process each id, substituting a fallback when one fails outright.

    `pin=False` prepares people without touching pool.json, so `--only` cannot
    unpin a pool that is already built.
    """
    done: List[str] = []
    queue = list(ids)
    spares = list(fallbacks or [])
    while queue:
        patient_id = queue.pop(0)
        if store.is_ready(patient_id) and not force:
            log.info("[%s] %s already prepared", label, patient_id)
            done.append(patient_id)
            if pin:
                _pin(pool, reference, label, done)
            continue
        t0 = time.time()
        log.info("[%s] %s starting", label, patient_id)
        try:
            process_patient(patient_id, emit=_progress(patient_id), force=force)
        except PipelineError as exc:
            log.error("[%s] %s failed at %s: %s", label, patient_id, exc.stage, exc)
            if spares:
                replacement = spares.pop(0)
                log.info("[%s] substituting %s", label, replacement)
                queue.append(replacement)
            continue
        except KeyboardInterrupt:
            log.warning("interrupted -- %d of %d done, re-run to resume", len(done), len(ids))
            raise
        done.append(patient_id)
        if pin:
            _pin(pool, reference, label, done)
        log.info("[%s] %s ready in %.0fs (cache %.0f MB)",
                 label, patient_id, time.time() - t0, store.size_mb())
    return done


def _pin(pool: List[str], reference: List[str], label: str, done: List[str]) -> None:
    """Keep pool.json current so an interrupted run never gets evicted."""
    sets = store.pool_sets()
    if label == "pool":
        store.write_pool_sets(sorted(set(done)), sets.reference or reference)
    else:
        store.write_pool_sets(sets.pool or pool, sorted(set(done)))


def _progress(patient_id: str):
    state = {"last": 0.0}

    def emit(stage: str, **payload) -> None:
        if stage == "downloading":
            done, total = payload.get("bytes_done", 0), payload.get("bytes_total", 0)
            now = time.time()
            if total and now - state["last"] > 2:
                state["last"] = now
                print(f"  {patient_id} downloading {done / 1e6:5.0f} / {total / 1e6:.0f} MB",
                      flush=True)
        elif stage == "model":
            print(f"  {patient_id} expert {payload['index']} of {payload['of']}", flush=True)
        elif stage in {"reading", "standardizing", "calibrating", "rendering"}:
            print(f"  {patient_id} {stage}", flush=True)

    return emit


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", type=int, default=16, help="curated pool size (half cancer)")
    ap.add_argument("--reference", type=int, default=12, help="unbalanced reference sample size")
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    ap.add_argument("--only", default=None, help="comma-separated patient ids to prepare instead")
    ap.add_argument("--force", action="store_true",
                    help="re-download and re-run people that are already prepared")
    args = ap.parse_args()

    settings.ensure_dirs()

    if args.only:
        ids = [p for p in args.only.split(",") if p]
        prepare(ids, "only", pool=[], reference=[], pin=False, force=args.force)
        return 0

    pool, reference = plan(args.pool, args.reference, args.seed)
    df = candidates().set_index("patient_id", drop=False)
    print(f"plan: {len(pool)} pool + {len(reference)} reference")
    for label, ids in (("pool", pool), ("reference", reference)):
        for pid in ids:
            row = df.loc[pid]
            flag = "cancer" if row.cancer_within_6y else "no cancer"
            extra = " [regression set]" if row.in_regression_set else ""
            print(f"  {label:<9} {pid:<14} {row.series_size_mb:5.0f} MB  {flag}{extra}")
    total_mb = float(df.loc[pool + reference, "series_size_mb"].sum())
    print(f"one-time download: {total_mb / 1000:.1f} GB (deleted as it goes)")
    if args.dry_run:
        return 0

    # Spares let a dead series or a bad header be replaced without a rerun.
    spare_pool, spare_reference = plan(args.pool + 6, args.reference + 4, args.seed + 1)
    t0 = time.time()
    done_pool = prepare(pool, "pool", pool=pool, reference=reference,
                        fallbacks=[p for p in spare_pool if p not in pool], force=args.force)
    done_ref = prepare(reference, "reference", pool=done_pool, reference=reference,
                       fallbacks=[p for p in spare_reference if p not in reference],
                       force=args.force)
    store.write_pool_sets(done_pool, done_ref)

    print(f"\nprepared {len(done_pool)} pool + {len(done_ref)} reference "
          f"in {(time.time() - t0) / 60:.1f} min")
    print(f"cache: {store.size_mb():.0f} MB for {len(store.list_ready())} people")
    cancer = sum(1 for pid in done_pool
                 if (store.outcome(pid) or {}).get("cancer_within_6y"))
    print(f"pool balance: {cancer} cancer / {len(done_pool) - cancer} no cancer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
