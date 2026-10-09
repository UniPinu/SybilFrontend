"""Building the exam / candidate / participant tables (app/catalog.py) and the
index query that feeds them."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from app.catalog import (ELIGIBLE, EXCLUDED, NO_IMAGES, NO_USABLE_SERIES, assemble,
                         participant_rows)
from tests.explore_fixtures import PRSN, ROUNDS_SEEN, SERIES, series_row

BUILD_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_candidates.py"


@pytest.fixture(scope="module")
def built():
    return assemble(SERIES, ROUNDS_SEEN, PRSN)


def test_exams_include_excluded_rounds_and_candidates_do_not(built):
    exams, candidates, _, excluded = built
    assert set(exams.patient_id) == {"900001_T0", "900001_T1", "900001_T2",
                                     "900002_T0", "900002_T1", "900002_T2", "900003_T0"}
    assert "900002_T2" not in set(candidates.patient_id)
    assert set(candidates.patient_id) == set(exams.patient_id[exams.eligible])
    assert excluded == {"no scr_days2": 1}
    assert candidates["cancer_within_6y"].dtype == bool


def test_excluded_exam_keeps_its_reason_but_has_no_label(built):
    exams = built[0].set_index("patient_id")
    row = exams.loc["900002_T2"]
    assert not row.eligible
    assert row.exclusion_reason == "no scr_days2"
    assert row.cancer_within_6y is None


def test_diagnosed_rounds_are_labelled_like_sybil_labels_them(built):
    exams = built[0].set_index("patient_id")
    # diagnosed at day 510: one year after T0 (day 12), inside the year after T1 (day 420)
    assert exams.loc["900002_T0", "years_to_cancer"] == 1
    assert exams.loc["900002_T1", "years_to_cancer"] == 0
    assert bool(exams.loc["900002_T1", "cancer_within_6y"])


def test_round_statuses(built):
    people = built[2].set_index("nlst_pid")
    assert list(people.loc["900001", ["t0_status", "t1_status", "t2_status"]]) == [ELIGIBLE] * 3
    assert list(people.loc["900002", ["t0_status", "t1_status", "t2_status"]]) == [
        ELIGIBLE, ELIGIBLE, EXCLUDED]
    assert list(people.loc["900003", ["t0_status", "t1_status", "t2_status"]]) == [
        ELIGIBLE, NO_USABLE_SERIES, NO_IMAGES]
    assert people.loc["900003", "t2_reason"] == "not screened in this round"


def test_participant_columns(built):
    people = built[2].set_index("nlst_pid")
    assert "900004" not in people.index  # nothing usable to run
    p = people.loc["900002"]
    assert bool(p.diagnosed) and p.years_rand_to_dx == pytest.approx(1.4, abs=0.01)
    assert (p.n_rounds, p.n_eligible) == (3, 2)
    assert p.sex == "Female" and p.stage_code == 120
    assert people.loc["900001", "manufacturers"] == "GE MEDICAL SYSTEMS; SIEMENS"
    assert not bool(people.loc["900001", "diagnosed"])


def test_two_series_for_one_round_is_an_error():
    series = pd.concat([SERIES, pd.DataFrame([series_row("900001", 1, study="other",
                                                         series="other")])])
    with pytest.raises(ValueError, match="900001_T1"):
        assemble(series, ROUNDS_SEEN, PRSN)


def test_participants_skip_people_without_exams():
    exams = assemble(SERIES, ROUNDS_SEEN, PRSN)[0]
    rows = participant_rows(exams[exams.nlst_pid == "900003"], ROUNDS_SEEN, PRSN)
    assert rows.nlst_pid.tolist() == ["900003"]


def test_index_query_keeps_one_series_per_participant_and_round():
    """IDC holds two studies for some participant-rounds; ranking per study kept both."""
    spec = importlib.util.spec_from_file_location("build_candidates", BUILD_SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    def idx(pid, study, series, desc, size, count=150):
        return dict(PatientID=pid, StudyInstanceUID=study, SeriesInstanceUID=series,
                    SeriesDescription=desc, instanceCount=count, series_size_MB=size,
                    Manufacturer="GE MEDICAL SYSTEMS", collection_id="nlst", Modality="CT")

    index = pd.DataFrame([
        idx("1", "s1", "a", "0,OPA,GE,LSULT,BONE,317,2.5,120,40,29.6,1.4", 80.0),
        idx("1", "s2", "b", "0,OPA,GE,LSULT,BONE,317,1.2,120,40,29.6,1.4", 72.0),
        idx("1", "s3", "c", "1,OPA,SE,SEN16,B50f,354,2,120,52.5,35,1.5", 120.0),
        idx("1", "s4", "d", "1,OPA,SE,SEN16,B50f,354,2,120,52.5,35,1.5", 120.0),
        idx("1", "s5", "e", "2,OPL,GE,LSULT,BONE,317,2.5,120,40,29.6,1.4", 5.0, count=2),
    ])
    con = duckdb.connect()
    con.register("index", index)
    picked = con.execute(script.CANDIDATE_SQL.format(max_mb=150)).df()
    assert sorted(zip(picked.study_yr, picked.SeriesInstanceUID)) == [(0, "b"), (1, "c")]
    seen = con.execute(script.ROUNDS_SQL).df()
    assert sorted(seen.study_yr) == [0, 1, 2]  # the localizer-only round still counts as imaged
