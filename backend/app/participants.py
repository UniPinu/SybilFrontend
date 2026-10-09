"""Explore: search participants, run several of their rounds, compare over time.

Reads `participants.parquet` and `exams.parquet` (scripts/build_candidates.py)
plus the patient cache. An "exam" here is what the rest of the app calls a
patient: `{nlst_pid}_T{round}`, one screening scan, cached on its own.

Unlike the story page, Explore shows outcomes by default -- with ~4% of
participants ever diagnosed, finding interesting people needs them. `blind=True`
drops every outcome field, so the reveal-after-prediction flow still works. All
outcome data sits under an `outcome` key at each level to keep that easy to get
right.
"""
from __future__ import annotations

import io
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from app import data
from app.catalog import EXCLUDED, ROUNDS, RUNNABLE
from app.config import settings
from app.jobs import jobs
from app.labels import STAGE
from app.store import store

BLIND_REASON = "outside Sybil's evaluation rules"

SORTS = {
    "id": ("nlst_pid", True),
    "age": ("age_at_randomization", True),
    "rounds": ("n_rounds", False),
    "results": ("results_ready", False),
    # outcome-based, so not available when blind
    "dx": ("years_rand_to_dx", True),
}


class UnknownParticipant(KeyError):
    pass


class BadRequest(ValueError):
    pass


def have_participants() -> bool:
    return settings.participants_path.exists() and settings.exams_path.exists()


def table() -> pd.DataFrame:
    return data.load_table(settings.participants_path, "nlst_pid")


def exams_for(nlst_pid: str) -> List[dict]:
    df = data.exams()
    if df is None:
        return []
    rows = df[df["nlst_pid"] == nlst_pid].sort_values("study_yr")
    return [data._clean(r) for r in rows.to_dict("records")]


def _row(nlst_pid: str) -> dict:
    df = table()
    if nlst_pid not in df.index:
        raise UnknownParticipant(nlst_pid)
    return data._clean(df.loc[nlst_pid].to_dict())


def ready_counts() -> Counter:
    """How many rounds of each participant already have a result."""
    counts: Counter = Counter()
    for exam_id in store.list_ready():
        pid, sep, _ = exam_id.rpartition("_T")
        if sep:
            counts[pid] += 1
    return counts


def _stage(code: Optional[float]) -> Optional[str]:
    return STAGE.get(int(code)) if code is not None else None


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
@dataclass
class Filters:
    q: Optional[str] = None
    sex: Optional[str] = None
    smoking: Optional[str] = None
    race: Optional[str] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    rounds_min: Optional[int] = None
    manufacturer: Optional[str] = None
    diagnosed: Optional[bool] = None
    has_results: Optional[bool] = None


def _summary(row: dict, results_ready: int, blind: bool) -> dict:
    item = {
        "nlst_pid": row["nlst_pid"],
        "display_id": f"Participant {row['nlst_pid']}",
        "age_at_randomization": row.get("age_at_randomization"),
        "sex": row.get("sex"),
        "smoking_status": row.get("smoking_status"),
        "race": row.get("race"),
        "rounds": [{"round": f"T{yr}", "status": row[f"t{yr}_status"]} for yr in ROUNDS],
        "n_rounds": int(row["n_rounds"]),
        "n_eligible": int(row["n_eligible"]),
        "manufacturers": [m for m in (row.get("manufacturers") or "").split("; ") if m],
        "in_regression_set": bool(row.get("in_regression_set")),
        "results_ready": results_ready,
        "outcome": None,
    }
    if not blind:
        item["outcome"] = {
            "diagnosed": bool(row["diagnosed"]),
            "years_rand_to_dx": row.get("years_rand_to_dx"),
            "stage": _stage(row.get("stage_code")),
            "cancer_within_6y_any": bool(row.get("cancer_within_6y_any")),
        }
    return item


def facets(blind: bool) -> Dict[str, Any]:
    df = table()
    makes = Counter(m for value in df["manufacturers"] for m in value.split("; ") if m)
    out: Dict[str, Any] = {
        "sex": df["sex"].value_counts().to_dict(),
        "smoking": df["smoking_status"].value_counts().to_dict(),
        "race": df["race"].value_counts().to_dict(),
        "manufacturer": dict(makes.most_common()),
        "rounds": {str(k): int(v) for k, v in df["n_rounds"].value_counts().sort_index().items()},
        "age": [int(df["age_at_randomization"].min()), int(df["age_at_randomization"].max())],
        "with_results": len(ready_counts()),
    }
    if not blind:
        out["diagnosed"] = int(df["diagnosed"].sum())
    return out


