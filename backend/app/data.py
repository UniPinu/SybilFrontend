"""Candidates, person cards, outcomes and the cohort view.

Everything here reads `data/candidates.parquet` (built by
scripts/build_candidates.py) plus whatever the cache already holds. No network.
"""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from app.config import settings
from app.labels import STAGE
from app.store import store

log = logging.getLogger(__name__)

_cache: Dict[str, object] = {}

# Band thresholds against the reference sample's 6-year risk percentiles.
BANDS = ("Lower than typical", "Typical", "Higher than typical", "Much higher than typical")


def candidates() -> pd.DataFrame:
    """The candidate table, reloaded if the parquet changed on disk."""
    path = settings.candidates_path
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: uv run python scripts/build_candidates.py"
        )
    stamp = path.stat().st_mtime
    if _cache.get("stamp") != stamp:
        df = pd.read_parquet(path)
        df = df.set_index("patient_id", drop=False)
        _cache["stamp"] = stamp
        _cache["df"] = df
        log.info("loaded %d candidates from %s", len(df), path)
    return _cache["df"]  # type: ignore[return-value]


def have_candidates() -> bool:
    return settings.candidates_path.exists()


def get_candidate(patient_id: str) -> Optional[dict]:
    df = candidates()
    if patient_id not in df.index:
        return None
    row = df.loc[patient_id]
    if isinstance(row, pd.DataFrame):  # duplicate index, should not happen
        row = row.iloc[0]
    return _clean(row.to_dict())


def _clean(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.floating,)):
            out[k] = None if np.isnan(v) else float(v)
        elif isinstance(v, (np.bool_,)):
            out[k] = bool(v)
        elif v is pd.NaT or (isinstance(v, float) and np.isnan(v)):
            out[k] = None
        else:
            out[k] = v
    return out


# Fields that answer "what happened to this person". They belong in outcome.json
# and nowhere else, so that nothing the client can fetch before the prediction
# carries the answer.
OUTCOME_FIELDS = (
    "cancer_within_6y",
    "years_to_cancer",
    "years_followed",
    "stage_code",
    "lesion_size_mm",
)


def without_outcome(candidate: dict) -> dict:
    return {k: v for k, v in candidate.items() if k not in OUTCOME_FIELDS}


def display_id(nlst_pid: str) -> str:
    """De-identified NLST ids are already pseudonyms; truncate anyway."""
    pid = str(nlst_pid)
    return f"Participant #{pid[:4]}…"


# Upstream's example scan (MVP.md 5.7): the offline fallback person. It has no
# trial record, so there is nothing to reveal.
DEMO_CANDIDATE = {
    "patient_id": "demo_offline",
    "nlst_pid": "demo",
    "display_id": "The example scan",
    "round_label": "the example scan published with the Sybil code",
    "study_yr": None,
    "series_uid": None,
    "series_size_mb": 0.0,
    "thickness_mm": None,
    "n_instances": None,
    "manufacturer": None,
    "kernel": None,
    "in_regression_set": False,
    "cancer_within_6y": False,
    "years_to_cancer": None,
    "years_followed": None,
    "age_at_scan": None,
    "age_at_randomization": None,
    "sex": None,
    "smoking_status": None,
    "race": None,
    "screening_round": None,
}


def membership(patient_id: str) -> str:
    sets = store.pool_sets()
    if patient_id in sets.pool:
        return "pool"
    if patient_id in sets.reference:
        return "reference"
    return "live"


def person_card(candidate: dict, *, ready: Optional[bool] = None) -> dict:
    """What the visitor may see *before* Sybil runs. Never the outcome."""
    pid = candidate["patient_id"]
    meta = store.meta(pid) or {}
    series = meta.get("series", {})
    return {
        "patient_id": pid,
        "display_id": candidate.get("display_id") or display_id(candidate["nlst_pid"]),
        "age": candidate.get("age_at_scan") or candidate.get("age_at_randomization"),
        "age_at_randomization": candidate.get("age_at_randomization"),
        "sex": candidate.get("sex"),
        "smoking_status": candidate.get("smoking_status"),
        "race": candidate.get("race"),
        "screening_round": candidate.get("screening_round"),
        "round_label": candidate.get("round_label") or _round_label(candidate.get("study_yr")),
        "manufacturer": series.get("manufacturer") or candidate.get("manufacturer"),
        "scanner_model": series.get("model"),
        "n_slices": series.get("n_files") or candidate.get("n_instances"),
        "thickness_mm": series.get("thickness_mm") or candidate.get("thickness_mm"),
        "series_size_mb": round(float(candidate.get("series_size_mb") or 0), 1),
        "kernel": candidate.get("kernel"),
        "in_regression_set": bool(candidate.get("in_regression_set")),
        "set": membership(pid),
        "ready": store.is_ready(pid) if ready is None else ready,
    }


def _round_label(study_yr) -> str:
    try:
        yr = int(study_yr)
    except (TypeError, ValueError):
        return "a screening scan"
    return {
        0: "first screening scan (T0)",
        1: "second screening scan, one year later (T1)",
        2: "third screening scan, two years later (T2)",
    }.get(yr, f"screening round T{yr}")


