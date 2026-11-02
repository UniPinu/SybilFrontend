"""Extract Sybil's features for every round of many participants -> data/features/.

  uv run python scripts/build_features.py --n 40 --cancer-share 0.3
  uv run python scripts/build_features.py --n 40 --dry-run
  uv run python scripts/build_features.py --cached          # every scan already in the cache

Each exam gets data/features/{exam_id}.npz (see app/features.py). Scans that
were run before features were saved have no vector, and their DICOMs are long
gone, so they are downloaded and run again; the scores come out identical.

Participants are drawn exactly as scripts/build_trajectories.py draws them
(three eligible, dated rounds; fully cached people first), and each finished
participant is also appended to data/trajectories.csv, so the Experiment page
grows too. Resumable: an exam that already has features is never re-run.

Cost: ~1.5 min per scan on a 16-thread CPU, ~4.5 min per participant.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from build_trajectories import already_done, append, eligible, plan

from app import features
from app.config import settings
from app.pipeline import PipelineError, process_patient
from app.store import store
from app.trajectory import ROUNDS, risk_columns

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("build_features")


def _progress(exam_id: str):
    seen: set = set()

    def emit(stage: str, **payload) -> None:
        if stage == "model":
            print(f"  {exam_id} expert {payload['index']} of {payload['of']}", flush=True)
        elif stage not in seen:
            seen.add(stage)
            print(f"  {exam_id} {stage}", flush=True)
    return emit


def extract(exam_id: str) -> list:
    """Make sure `exam_id` has features; returns its six calibrated risks."""
    if features.has(exam_id):
        return [float(x) for x in features.load(exam_id)["risk_by_year"]]
    # a cached result without features has to be run again to get them
    return process_patient(exam_id, emit=_progress(exam_id), force=store.is_ready(exam_id)).risk_by_year


def todo_scans(ids) -> list:
    return [e for e in ids if not features.has(e)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=40, help="participants with features for all 3 rounds")
    ap.add_argument("--seed", type=int, default=20261027)
    ap.add_argument("--cancer-share", type=float, default=0.3,
                    help="fraction of new picks diagnosed within 6 years (population: ~2%%)")
    ap.add_argument("--cached", action="store_true",
                    help="instead: extract features for every scan already in the cache")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    args = ap.parse_args()
    settings.ensure_dirs()

    if args.cached:
        queue = todo_scans(store.list_ready())
        print(f"{len(queue)} cached scans have no features, ~{len(queue) * 1.6 / 60:.1f} h")
        if args.dry_run:
            return 0
        for i, exam_id in enumerate(queue, 1):
            log.info("scan %s (%d of %d)", exam_id, i, len(queue))
            try:
                extract(exam_id)
            except PipelineError as exc:
                log.error("%s skipped: failed at %s: %s", exam_id, exc.stage, exc)
        return 0

    pool = eligible()
    exams_of = {pid: [pool.loc[pid, f"exam_t{r}"] for r in ROUNDS] for pid in pool.index}
    complete = {pid for pid, ids in exams_of.items() if not todo_scans(ids)}
    queue = [p for p in plan(pool, args.n, args.seed, args.cancer_share, set())
             if p not in complete]
    wanted = max(0, args.n - len(complete))
    preview = queue[:wanted]
    scans = sum(len(todo_scans(exams_of[p])) for p in preview)
    print(f"{len(pool)} participants have three eligible rounds; {len(complete)} already have "
          f"features for all three, {wanted} to go: {scans} scans, ~{scans * 1.6 / 60:.1f} h")
    if args.dry_run or not wanted:
        return 0

    traj_csv = settings.data_dir / "trajectories.csv"
    in_csv = already_done(traj_csv)
    t_start, added = time.time(), 0
    for pid in queue:
        if added >= wanted:
            break
        t0 = time.time()
        log.info("participant %s (%d of %d)", pid, added + 1, wanted)
        row = pool.loc[pid]
        out = {"nlst_pid": pid, "diagnosed": row["diagnosed"],
               "years_rand_to_dx": row["years_rand_to_dx"]}
        try:
            for r, exam_id in zip(ROUNDS, exams_of[pid]):
                out[f"t{r}_years"] = row[f"t{r}_years"]
                out.update(zip(risk_columns(r), extract(exam_id)))
        except PipelineError as exc:
            log.error("%s skipped: failed at %s: %s", pid, exc.stage, exc)
            continue
        except KeyboardInterrupt:
            log.warning("interrupted -- %d added this run, re-run to resume", added)
            raise
        if pid not in in_csv:
            append(traj_csv, out)
            in_csv.add(pid)
        added += 1
        log.info("%s done in %.0fs", pid, time.time() - t0)

    print(f"\nadded {added} participants in {(time.time() - t_start) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