def search(filters: Filters, *, sort: str = "id", page: int = 1, page_size: int = 25,
           blind: bool = False) -> dict:
    df = table()
    ready = ready_counts()
    if blind and (filters.diagnosed is not None or sort.lstrip("-") == "dx"):
        raise BadRequest("Outcome filters and sorting are not available in blind mode.")
    key = sort.lstrip("-")
    if key not in SORTS:
        raise BadRequest(f"Unknown sort {sort!r}; use one of {sorted(SORTS)}")

    mask = pd.Series(True, index=df.index)
    if filters.q:
        mask &= df["nlst_pid"].str.startswith(filters.q.strip())
    if filters.sex:
        mask &= df["sex"] == filters.sex
    if filters.smoking:
        mask &= df["smoking_status"] == filters.smoking
    if filters.race:
        mask &= df["race"] == filters.race
    if filters.age_min is not None:
        mask &= df["age_at_randomization"] >= filters.age_min
    if filters.age_max is not None:
        mask &= df["age_at_randomization"] <= filters.age_max
    if filters.rounds_min is not None:
        mask &= df["n_rounds"] >= filters.rounds_min
    if filters.manufacturer:
        mask &= df["manufacturers"].str.split("; ").apply(lambda ms: filters.manufacturer in ms)
    if filters.diagnosed is not None:
        mask &= df["diagnosed"] == filters.diagnosed
    if filters.has_results is not None:
        has = df["nlst_pid"].isin(list(ready))
        mask &= has if filters.has_results else ~has

    hits = df[mask].reset_index(drop=True)
    hits["results_ready"] = hits["nlst_pid"].map(lambda p: ready.get(p, 0))
    column, ascending = SORTS[key]
    if sort.startswith("-"):
        ascending = not ascending
    hits = hits.sort_values([column, "nlst_pid"], ascending=[ascending, True],
                            na_position="last")

    page_size = max(1, min(page_size, 100))
    page = max(1, page)
    window = hits.iloc[(page - 1) * page_size: page * page_size]
    return {
        "total": int(len(hits)),
        "page": page,
        "page_size": page_size,
        "blind": blind,
        "items": [_summary(data._clean(r), int(r["results_ready"]), blind)
                  for r in window.to_dict("records")],
        "facets": facets(blind),
    }


# ---------------------------------------------------------------------------
# one participant
# ---------------------------------------------------------------------------
def _job_info(exam_id: str) -> Optional[dict]:
    job = jobs.job_for_patient(exam_id)
    if job is None:
        return None
    stats = jobs.stats()
    position = None
    if job.id in stats["queued"]:
        position = stats["queued"].index(job.id) + (1 if stats["running"] else 0)
    return {"job_id": job.id, "state": job.state, "position": position}


def _timeline(row: dict, blind: bool) -> dict:
    return {
        "rounds": [{"round": f"T{yr}", "years": row.get(f"t{yr}_years")} for yr in ROUNDS],
        "diagnosis_years": None if blind else row.get("years_rand_to_dx"),
        "last_cancer_free_years": None if blind else row.get("years_rand_to_last_free"),
    }


def _participant_outcome(row: dict) -> dict:
    return {
        "diagnosed": bool(row["diagnosed"]),
        "years_rand_to_dx": row.get("years_rand_to_dx"),
        "years_rand_to_last_free": row.get("years_rand_to_last_free"),
        "stage": _stage(row.get("stage_code")),
        "source": "NLST participant data via NCI Imaging Data Commons",
    }


def _exam_outcome(exam: dict) -> dict:
    return {
        "cancer_within_6y": exam.get("cancer_within_6y") if exam.get("eligible") else None,
        "years_to_cancer": exam.get("years_to_cancer"),
        "years_followed": (int(exam["years_followed"])
                           if exam.get("years_followed") is not None else None),
    }


def detail(nlst_pid: str, *, blind: bool = False) -> dict:
    row = _row(nlst_pid)
    by_round = {e["study_yr"]: e for e in exams_for(nlst_pid)}
    rounds = []
    for yr in ROUNDS:
        status, reason = row[f"t{yr}_status"], row[f"t{yr}_reason"] or None
        exam = by_round.get(yr)
        entry: Dict[str, Any] = {
            "round": f"T{yr}",
            "study_yr": yr,
            "status": status,
            "reason": BLIND_REASON if blind and status == EXCLUDED else reason,
            "runnable": status in RUNNABLE,
            "years_since_rand": row.get(f"t{yr}_years"),
            "exam_id": None, "age_at_scan": None, "series": None,
            "ready": False, "job": None, "outcome": None,
        }
        if exam is not None:
            exam_id = exam["patient_id"]
            meta = store.meta(exam_id) or {}
            ran_on = meta.get("candidate") or {}
            entry.update(
                exam_id=exam_id,
                age_at_scan=exam.get("age_at_scan"),
                series={
                    "manufacturer": exam.get("manufacturer"),
                    "kernel": ran_on.get("kernel") or exam.get("kernel"),
                    "thickness_mm": exam.get("thickness_mm"),
                    "n_instances": exam.get("n_instances"),
                    "series_size_mb": round(float(exam.get("series_size_mb") or 0), 1),
                    "in_regression_set": bool(exam.get("in_regression_set")),
                },
                ready=store.is_ready(exam_id),
                job=_job_info(exam_id),
                outcome=None if blind else _exam_outcome(exam),
            )
        rounds.append(entry)

    out = _summary(row, sum(r["ready"] for r in rounds), blind)
    out.update(
        blind=blind,
        timeline=_timeline(row, blind),
        rounds=rounds,
        outcome=None if blind else _participant_outcome(row),
    )
    return out


