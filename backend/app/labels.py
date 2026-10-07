"""NLST outcome labels, ported from Sybil's own dataset code.

Why port it: "what happened" in the UI should mean the same thing it meant when
Sybil was evaluated, so the reveal and the published metrics line up.
Upstream reference: `sybil/datasets/nlst.py::NLST_Survival_Dataset.{check_label,get_label}`
at main@d9fc81b.

Two documented deviations, forced by what IDC actually publishes (MVP.md §5.1
says to print the columns and adapt). IDC's `nlst_prsn` is a *subset* of the
CDAS participant table:

  * `fup_days` does not exist. We use `canc_free_days` -- "days from
    randomization to the date the participant was last known to be free of lung
    cancer". For the question this app asks ("was this person diagnosed in the
    next six years?") that is the more direct denominator anyway.
  * `lung_cancer` does not exist. A non-empty `candx_days` *is* the confirmed
    diagnosis flag, which is exactly the test Sybil's own code applies
    (`candx_days > -1`). `canc_rpt_link` covers only 969 of the 2058 diagnosed
    participants, so it is not usable as the flag.

Missing values in IDC's tables are empty strings, not NaN and not -1.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

MAX_FOLLOWUP = 6
DAYS_PER_YEAR = 365

# --- code books (CDAS NLST data dictionary) ------------------------------
GENDER = {1: "Male", 2: "Female"}
CIGSMOK = {0: "Former smoker", 1: "Current smoker"}
RACE = {
    1: "White",
    2: "Black or African-American",
    3: "Asian",
    4: "American Indian or Alaskan Native",
    5: "Native Hawaiian or Other Pacific Islander",
    6: "More than one race",
    7: "Participant refused to answer",
    95: "Missing",
    96: "Missing",
    98: "Unknown/decline to answer",
    99: "Unknown/decline to answer",
}
# de_stag: AJCC 6th edition stage group
STAGE = {
    110: "stage IA",
    120: "stage IB",
    210: "stage IIA",
    220: "stage IIB",
    310: "stage IIIA",
    320: "stage IIIB",
    400: "stage IV",
    888: "stage not applicable",
    900: "carcinoid/other",
    994: "TNM not available",
    999: "stage unknown",
}


def to_num(value: Any) -> Optional[float]:
    """IDC codes missing values as "" (and sometimes as negative sentinels)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in {"", ".", ".N", ".M", "NA", "nan"}:
            return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


@dataclass(frozen=True)
class NlstLabel:
    cancer_within_6y: bool
    years_to_cancer: Optional[int]  # 0 == diagnosed inside the first year
    years_followed: int  # years of cancer-free follow-up after this scan, 1..6
    valid: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def nlst_label(row: Any, screen_yr: int, max_followup: int = MAX_FOLLOWUP) -> NlstLabel:
    """Label one *screening exam* (a participant has up to three).

    `row` is anything indexable by column name: a dict or a pandas Series.
    Returns `valid=False` for exams Sybil's `skip_sample` would have dropped, so
    callers can filter candidates the same way the model's evaluation did.
    """
    days_since_rand = to_num(row[f"scr_days{screen_yr}"])
    days_to_cancer_since_rand = to_num(row["candx_days"])
    days_to_last_cancer_free = to_num(row["canc_free_days"])
    cancer_timepoint = to_num(row["cancyr"])

    # check_label(): the screen must have happened, and we need at least one of
    # the two time anchors.
    if days_since_rand is None:
        return NlstLabel(False, None, 0, False, f"no scr_days{screen_yr}")
    if days_to_cancer_since_rand is None and days_to_last_cancer_free is None:
        return NlstLabel(False, None, 0, False, "no outcome timing")

    if days_to_cancer_since_rand is not None:
        days_to_cancer = days_to_cancer_since_rand - days_since_rand
        years_to_cancer = int(days_to_cancer // DAYS_PER_YEAR)
    else:
        years_to_cancer = 100

    cancer_within_6y = years_to_cancer < max_followup

    if cancer_within_6y:
        # Upstream asserts screen_timepoint <= cancyr, and skip_sample drops
        # exams whose time-at-event is negative -- i.e. scans taken *after* the
        # diagnosis. Those cannot be "predicted", so they are not candidates.
        if years_to_cancer < 0:
            return NlstLabel(False, None, 0, False, "diagnosed before this scan")
        if cancer_timepoint is not None and screen_yr > cancer_timepoint:
            return NlstLabel(False, None, 0, False, "scan after diagnosis year")
        years_followed = years_to_cancer + 1
        return NlstLabel(True, years_to_cancer, min(years_followed, max_followup), True)

    if days_to_last_cancer_free is None:
        return NlstLabel(False, None, 0, False, "no cancer-free follow-up")
    years_to_last_followup = int(days_to_last_cancer_free - days_since_rand) // DAYS_PER_YEAR
    if years_to_last_followup < 0:
        return NlstLabel(False, None, 0, False, "follow-up ends before this scan")
    time_at_event = min(years_to_last_followup, max_followup - 1)
    return NlstLabel(False, None, time_at_event + 1, True)


def describe_person(row: Any, screen_yr: int) -> dict:
    """The non-identifying facts shown on the person card (MVP.md §6.6).

    `pkyr` (pack-years) is in the CDAS table but *not* in IDC's subset, so the
    card shows smoking status only. Every NLST participant was 55-74 with at
    least 30 pack-years, which the UI states as cohort context instead.
    """
    age = to_num(row["age"])
    days = to_num(row[f"scr_days{screen_yr}"]) or 0.0
    gender = to_num(row["gender"])
    cigsmok = to_num(row["cigsmok"])
    race = to_num(row["race"])
    return {
        "age_at_randomization": int(age) if age is not None else None,
        "age_at_scan": int(age + days // DAYS_PER_YEAR) if age is not None else None,
        "sex": GENDER.get(int(gender)) if gender is not None else None,
        "smoking_status": CIGSMOK.get(int(cigsmok)) if cigsmok is not None else None,
        "race": RACE.get(int(race)) if race is not None else None,
        "screening_round": f"T{screen_yr}",
    }


def describe_stage(row: Any) -> Optional[str]:
    stage = to_num(row.get("de_stag") if hasattr(row, "get") else row["de_stag"])
    if stage is None:
        return None
    return STAGE.get(int(stage))
