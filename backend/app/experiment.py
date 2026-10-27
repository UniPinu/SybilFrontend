"""The T0 + T1 -> T2 experiment, explained on one participant (the Experiment page).

Every number the page shows comes from app/trajectory.py, so the guide and
scripts/fit_trajectory.py can never disagree. Steps:

  scans     the three Sybil runs: dates and 6 risks each
  align     T0's and T1's points on T0's clock (T1 made unconditional)
  curve     the PCHIP curves and the blend between them, sampled densely
  forecast  T2's six numbers read off the curve, vs Sybil's T2 and "T2 = T1"
  network   the 13 inputs for this person, as the models see them
  dataset   how far data/trajectories.csv is, and cross-validated results once
            there are enough participants
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from app import participants as explore
from app.config import settings
from app.store import store
from app.trajectory import (YEARS, Trajectories, abs_errors, blend_weight, combined_curve,
                            cross_validate, curve_forecast, curve_parts, default_specs,
                            load_trajectories, logit, metrics, paired_difference)

MIN_PARTICIPANTS = 10  # 5-fold CV needs two people per fold
HIDDEN = 8


class NotReady(LookupError):
    """The participant exists but lacks a result for one of T0, T1, T2."""


def dataset_path() -> Path:
    return settings.data_dir / "trajectories.csv"


def _r(values, digits: int = 6) -> List[float]:
    return [round(float(v), digits) for v in np.asarray(values).ravel()]


def build_guide(nlst_pid: str, years: np.ndarray, risks: np.ndarray,
                outcome: Optional[dict] = None) -> Dict[str, Any]:
    """Everything except the dataset block, from one person's 3 dates and 3 x 6 risks."""
    years, risks = np.asarray(years, dtype=float), np.asarray(risks, dtype=float)
    d1, d2 = float(years[1] - years[0]), float(years[2] - years[0])
    k = np.arange(1, YEARS + 1)
    f0, f1, base = curve_parts(risks[0], risks[1], d1)
    horizon = float(np.ceil(d2 + YEARS + 1))
    curve = combined_curve(risks[0], risks[1], d1, horizon=horizon)

    t = np.round(np.arange(0.0, d2 + YEARS + 1e-9, 0.1), 2)
    forecast = curve_forecast(curve, d2)
    truth = risks[2]
    X = np.concatenate([logit(risks[0]), logit(risks[1]), [d1]])

    return {
        "nlst_pid": nlst_pid,
        "outcome": outcome,
        "scans": [{"round": f"T{i}", "years": round(float(years[i]), 3),
                   "risk_by_year": _r(risks[i])} for i in range(3)],
        "offset": round(d1, 3),
        "t2_offset": round(d2, 3),
        "align": {
            "base": round(base, 6),
            "t0": [{"t": float(x), "risk": round(float(v), 6)} for x, v in zip(k, risks[0])],
            "t1_shifted": [{"t": round(d1 + x, 3), "risk": round(float(v), 6)}
                           for x, v in zip(k, risks[1])],
            "t1_on_t0_clock": [{"t": round(d1 + x, 3), "risk": round(base + (1 - base) * float(v), 6)}
                               for x, v in zip(k, risks[1])],
        },
        "curve": [{
            "t": float(x),
            "combined": round(float(curve(x)), 6),
            "t0_only": round(float(f0(x)), 6) if x <= YEARS else None,
            "t1_only": round(float(f1(x)), 6) if x >= d1 else None,
            "weight": round(float(blend_weight(x, d1)), 4),
        } for x in t],
        "forecast": {
            "at": round(d2, 3),
            "curve_at_t2": round(float(curve(d2)), 6),
            "sybil_t2": _r(truth),
            "curve": _r(forecast),
            "persistence": _r(risks[1]),
            "curve_mae_pp": round(float(np.abs(forecast - truth).mean() * 100), 3),
            "persistence_mae_pp": round(float(np.abs(risks[1] - truth).mean() * 100), 3),
        },
        "network": {
            "inputs": [{"name": f"T{r} · {y} y", "value": round(float(risks[r][y - 1]), 6),
                        "x": round(float(X[r * YEARS + y - 1]), 4)}
                       for r in (0, 1) for y in k]
                      + [{"name": "Δ T0→T1", "value": round(d1, 3), "x": round(d1, 4)}],
            "hidden": HIDDEN,
            "outputs": [f"T2 · {y} y" for y in k],
        },
    }


@lru_cache(maxsize=4)
def _cross_validated(path: str, mtime: float) -> Dict[str, Any]:
    """CV once per version of the CSV; the mtime is only part of the cache key."""
    traj = load_trajectories(Path(path))
    specs = default_specs(HIDDEN)
    preds = cross_validate(traj, specs, folds=5, repeats=3)
    truth = traj.risks[:, 2]
    errors = {name: abs_errors(p, truth) for name, p in preds.items()}
    names = list(specs)
    return {
        "traj": traj,
        "preds": preds,
        "metrics": {name: metrics(p, truth) for name, p in preds.items()},
        "offset_effect": [
            {"with": a, "without": b, **paired_difference(errors[a], errors[b])}
            for a, b in zip(names[1::2], names[0::2])
        ],
    }


def dataset_block(nlst_pid: str) -> Dict[str, Any]:
    path = dataset_path()
    traj: Optional[Trajectories] = load_trajectories(path) if path.exists() else None
    n = len(traj) if traj is not None else 0
    out: Dict[str, Any] = {
        "file": f"backend/data/{path.name}",
        "n_participants": n,
        "min_needed": MIN_PARTICIPANTS,
        "includes_this_participant": bool(traj is not None and nlst_pid in traj.pids),
        "metrics": None,
        "offset_effect": None,
        "this_participant": None,
    }
    if n < MIN_PARTICIPANTS:
        return out
    cv = _cross_validated(str(path), path.stat().st_mtime)
    out["metrics"] = cv["metrics"]
    out["offset_effect"] = cv["offset_effect"]
    if nlst_pid in cv["traj"].pids:
        i = cv["traj"].pids.index(nlst_pid)
        out["this_participant"] = {name: _r(p[:, i].mean(0)) for name, p in cv["preds"].items()}
    return out


def guide(nlst_pid: str) -> Dict[str, Any]:
    row = explore._row(nlst_pid)  # raises UnknownParticipant
    by_round = {e["study_yr"]: e for e in explore.exams_for(nlst_pid)}
    risks, years = [], []
    for r in (0, 1, 2):
        exam = by_round.get(r)
        result = store.result(exam["patient_id"]) if exam else None
        when = row.get(f"t{r}_years")
        if not result:
            raise NotReady(f"Participant {nlst_pid} has no Sybil result for T{r} yet. "
                           "Run all three rounds in Explore first.")
        if when is None:
            raise NotReady(f"Participant {nlst_pid}'s T{r} scan has no date, so it can't be "
                           "placed on the timeline.")
        risks.append(result["risk_by_year"])
        years.append(when)
    if years[1] <= years[0]:
        raise NotReady(f"Participant {nlst_pid}'s T1 is not after T0.")
    outcome = {"diagnosed": bool(row.get("diagnosed")),
               "years_rand_to_dx": row.get("years_rand_to_dx"),
               "stage": explore._stage(row.get("stage_code"))}
    payload = build_guide(nlst_pid, np.array(years), np.array(risks), outcome)
    payload["dataset"] = dataset_block(nlst_pid)
    return payload