def run(nlst_pid: str, exam_ids: Optional[Sequence[str]] = None) -> List[dict]:
    """Queue rounds in chronological order; anything already cached is ready."""
    _row(nlst_pid)
    runnable = {e["patient_id"]: e for e in exams_for(nlst_pid)}
    wanted = list(runnable) if exam_ids is None else list(dict.fromkeys(exam_ids))
    if not wanted:
        raise BadRequest("Pick at least one round to run.")
    unknown = [x for x in wanted if x not in runnable]
    if unknown:
        raise BadRequest(f"Not a runnable round of participant {nlst_pid}: {unknown}")

    out = []
    for exam_id in sorted(wanted, key=lambda x: runnable[x]["study_yr"]):
        round_label = f"T{runnable[exam_id]['study_yr']}"
        if store.is_ready(exam_id):
            store.touch(exam_id)
            out.append({"exam_id": exam_id, "round": round_label, "job_id": None,
                        "ready": True, "state": "done"})
        else:
            job = jobs.submit(exam_id)
            out.append({"exam_id": exam_id, "round": round_label, "job_id": job.id,
                        "ready": False, "state": job.state})
    return out


def results(nlst_pid: str, *, blind: bool = False) -> dict:
    """Every finished round on one time axis, with the change since the last one."""
    row = _row(nlst_pid)
    reference = data.reference_curve()
    entries = []
    previous: Optional[dict] = None
    for exam in exams_for(nlst_pid):
        exam_id = exam["patient_id"]
        result = store.result(exam_id)
        if not result:
            continue
        risks = result["risk_by_year"]
        meta = store.meta(exam_id) or {}
        entry = {
            "exam_id": exam_id,
            "round": f"T{exam['study_yr']}",
            "study_yr": exam["study_yr"],
            "eligible": bool(exam.get("eligible", True)),
            "years_since_rand": row.get(f"t{exam['study_yr']}_years"),
            "age_at_scan": exam.get("age_at_scan"),
            "manufacturer": exam.get("manufacturer"),
            "kernel": (meta.get("candidate") or {}).get("kernel") or exam.get("kernel"),
            "risk_by_year": risks,
            "risk_pct_by_year": [round(r * 100, 1) for r in risks],
            "band": data.risk_band(risks[-1], reference).get("band"),
            "hotspot_slice": result.get("hotspot_slice"),
            "n_slices": result.get("n_slices"),
            "slice_importance": result.get("slice_importance") or [],
            "created_at": result.get("created_at"),
            "sybil_commit": (result.get("model") or {}).get("sybil_commit"),
            "change_from_previous": None,
            "outcome": None if blind else _exam_outcome(exam),
        }
        if previous is not None:
            entry["change_from_previous"] = {
                "from_round": previous["round"],
                "risk_by_year": [round(a - b, 6)
                                 for a, b in zip(risks, previous["risk_by_year"])],
            }
        entries.append(entry)
        previous = entry
    return {
        "nlst_pid": nlst_pid,
        "blind": blind,
        "timeline": _timeline(row, blind),
        "exams": entries,
        "reference": reference,
        "outcome": None if blind else _participant_outcome(row),
    }


def export_csv(nlst_pid: str, *, blind: bool = False) -> str:
    payload = results(nlst_pid, blind=blind)
    person = payload["outcome"] or {}
    rows = []
    for e in payload["exams"]:
        row = {
            "nlst_pid": nlst_pid,
            "exam_id": e["exam_id"],
            "round": e["round"],
            "eligible": e["eligible"],
            "years_since_randomization": e["years_since_rand"],
            "age_at_scan": e["age_at_scan"],
            "manufacturer": e["manufacturer"],
            "kernel": e["kernel"],
            **{f"risk_{i + 1}y": r for i, r in enumerate(e["risk_by_year"])},
            "band": e["band"],
            "hotspot_slice": e["hotspot_slice"],
            "created_at": e["created_at"],
            "sybil_commit": e["sybil_commit"],
        }
        if not blind:
            row.update(
                cancer_within_6y=e["outcome"]["cancer_within_6y"],
                years_to_cancer=e["outcome"]["years_to_cancer"],
                years_followed=e["outcome"]["years_followed"],
                participant_diagnosed=person.get("diagnosed"),
                years_randomization_to_diagnosis=person.get("years_rand_to_dx"),
                stage=person.get("stage"),
            )
        rows.append(row)
    buffer = io.StringIO()
    pd.DataFrame(rows).to_csv(buffer, index=False)
    return buffer.getvalue()
