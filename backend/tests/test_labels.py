"""The outcome labels must mean what they meant when Sybil was evaluated."""
from __future__ import annotations

import numpy as np
import pytest

from app.labels import describe_person, nlst_label, to_num

BASE = {
    "age": 64,
    "gender": 1,
    "race": 1,
    "cigsmok": 1,
    "scr_days0": "12",
    "scr_days1": "374",
    "scr_days2": "738",
    "candx_days": "",
    "cancyr": "",
    "canc_free_days": 2381,
    "de_stag": "",
}


def row(**overrides):
    return {**BASE, **overrides}


# --- missing-value coding ---------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("", None), (" ", None), (".", None), (".N", None), ("nan", None), (None, None),
    ("0", 0.0), ("-4", -4.0), (7, 7.0), (2.5, 2.5), (np.nan, None), (np.int64(3), 3.0),
])
def test_to_num_handles_idc_missing_values(raw, expected):
    assert to_num(raw) == expected


# --- no cancer --------------------------------------------------------------
def test_cancer_free_participant():
    label = nlst_label(row(), screen_yr=0)
    assert label.valid and not label.cancer_within_6y
    assert label.years_to_cancer is None
    # (2381 - 12) // 365 = 6 years, capped at max_followup - 1 then +1
    assert label.years_followed == 6


def test_short_follow_up_is_reported_honestly():
    label = nlst_label(row(canc_free_days=800), screen_yr=0)
    assert label.valid and not label.cancer_within_6y
    assert label.years_followed == 3  # (800-12)//365 = 2 -> "followed 3 years"


# --- cancer -----------------------------------------------------------------
def test_cancer_in_the_first_year_after_the_scan():
    label = nlst_label(row(candx_days="200", cancyr="0", canc_free_days=150), screen_yr=0)
    assert label.valid and label.cancer_within_6y
    assert label.years_to_cancer == 0  # 0 means "inside the first year"
    assert label.years_followed == 1


def test_cancer_in_year_four():
    label = nlst_label(row(candx_days="1600", cancyr="4", canc_free_days=1500), screen_yr=0)
    assert label.years_to_cancer == 4
    assert label.cancer_within_6y


def test_cancer_after_six_years_is_not_a_positive_label():
    label = nlst_label(row(candx_days="2600", cancyr="6", canc_free_days=2500), screen_yr=0)
    assert label.valid and not label.cancer_within_6y
    assert label.years_followed == 6


def test_label_is_relative_to_the_screening_round():
    # diagnosed 1600 days after randomisation; from T2 (738 days) that is year 2
    label = nlst_label(row(candx_days="1600", cancyr="4", canc_free_days=1500), screen_yr=2)
    assert label.years_to_cancer == 2


# --- exclusions Sybil's skip_sample would also make -------------------------
def test_scan_taken_after_the_diagnosis_is_excluded():
    label = nlst_label(row(candx_days="100", cancyr="0", canc_free_days=90), screen_yr=1)
    assert not label.valid
    assert "before this scan" in label.reason


def test_missing_screen_date_is_excluded():
    label = nlst_label(row(scr_days2=""), screen_yr=2)
    assert not label.valid and "scr_days2" in label.reason


def test_no_outcome_timing_at_all_is_excluded():
    label = nlst_label(row(candx_days="", canc_free_days=""), screen_yr=0)
    assert not label.valid


def test_follow_up_ending_before_the_scan_is_excluded():
    label = nlst_label(row(canc_free_days=10), screen_yr=2)
    assert not label.valid and "follow-up" in label.reason


# --- person card ------------------------------------------------------------
def test_person_card_ages_the_participant_to_the_scan_date():
    card = describe_person(row(), screen_yr=2)
    assert card["age_at_randomization"] == 64
    assert card["age_at_scan"] == 66  # 738 days later
    assert card["sex"] == "Male"
    assert card["smoking_status"] == "Current smoker"
    assert card["screening_round"] == "T2"


def test_person_card_never_leaks_the_outcome():
    card = describe_person(row(candx_days="200", cancyr="0"), screen_yr=0)
    assert not any("canc" in k for k in card)