def outcome_payload(candidate: dict) -> dict:
    """The reveal. Kept out of every other endpoint on purpose."""
    stage = candidate.get("stage_code")
    years = candidate.get("years_to_cancer")
    years = int(years) if years is not None else None
    followed = candidate.get("years_followed")
    return {
        "patient_id": candidate["patient_id"],
        "cancer_within_6y": bool(candidate["cancer_within_6y"]),
        # 0 means "diagnosed during the first year after this scan"
        "years_to_cancer": years,
        "diagnosis_year": years + 1 if years is not None else None,
        "years_followed": int(followed) if followed is not None else None,
        "stage": STAGE.get(int(stage)) if stage is not None else None,
        # `lesionsize` is in the IDC table but its units are not documented there,
        # so we keep it out of the reveal rather than print a number we cannot vouch for.
        "source": "NLST participant data via NCI Imaging Data Commons",
    }


# ---------------------------------------------------------------------------
# picking people
# ---------------------------------------------------------------------------
def pick_curated(exclude: Sequence[str] = (), rng: Optional[random.Random] = None) -> Optional[str]:
    rng = rng or random
    ids = [p for p in store.pool_sets().pool if store.is_ready(p) and p not in exclude]
    if not ids:
        # fall back to anything prepared, so a half-built pool still demos
        ids = [p for p in store.list_ready() if p not in exclude]
    return rng.choice(ids) if ids else None


def pick_live(exclude: Sequence[str] = (), rng: Optional[random.Random] = None) -> Optional[str]:
    """A brand-new random candidate nobody has run yet."""
    rng = rng or random
    df = candidates()
    taken = set(store.list_ready()) | set(exclude)
    for _ in range(200):
        pid = str(df.iloc[rng.randrange(len(df))]["patient_id"])
        if pid not in taken:
            return pid
    pool = [p for p in df["patient_id"].tolist() if p not in taken]
    return rng.choice(pool) if pool else None


# ---------------------------------------------------------------------------
# reference sample and cohort
# ---------------------------------------------------------------------------
def reference_curve() -> Optional[dict]:
    """"A typical screening participant", from the unbalanced reference sample."""
    ids = [p for p in store.pool_sets().reference if store.is_ready(p)]
    curves = []
    for pid in ids:
        result = store.result(pid)
        if result and result.get("risk_by_year"):
            curves.append(result["risk_by_year"])
    if not curves:
        return None
    arr = np.array(curves, dtype=float)
    return {
        "n": len(curves),
        "median": [round(float(v), 6) for v in np.median(arr, axis=0)],
        "p25": [round(float(v), 6) for v in np.percentile(arr, 25, axis=0)],
        "p75": [round(float(v), 6) for v in np.percentile(arr, 75, axis=0)],
        "p95": [round(float(v), 6) for v in np.percentile(arr, 95, axis=0)],
        "note": "Median of a small, unbalanced random sample of NLST screening scans.",
    }


def risk_band(risk_6y: float, reference: Optional[dict]) -> dict:
    """Where this person sits against the reference sample. Never a diagnosis."""
    if not reference:
        return {"band": None, "comparison": None,
                "note": "No reference sample prepared yet."}
    p25, p75, p95 = reference["p25"][-1], reference["p75"][-1], reference["p95"][-1]
    median = reference["median"][-1]
    if risk_6y < p25:
        band = BANDS[0]
    elif risk_6y <= p75:
        band = BANDS[1]
    elif risk_6y <= p95:
        band = BANDS[2]
    else:
        band = BANDS[3]
    ratio = round(risk_6y / median, 1) if median > 0 else None
    return {
        "band": band,
        "reference_median_6y": median,
        "times_typical": ratio,
        "note": "Compared with a small reference sample of screening participants, "
                "not with the general population.",
    }


def cohort() -> List[dict]:
    """Every prepared patient: 6-year risk next to what actually happened."""
    out = []
    sets = store.pool_sets()
    for pid in store.list_ready():
        result = store.result(pid)
        if not result:
            continue
        cand = get_candidate(pid)
        outcome = store.outcome(pid) or {}
        out.append(
            {
                "patient_id": pid,
                "display_id": display_id(cand["nlst_pid"]) if cand else pid,
                "risk_6y": result["risk_by_year"][-1],
                "risk_1y": result["risk_by_year"][0],
                "cancer_within_6y": outcome.get("cancer_within_6y"),
                "years_to_cancer": outcome.get("years_to_cancer"),
                "years_followed": outcome.get("years_followed"),
                "set": "pool" if pid in sets.pool else
                       ("reference" if pid in sets.reference else "live"),
                "in_regression_set": bool(cand.get("in_regression_set")) if cand else False,
                "age": cand.get("age_at_scan") if cand else None,
                "sex": cand.get("sex") if cand else None,
                "screening_round": cand.get("screening_round") if cand else None,
            }
        )
    return sorted(out, key=lambda r: r["risk_6y"])


def candidate_stats() -> dict:
    if not have_candidates():
        return {"available": False}
    df = candidates()
    return {
        "available": True,
        "exams": int(len(df)),
        "participants": int(df["nlst_pid"].nunique()),
        "cancer_within_6y": int(df["cancer_within_6y"].sum()),
        "median_series_mb": round(float(df["series_size_mb"].median()), 1),
        "in_regression_set": int(df["in_regression_set"].sum()),
    }
