"""Does T0 + T1 (+ the time between them) predict Sybil's T2 better than T1 alone?

  uv run python scripts/fit_trajectory.py
  uv run python scripts/fit_trajectory.py --show 121825      # one participant's curve
  uv run python scripts/fit_trajectory.py --synthetic 200    # dry run without Sybil

Reads data/trajectories.csv (scripts/build_trajectories.py). Every learned
model is scored on participants it never saw (repeated k-fold), against two
baselines that learn nothing:

  T2 = T1          Sybil's T1 numbers, unchanged
  T0+T1 curve      the interpolated curve, read off at T2's real date

Errors are mean absolute differences from Sybil's real T2 numbers, in
percentage points of risk. The last block answers the question directly:
the same model with and without the 13th (offset) input.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from app.config import settings
from app.trajectory import (YEARS, Trajectories, abs_errors, combined_curve, cross_validate,
                            curve_baseline, curve_forecast, default_specs, load_trajectories,
                            metrics, paired_difference, persistence)


def synthetic(n: int, seed: int = 0) -> Trajectories:
    """Constant-hazard people with jittered scan dates and Sybil-like noise.

    Each person's hazard drifts a little each year, so T1 alone is not the whole
    story. Only for checking the pipeline end to end.
    """
    rng = np.random.default_rng(seed)
    hazard = np.exp(rng.normal(np.log(0.01), 0.8, n))
    drift = np.exp(rng.normal(0.1, 0.15, n))
    years = np.column_stack([rng.uniform(0, 0.1, n),
                             rng.normal(1.05, 0.13, n),
                             rng.normal(2.07, 0.16, n)])
    years[:, 1] = np.maximum(years[:, 1], years[:, 0] + 0.3)
    years[:, 2] = np.maximum(years[:, 2], years[:, 1] + 0.3)
    k = np.arange(1, YEARS + 1)
    risks = np.empty((n, 3, YEARS))
    for r in range(3):
        h = hazard * drift ** years[:, r] * np.exp(rng.normal(0, 0.2, n))  # scan-to-scan noise
        risks[:, r] = np.clip(1 - np.exp(-h[:, None] * k[None]), 1e-3, 0.99)
    return Trajectories([f"syn{i}" for i in range(n)], years, risks)


def show(traj: Trajectories, pid: str) -> None:
    i = traj.pids.index(pid)
    r, d1, d2 = traj.risks[i], traj.offsets[i], traj.t2_offsets[i]
    curve = combined_curve(r[0], r[1], d1)
    print(f"\n{pid}: T1 at +{d1:.2f} y, T2 at +{d2:.2f} y after T0")
    print("  years after T0   " + " ".join(f"{t:5.1f}" for t in np.arange(0, 9.5, 0.5)))
    print("  curve risk %     " + " ".join(f"{v * 100:5.1f}" for v in curve(np.arange(0, 9.5, 0.5))))
    print("  T2, Sybil %      " + " ".join(f"{v * 100:5.1f}" for v in r[2]))
    print("  T2, curve %      " + " ".join(f"{v * 100:5.1f}" for v in curve_forecast(curve, d2)))
    print("  T2 = T1 %        " + " ".join(f"{v * 100:5.1f}" for v in r[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(settings.data_dir / "trajectories.csv"))
    ap.add_argument("--synthetic", type=int, default=0, metavar="N",
                    help="use N synthetic participants instead of --data")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--hidden", type=int, default=8, help="MLP hidden neurons")
    ap.add_argument("--epochs", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--show", default=None, metavar="NLST_PID", help="print one participant's curve")
    args = ap.parse_args()

    if args.synthetic:
        traj = synthetic(args.synthetic, args.seed)
    else:
        path = Path(args.data)
        if not path.exists():
            print(f"{path} not found -- run scripts/build_trajectories.py first "
                  "(or try --synthetic 200)")
            return 1
        traj = load_trajectories(path)

    print(f"{len(traj)} participants; T0->T1 offset {traj.offsets.mean():.2f} "
          f"+/- {traj.offsets.std():.2f} y (min {traj.offsets.min():.2f}, "
          f"max {traj.offsets.max():.2f})")
    if args.show:
        show(traj, args.show)

    truth = traj.risks[:, 2]
    preds = {"T2 = T1 (no model)": persistence(traj),
             "T0+T1 curve (no model)": curve_baseline(traj)}
    specs = default_specs(args.hidden, args.epochs)
    try:
        preds.update(cross_validate(traj, specs, folds=args.folds, repeats=args.repeats,
                                    seed=args.seed))
    except ValueError as exc:
        print(f"\nskipping the learned models: {exc}")
        specs = {}

    print(f"\nerror against Sybil's real T2, percentage points "
          f"({args.folds}-fold CV x {args.repeats} for learned models)")
    print(f"  {'model':<28} {'MAE':>6} {'RMSE':>6} {'6y MAE':>7}   MAE by year 1..6")
    for name, p in preds.items():
        m = metrics(p, truth)
        by_year = " ".join(f"{v:5.2f}" for v in m["mae_by_year_pp"])
        print(f"  {name:<28} {m['mae_pp']:6.2f} {m['rmse_pp']:6.2f} {m['mae_6y_pp']:7.2f}   {by_year}")

    errors = {name: abs_errors(p, truth) for name, p in preds.items()}
    learned = list(specs)  # default_specs lists each model without, then with, the offset
    pairs = list(zip(learned[1::2], learned[0::2]))
    pairs += [(name, "T2 = T1 (no model)") for name in list(preds)[1:]]
    print("\npaired differences, MAE(a) - MAE(b) per participant, 95% bootstrap CI "
          "(negative = a is better)")
    for a, b in pairs:
        d = paired_difference(errors[a], errors[b], seed=args.seed)
        verdict = ("a better" if d["hi"] < 0 else "b better" if d["lo"] > 0
                   else "no clear difference")
        print(f"  {a:<28} vs {b:<28} {d['mean']:+6.3f} [{d['lo']:+.3f}, {d['hi']:+.3f}]"
              f"  a better for {d['a_better']}/{d['n']}  -> {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
