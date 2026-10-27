"""Run Sybil on T0, T1 and T2 of many participants -> data/trajectories.csv.

  uv run python scripts/build_trajectories.py --n 100
  uv run python scripts/build_trajectories.py --n 100 --cancer-share 0.3 --dry-run

One row per participant: years since randomization of each scan and Sybil's six
risks for each. Rows are appended as soon as a participant's third scan
finishes, so the numbers survive cache eviction and the script resumes where it
stopped. Participants already fully cached are used first, for free.

Cost: three scans per participant at ~1.5 min each on a 16-thread CPU, i.e.
about 4.5 min per participant -- 100 participants is an overnight job, which is
what the university PC is for.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path
from typing import List

import pandas as pd

from app import participants as people
from app.config import settings
from app.data import exams
from app.pipeline import PipelineError, process_patient
from app.store import store
from app.trajectory import CSV_COLUMNS, ROUNDS, risk_columns

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("build_trajectories")


def eligible() -> pd.DataFrame:
    """Participants with an eligible exam in every round and a date for each.

    Indexed by nlst_pid, with one exam id column per round (`exam_t0` ..).
    """
    df = exams()
    if df is None:
        raise SystemExit("data/exams.parquet is missing -- run scripts/build_candidates.py")
    ok = df[df["eligible"] & df["study_yr"].isin(ROUNDS)]
    wide = ok.pivot_table(index="nlst_pid", columns="study_yr", values="patient_id",
                          aggfunc="first").dropna()
    wide.columns = [f"exam_t{int(c)}" for c in wide.columns]
    prsn = people.table()
    year_cols = [f"t{r}_years" for r in ROUNDS]
    joined = wide.join(prsn[year_cols + ["diagnosed", "years_rand_to_dx",
                                         "cancer_within_6y_any"]], how="inner")
    joined = joined.dropna(subset=year_cols)
    # the curve needs T1 strictly after T0
    return joined[joined["t1_years"] > joined["t0_years"]]


def plan(pool: pd.DataFrame, n: int, seed: int, cancer_share: float, done: set) -> List[str]:
    """Fully cached people first, then a seeded random draw (optionally enriched)."""
    cached = [pid for pid, row in pool.iterrows()
              if all(store.is_ready(row[f"exam_t{r}"]) for r in ROUNDS)]
    todo = pool.drop(index=[p for p in cached if p in pool.index])
    shuffled = todo.sample(frac=1.0, random_state=seed)
    n_cancer = round(n * cancer_share)
    if n_cancer:
        cancer = shuffled[shuffled["cancer_within_6y_any"].fillna(False).astype(bool)]
        rest = shuffled.drop(index=cancer.index[:n_cancer])
        ordered = list(cancer.index[:n_cancer]) + list(rest.index)
    else:
        ordered = list(shuffled.index)
    return [p for p in cached + ordered if p not in done]


def already_done(path) -> set:
    if not path.exists():
        return set()
    with open(path, newline="") as fh:
        return {row["nlst_pid"] for row in csv.DictReader(fh)}


def append(path, row: dict) -> None:
    new = not path.exists()
    with open(path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def _progress(exam_id: str):
    seen: set = set()

    def emit(stage: str, **payload) -> None:
        if stage == "model":
            print(f"  {exam_id} expert {payload['index']} of {payload['of']}", flush=True)
        elif stage not in seen:
            seen.add(stage)
            print(f"  {exam_id} {stage}", flush=True)
    return emit


def run_participant(pid: str, row: pd.Series) -> dict:
    out = {"nlst_pid": pid,
           "diagnosed": row["diagnosed"],
           "years_rand_to_dx": row["years_rand_to_dx"]}
    for r in ROUNDS:
        out[f"t{r}_years"] = row[f"t{r}_years"]
        exam_id = row[f"exam_t{r}"]
        risks = process_patient(exam_id, emit=_progress(exam_id)).risk_by_year
        if len(risks) != len(risk_columns(r)):
            raise PipelineError(f"{exam_id} returned {len(risks)} risks", "model")
        out.update(zip(risk_columns(r), risks))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=50, help="participants wanted in the CSV in total")
    ap.add_argument("--seed", type=int, default=20261027)
    ap.add_argument("--cancer-share", type=float, default=0.0,
                    help="fraction of new picks diagnosed within 6 years (population: ~2%%)")
    ap.add_argument("--out", default=str(settings.data_dir / "trajectories.csv"))
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    args = ap.parse_args()

    settings.ensure_dirs()
    out = Path(args.out)
    done = already_done(out)
    pool = eligible()
    queue = plan(pool, args.n, args.seed, args.cancer_share, done)
    wanted = max(0, args.n - len(done))

    print(f"{len(pool)} participants have three eligible rounds; "
          f"{len(done)} already in {out.name}, {wanted} to go")
    preview = queue[:wanted]
    cached = sum(all(store.is_ready(pool.loc[p, f"exam_t{r}"]) for r in ROUNDS) for p in preview)
    print(f"next {len(preview)}: {cached} fully cached, ~{(len(preview) - cached) * 4.5 / 60:.1f} h "
          "of Sybil at ~1.5 min per scan")
    if args.dry_run or not wanted:
        return 0

    t_start, added = time.time(), 0
    for pid in queue:
        if added >= wanted:
            break
        t0 = time.time()
        log.info("participant %s (%d of %d)", pid, added + 1, wanted)
        try:
            append(out, run_participant(pid, pool.loc[pid]))
        except PipelineError as exc:
            log.error("%s skipped: failed at %s: %s", pid, exc.stage, exc)
            continue
        except KeyboardInterrupt:
            log.warning("interrupted -- %d added this run, re-run to resume", added)
            raise
        added += 1
        log.info("%s done in %.0fs", pid, time.time() - t0)

    print(f"\nadded {added} participants in {(time.time() - t_start) / 60:.1f} min -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
