"""Turn IDC's index + `nlst_prsn` into the three tables the app reads.

Pure pandas, no network: scripts/build_candidates.py does the querying and
hands the frames in, which keeps this testable on synthetic rows.

    exams.parquet         one row per (participant, round) that has a usable
                          axial series -- including rounds Sybil's evaluation
                          excludes, flagged `eligible=False` with the reason
    candidates.parquet    the eligible subset: what random picking and the pool
                          draw from (unchanged meaning)
    participants.parquet  one row per participant with at least one usable
                          scan: demographics, the trial timeline and the status
                          of each screening round, for search
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

import pandas as pd

from app.labels import DAYS_PER_YEAR, describe_person, nlst_label, to_num

ROUNDS = (0, 1, 2)

# Round statuses, in the order the UI explains them.
ELIGIBLE = "eligible"            # in Sybil's evaluation set; has an outcome label
EXCLUDED = "excluded"            # usable scan, but Sybil's own rules drop it
NO_USABLE_SERIES = "no_usable_series"  # imaged, but no 1-2.5 mm axial series fits
NO_IMAGES = "no_images"          # no CT for this round in IDC

RUNNABLE = (ELIGIBLE, EXCLUDED)


def _years(days: Optional[float]) -> Optional[float]:
    return None if days is None else round(days / DAYS_PER_YEAR, 2)


def exam_row(rec: dict, yr: int, regression: Iterable[str] = ()) -> dict:
    label = nlst_label(rec, yr)
    days_since_rand = to_num(rec[f"scr_days{yr}"])
    row = {
        "patient_id": f"{rec['PatientID']}_T{yr}",
        "nlst_pid": str(rec["PatientID"]),
        "study_yr": yr,
        "study_uid": rec["StudyInstanceUID"],
        "series_uid": rec["SeriesInstanceUID"],
        "series_description": rec["SeriesDescription"],
        "manufacturer": rec["Manufacturer"],
        "kernel": rec["kernel"],
        "n_instances": int(rec["instanceCount"]),
        "series_size_mb": float(rec["series_size_MB"]),
        "thickness_mm": float(rec["thickness_mm"]),
        "fov_mm": to_num(rec["fov_mm"]),
        "days_since_rand": days_since_rand,
        **describe_person(rec, yr),
        "stage_code": to_num(rec["de_stag"]),
        "lesion_size_mm": to_num(rec["lesionsize"]),
        "in_regression_set": rec["SeriesInstanceUID"] in regression,
        "eligible": label.valid,
        "exclusion_reason": None if label.valid else label.reason,
    }
    if label.valid:
        row.update(cancer_within_6y=label.cancer_within_6y,
                   years_to_cancer=label.years_to_cancer,
                   years_followed=label.years_followed)
    else:
        # No label in Sybil's sense, but the raw interval is still what a
        # longitudinal view needs: negative means the scan came after diagnosis.
        candx = to_num(rec["candx_days"])
        raw = (int((candx - days_since_rand) // DAYS_PER_YEAR)
               if candx is not None and days_since_rand is not None else None)
        row.update(cancer_within_6y=None, years_to_cancer=raw, years_followed=None)
    return row


def _round_status(yr: int, exam: Optional[dict], seen: set, screened: bool) -> Tuple[str, str]:
    if exam is not None:
        if exam["eligible"]:
            return ELIGIBLE, ""
        return EXCLUDED, exam["exclusion_reason"]
    if yr in seen:
        return NO_USABLE_SERIES, "no axial 1-2.5 mm series within the size limit"
    if not screened:
        return NO_IMAGES, "not screened in this round"
    return NO_IMAGES, "no CT for this round in Imaging Data Commons"


def participant_rows(exams: pd.DataFrame, rounds_seen: pd.DataFrame,
                     prsn: pd.DataFrame) -> pd.DataFrame:
    seen: Dict[str, set] = (
        rounds_seen.assign(PatientID=rounds_seen["PatientID"].astype(str))
        .groupby("PatientID")["study_yr"].apply(lambda s: {int(v) for v in s}).to_dict()
    )
    by_pid = {pid: g.to_dict("records") for pid, g in exams.groupby("nlst_pid")}
    prsn = prsn.assign(dicom_patient_id=prsn["dicom_patient_id"].astype(str))

    rows = []
    for rec in prsn.to_dict("records"):
        pid = rec["dicom_patient_id"]
        pid_exams = {e["study_yr"]: e for e in by_pid.get(pid, [])}
        if not pid_exams:
            continue  # nothing anyone could run
        person = describe_person(rec, 0)
        candx = to_num(rec["candx_days"])
        row = {
            "nlst_pid": pid,
            "age_at_randomization": person["age_at_randomization"],
            "sex": person["sex"],
            "smoking_status": person["smoking_status"],
            "race": person["race"],
            "diagnosed": candx is not None,
            "years_rand_to_dx": _years(candx),
            "years_rand_to_last_free": _years(to_num(rec["canc_free_days"])),
            "cancyr": to_num(rec["cancyr"]),
            "stage_code": to_num(rec["de_stag"]),
        }
        for yr in ROUNDS:
            days = to_num(rec[f"scr_days{yr}"])
            status, reason = _round_status(yr, pid_exams.get(yr), seen.get(pid, set()),
                                           screened=days is not None)
            row[f"t{yr}_status"] = status
            row[f"t{yr}_reason"] = reason
            row[f"t{yr}_years"] = _years(days)
        runnable = list(pid_exams.values())
        row.update(
            n_rounds=len(runnable),
            n_eligible=sum(1 for e in runnable if e["eligible"]),
            manufacturers="; ".join(sorted({e["manufacturer"] for e in runnable})),
            in_regression_set=any(e["in_regression_set"] for e in runnable),
            cancer_within_6y_any=any(bool(e["cancer_within_6y"]) for e in runnable
                                     if e["eligible"]),
        )
        rows.append(row)
    return pd.DataFrame(rows)


def assemble(series: pd.DataFrame, rounds_seen: pd.DataFrame, prsn: pd.DataFrame,
             regression: Iterable[str] = ()) -> Tuple[pd.DataFrame, pd.DataFrame,
                                                     pd.DataFrame, Dict[str, int]]:
    """-> (exams, candidates, participants, excluded-reason counts)."""
    regression = set(regression)
    prsn = prsn.drop_duplicates("dicom_patient_id")
    df = series.merge(prsn, left_on="PatientID", right_on="dicom_patient_id", how="inner")

    rows = [exam_row(rec, int(rec["study_yr"]), regression) for rec in df.to_dict("records")]
    exams = pd.DataFrame(rows)
    dupes = exams["patient_id"][exams["patient_id"].duplicated()].tolist()
    if dupes:
        raise ValueError(f"more than one series per participant and round: {dupes[:5]}")

    excluded: Dict[str, int] = (
        exams.loc[~exams["eligible"], "exclusion_reason"].value_counts().to_dict()
    )
    candidates = exams[exams["eligible"]].copy()
    candidates["cancer_within_6y"] = candidates["cancer_within_6y"].astype(bool)
    candidates["years_followed"] = candidates["years_followed"].astype(int)
    participants = participant_rows(exams, rounds_seen, prsn)
    return exams, candidates.reset_index(drop=True), participants, excluded
