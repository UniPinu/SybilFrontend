"""Wording that depends on the numbers, kept next to the numbers.

The rules in MVP.md section 8: absolute counts beside every percentage, "risk"
and "chance" rather than "has cancer", and the misses stated plainly.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

FOOTER = ("Research demonstration using public, de-identified trial data. "
          "Not for medical decisions.")

TRAINING_CAVEAT = ("Some of these people may have been part of the data Sybil learned from. "
                   "The published accuracy numbers come from people it had never seen.")

POOL_CAVEAT = ("This demo deliberately includes more people who developed cancer than a real "
               "screening population would, so there's something to see.")

# JCO 2023, Mikhael et al. (MVP.md section 7.3)
PUBLISHED_METRICS = [
    {
        "dataset": "NLST test set",
        "detail": "2,203 people, unseen in training",
        "auc_1y": 0.92,
        "c_index_6y": 0.75,
        "plain": ("Take one person who was diagnosed within a year and one who wasn't. "
                  "92 times out of 100, Sybil gives the person who got cancer the higher risk."),
    },
    {
        "dataset": "Massachusetts General Hospital",
        "detail": "a different hospital, different scanners",
        "auc_1y": 0.86,
        "c_index_6y": 0.81,
        "plain": ("On scans from a hospital it was not trained on, it got the pair the right "
                  "way round 86 times out of 100."),
    },
    {
        "dataset": "Chang Gung Memorial Hospital, Taiwan",
        "detail": "a mostly non-smoking population",
        "auc_1y": 0.94,
        "c_index_6y": 0.80,
        "plain": ("On a population very different from the trial it learned from, 94 times "
                  "out of 100."),
    },
]


def people_in_100(risk: float) -> int:
    return int(round(risk * 100))


def headline(risk_6y: float) -> str:
    n = people_in_100(risk_6y)
    return (f"About {n} in 100 people with a scan like this are diagnosed with lung cancer "
            f"within 6 years.")


def year_phrase(year_index: int, risk: float) -> str:
    return f"By year {year_index + 1}: {risk * 100:.1f}%"


def reveal(outcome: Dict[str, Any], result: Optional[Dict[str, Any]] = None,
           band: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """The sealed card's text once it flips."""
    if not outcome.get("available", True):
        return {
            "headline": "No outcome to reveal",
            "detail": outcome.get("note", ""),
            "reminder": FOOTER,
        }

    if outcome.get("eligible") is False:
        return excluded_reveal(outcome)

    risks = (result or {}).get("risk_by_year") or []
    comparison = ""
    if band and band.get("band"):
        comparison = f" Sybil placed this person in the “{band['band'].lower()}” range."

    if outcome.get("cancer_within_6y"):
        years = outcome.get("years_to_cancer")
        year_index = min(int(years or 0), len(risks) - 1) if risks else None
        nth = (years or 0) + 1
        # years_to_cancer == 0 means "inside the first year", so n means "between
        # n and n+1 years"; say which year it fell in rather than rounding it off.
        when = "within a year of this scan" if nth == 1 else f"in year {nth} after this scan"
        detail = ""
        if year_index is not None and risks:
            pct = risks[year_index] * 100
            detail = (f"Sybil's risk for that year was {pct:.1f}%, i.e. about "
                      f"{people_in_100(risks[year_index])} in 100.")
        stage = outcome.get("stage")
        if stage and stage.startswith("stage "):
            detail += f" The cancer was recorded as {stage}."
        missed = ""
        if risks and risks[-1] < 0.05:
            missed = (" Not every case is caught: Sybil rated this person as low risk, and they "
                      "were still diagnosed.")
        return {
            "headline": f"This person was diagnosed with lung cancer {when}.",
            "detail": (detail + comparison + missed).strip(),
            "reminder": ("A high risk is not a diagnosis, and a low risk is not a guarantee. "
                         + FOOTER),
        }

    followed = outcome.get("years_followed") or 0
    plural = "year" if followed == 1 else "years"
    detail = ""
    if risks:
        detail = (f"Sybil's 6-year risk for this person was {risks[-1] * 100:.1f}%, about "
                  f"{people_in_100(risks[-1])} in 100.")
    return {
        "headline": f"This person had no lung-cancer diagnosis during {followed} {plural} "
                    f"of follow-up.",
        "detail": (detail + comparison).strip(),
        "reminder": ("A low risk is not a guarantee, and follow-up ends where the trial's "
                     "records end. " + FOOTER),
    }


EXCLUDED_NOTE = ("Sybil's own evaluation leaves scans like this out, so it does not count "
                 "towards any accuracy figure here.")


def excluded_reveal(outcome: Dict[str, Any]) -> Dict[str, str]:
    """An exam run from Explore that has no 6-year label in Sybil's sense."""
    years = outcome.get("years_to_cancer")
    if years is None:
        headline_text = "This scan is outside Sybil's evaluation rules."
    elif years < 0:
        headline_text = "This scan was taken after the person's lung-cancer diagnosis."
    else:
        nth = years + 1
        when = "within a year of this scan" if nth == 1 else f"in year {nth} after this scan"
        headline_text = f"This person was diagnosed with lung cancer {when}."
    reason = outcome.get("exclusion_reason")
    detail = (f"Excluded because: {reason}. " if reason else "") + EXCLUDED_NOTE
    return {"headline": headline_text, "detail": detail, "reminder": FOOTER}
