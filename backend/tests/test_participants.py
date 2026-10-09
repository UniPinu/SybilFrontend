"""Explore: participant search, round status, batch runs and the longitudinal
results, on synthetic tables (tests/explore_fixtures.py) so nothing skips.

Same stub pipeline idea as test_api.py: no model, no network.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import data
from app.catalog import assemble
from app.config import Settings
from app.store import store
from tests.explore_fixtures import PRSN, ROUNDS_SEEN, SERIES

T0_RISKS = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
T1_RISKS = [0.05, 0.08, 0.10, 0.12, 0.14, 0.16]

# keys that say what happened to someone; none may appear (non-null) when blind
OUTCOME_KEYS = {"diagnosed", "years_rand_to_dx", "years_rand_to_last_free", "stage",
                "cancer_within_6y", "cancer_within_6y_any", "years_to_cancer",
                "years_followed", "diagnosis_years", "last_cancer_free_years"}


@pytest.fixture
def tables(tmp_path, monkeypatch):
    exams, candidates, participants, _ = assemble(SERIES, ROUNDS_SEEN, PRSN)
    paths = {}
    for name, frame in (("exams", exams), ("candidates", candidates),
                        ("participants", participants)):
        paths[name] = tmp_path / f"{name}.parquet"
        frame.to_parquet(paths[name], index=False)
    for name, path in paths.items():
        monkeypatch.setattr(Settings, f"{name}_path", property(lambda self, p=path: p))
    return paths


@pytest.fixture
def client(tables, clean_cache):
    from app.main import app

    with TestClient(app) as c:
        yield c


def fake_result(exam_id: str, risks) -> None:
    candidate = data.get_candidate(exam_id)
    store.write_meta(exam_id, {"patient_id": exam_id,
                               "candidate": data.without_outcome(candidate),
                               "series": {"n_files": 3, "thickness_mm": 2.5}})
    store.write_result(exam_id, {
        "patient_id": exam_id, "risk_by_year": risks, "n_slices": 3, "width": 32,
        "height": 32, "slice_importance": [0.2, 0.5, 0.3], "hotspot_slice": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "model": {"sybil_commit": "d9fc81b"},
    })
    store.write_outcome(exam_id, {**data.outcome_payload(candidate), "available": True})


def leaked(payload, path="") -> list:
    """Every outcome key carrying a value anywhere in a JSON payload."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in OUTCOME_KEYS and value is not None:
                found.append(f"{path}.{key}")
            if key == "outcome" and value is not None:
                found.append(f"{path}.outcome")
            found += leaked(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for i, value in enumerate(payload):
            found += leaked(value, f"{path}[{i}]")
    return found


# --- search ------------------------------------------------------------------
def test_search_lists_explorable_participants(client):
    page = client.get("/api/participants").json()
    assert page["total"] == 3
    assert [p["nlst_pid"] for p in page["items"]] == ["900001", "900002", "900003"]
    assert page["facets"]["diagnosed"] == 1
    assert page["facets"]["rounds"] == {"1": 1, "3": 2}


@pytest.mark.parametrize("query,expected", [
    ("diagnosed=true", ["900002"]),
    ("diagnosed=false", ["900001", "900003"]),
    ("rounds_min=3", ["900001", "900002"]),
    ("sex=Female", ["900002"]),
    ("smoking=Current smoker", ["900002", "900003"]),
    ("age_min=60&age_max=65", ["900001"]),
    ("manufacturer=SIEMENS", ["900001"]),
    ("q=90000", ["900001", "900002", "900003"]),
    ("q=900003", ["900003"]),
    ("sort=-age", ["900002", "900001", "900003"]),
    ("sort=dx", ["900002", "900001", "900003"]),
])
def test_search_filters_and_sorts(client, query, expected):
    page = client.get(f"/api/participants?{query}").json()
    assert [p["nlst_pid"] for p in page["items"]] == expected


def test_search_paginates(client):
    page = client.get("/api/participants?page=2&page_size=2").json()
    assert page["total"] == 3 and [p["nlst_pid"] for p in page["items"]] == ["900003"]


def test_search_knows_who_has_results(client):
    fake_result("900002_T0", T0_RISKS)
    page = client.get("/api/participants?has_results=true").json()
    assert [(p["nlst_pid"], p["results_ready"]) for p in page["items"]] == [("900002", 1)]
    assert client.get("/api/participants?has_results=false").json()["total"] == 2


def test_blind_search_has_no_outcomes_and_refuses_outcome_filters(client):
    page = client.get("/api/participants?blind=true").json()
    assert leaked(page) == []
    assert "diagnosed" not in page["facets"]
    assert client.get("/api/participants?blind=true&diagnosed=true").status_code == 400
    assert client.get("/api/participants?blind=true&sort=dx").status_code == 400


def test_bad_sort_is_400(client):
    assert client.get("/api/participants?sort=shoe_size").status_code == 400


# --- one participant -----------------------------------------------------------
def test_detail_shows_every_round(client):
    person = client.get("/api/participants/900002").json()
    rounds = {r["round"]: r for r in person["rounds"]}
    assert rounds["T0"]["status"] == "eligible" and rounds["T0"]["exam_id"] == "900002_T0"
    assert rounds["T2"]["status"] == "excluded" and rounds["T2"]["runnable"]
    assert rounds["T2"]["reason"] == "no scr_days2"
    assert rounds["T2"]["years_since_rand"] is None  # no screening date on record
    assert rounds["T1"]["outcome"]["years_to_cancer"] == 0
    assert person["outcome"]["stage"] == "stage IB"
    assert person["timeline"]["diagnosis_years"] == pytest.approx(1.4, abs=0.01)

    other = {r["round"]: r for r in client.get("/api/participants/900003").json()["rounds"]}
    assert other["T1"]["status"] == "no_usable_series" and not other["T1"]["runnable"]
    assert other["T1"]["exam_id"] is None


def test_blind_detail_hides_the_outcome_and_the_telling_reason(client):
    person = client.get("/api/participants/900002?blind=true").json()
    assert leaked(person) == []
    t2 = next(r for r in person["rounds"] if r["round"] == "T2")
    assert t2["status"] == "excluded"
    assert t2["reason"] == "outside Sybil's evaluation rules"


def test_unknown_participant_is_404(client):
    assert client.get("/api/participants/123").status_code == 404
    assert client.get("/api/participants/123/results").status_code == 404


def test_excluded_exam_works_in_the_story_endpoints(client):
    """An excluded round can be opened in the story view and has its own reveal."""
    assert client.get("/api/patients/900002_T2").status_code == 200
    fake_result("900002_T2", T1_RISKS)
    outcome = client.get("/api/patients/900002_T2/outcome").json()
    assert outcome["eligible"] is False and outcome["cancer_within_6y"] is None
    assert "outside Sybil's evaluation rules" in outcome["headline"]
    assert "no scr_days2" in outcome["detail"]
    # ... and stays off the scoreboard
    assert "900002_T2" not in [p["patient_id"] for p in client.get("/api/cohort").json()["people"]]
    meta = store.meta("900002_T2")
    assert "exclusion_reason" not in meta["candidate"] and "eligible" not in meta["candidate"]


# --- runs ------------------------------------------------------------------------
@pytest.fixture
def stub_pipeline(monkeypatch):
    from app import jobs as jobs_module

    calls: list[str] = []

    def fake_process(patient_id, emit=None, **kwargs):
        calls.append(patient_id)
        emit = emit or (lambda *a, **k: None)
        emit("model", index=1, of=5)
        fake_result(patient_id, T0_RISKS)
        emit("done", patient_id=patient_id, cached=False)

    monkeypatch.setattr(jobs_module, "process_patient", fake_process)
    monkeypatch.setattr("app.main.weights_present", lambda: True)
    return calls


def wait_for(client, job_ids, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        states = [client.get(f"/api/jobs/{j}").json()["state"] for j in job_ids]
        if all(s in {"done", "error"} for s in states):
            return states
        time.sleep(0.05)
    raise AssertionError(f"jobs did not finish: {states}")


def test_run_queues_rounds_in_chronological_order(client, stub_pipeline):
    fake_result("900001_T1", T1_RISKS)
    response = client.post("/api/participants/900001/runs",
                           json={"exam_ids": ["900001_T2", "900001_T1", "900001_T0"]})
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert [r["round"] for r in runs] == ["T0", "T1", "T2"]
    assert runs[1]["ready"] and runs[1]["job_id"] is None  # already cached
    assert wait_for(client, [runs[0]["job_id"], runs[2]["job_id"]]) == ["done", "done"]
    assert stub_pipeline == ["900001_T0", "900001_T2"]


def test_run_without_a_body_runs_every_runnable_round(client, stub_pipeline):
    runs = client.post("/api/participants/900002/runs").json()["runs"]
    assert [r["exam_id"] for r in runs] == ["900002_T0", "900002_T1", "900002_T2"]
    wait_for(client, [r["job_id"] for r in runs])


def test_run_rejects_rounds_that_are_not_this_participants(client, stub_pipeline):
    bad = client.post("/api/participants/900001/runs", json={"exam_ids": ["900002_T0"]})
    assert bad.status_code == 400
    assert client.post("/api/participants/900003/runs",
                       json={"exam_ids": ["900003_T1"]}).status_code == 400
    assert client.post("/api/participants/900001/runs", json={"exam_ids": []}).status_code == 400
    assert stub_pipeline == []


def test_detail_reports_a_queued_round(client, monkeypatch):
    """While a round waits, the participant page can show where it is."""
    from app.jobs import jobs

    monkeypatch.setattr("app.main.weights_present", lambda: True)
    monkeypatch.setattr(jobs, "submit", lambda exam_id: type(
        "J", (), {"id": "abc", "state": "queued"})())
    monkeypatch.setattr(jobs, "job_for_patient", lambda exam_id: type(
        "J", (), {"id": "abc", "state": "queued"})() if exam_id == "900003_T0" else None)
    monkeypatch.setattr(jobs, "stats", lambda: {"running": "xyz", "queued": ["abc"]})
    runs = client.post("/api/participants/900003/runs").json()["runs"]
    assert runs == [{"exam_id": "900003_T0", "round": "T0", "job_id": "abc",
                     "ready": False, "state": "queued"}]
    t0 = client.get("/api/participants/900003").json()["rounds"][0]
    assert t0["job"] == {"job_id": "abc", "state": "queued", "position": 1}


# --- results over time ------------------------------------------------------------
def test_results_put_every_round_on_one_axis(client):
    fake_result("900002_T0", T0_RISKS)
    fake_result("900002_T1", T1_RISKS)
    res = client.get("/api/participants/900002/results").json()
    assert [e["round"] for e in res["exams"]] == ["T0", "T1"]
    t0, t1 = res["exams"]
    assert t0["years_since_rand"] == pytest.approx(0.03, abs=0.01)
    assert t1["years_since_rand"] == pytest.approx(1.15, abs=0.01)
    assert t0["change_from_previous"] is None
    assert t1["change_from_previous"]["from_round"] == "T0"
    assert t1["change_from_previous"]["risk_by_year"] == pytest.approx(
        [b - a for a, b in zip(T0_RISKS, T1_RISKS)])
    assert t1["risk_pct_by_year"][-1] == 16.0
    assert t1["outcome"]["years_to_cancer"] == 0
    assert res["outcome"]["diagnosed"] is True


def test_blind_results_and_export_leak_nothing(client):
    fake_result("900002_T0", T0_RISKS)
    assert leaked(client.get("/api/participants/900002/results?blind=true").json()) == []
    csv = client.get("/api/participants/900002/export.csv?blind=true").text
    header = csv.splitlines()[0].split(",")
    assert not {"cancer_within_6y", "years_to_cancer", "stage",
                "participant_diagnosed"} & set(header)


def test_export_is_one_row_per_finished_round(client):
    fake_result("900002_T0", T0_RISKS)
    fake_result("900002_T1", T1_RISKS)
    response = client.get("/api/participants/900002/export.csv")
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="sybil_900002.csv"' in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    header = lines[0].split(",")
    assert len(lines) == 3
    assert {"risk_1y", "risk_6y", "years_since_randomization", "cancer_within_6y",
            "years_randomization_to_diagnosis", "stage"} <= set(header)
    assert lines[2].split(",")[header.index("risk_6y")] == "0.16"


def test_missing_tables_are_503(monkeypatch, tmp_path, clean_cache):
    from app.main import app

    monkeypatch.setattr(Settings, "participants_path",
                        property(lambda self: tmp_path / "nope.parquet"))
    with TestClient(app) as c:
        response = c.get("/api/participants")
    assert response.status_code == 503
    assert "build_candidates" in response.json()["detail"]
