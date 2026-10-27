"""scripts/harvest.py's storage: atomic per-scan files, resume bookkeeping, compile.

No model weights, no network: scans are faked with random numbers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app import harvest
from app.harvest import HarvestDir, Scored, compile_dataset, scan_record
from app.trajectory import ROUNDS, YEARS, load_trajectories


def fake_scored(seed: int) -> Scored:
    rng = np.random.default_rng(seed)
    risks = np.sort(rng.uniform(0, 0.2, YEARS)).tolist()
    return Scored(calibrated=risks, raw_mean=risks, raw_per_model=[risks] * 5,
                  hidden=rng.normal(size=(5, 512)).astype(np.float32),
                  attention=rng.uniform(size=(25, 16, 16)).astype(np.float32))


@pytest.fixture
def hd(tmp_path, monkeypatch):
    people = pd.DataFrame({"diagnosed": [True, False], "years_rand_to_dx": [3.2, None]},
                          index=pd.Index(["100", "200"], name="nlst_pid"))
    monkeypatch.setattr(harvest.people, "table", lambda: people)
    d = HarvestDir(tmp_path / "harvest")
    d.ensure()
    return d


def save(hd: HarvestDir, pid: str, r: int) -> Scored:
    scored = fake_scored(int(pid) + r)
    hd.save(scan_record(f"{pid}_T{r}", pid, r, float(r), {"manufacturer": "GE"},
                        {"thickness_mm": 2.5}, scored, "cpu", {"model": 1.0}), scored)
    return scored


def test_compile_keeps_only_complete_participants(hd, tmp_path):
    kept = {r: save(hd, "100", r) for r in ROUNDS}
    save(hd, "200", 0)  # only T0 so far
    csv_path = tmp_path / "trajectories.csv"

    summary = compile_dataset(hd, csv_path)

    assert summary == {"scans": 4, "participants_complete": 1, "devices": ["cpu"],
                       "trajectories_csv": str(csv_path)}
    traj = load_trajectories(csv_path)
    assert traj.pids == ["100"]
    assert np.allclose(traj.risks[0], [kept[r].calibrated for r in ROUNDS], atol=1e-6)
    with np.load(hd.root / "features.npz") as z:
        assert z["hidden"].shape == (1, 3, 5, 512)
        assert np.array_equal(z["hidden"][0, 2], kept[2].hidden)
        assert z["attention"].shape == (1, 3, 25, 16, 16)
    assert len(pd.read_parquet(hd.root / "scans.parquet")) == 4


def test_leftovers_from_a_killed_run_are_not_counted(hd):
    save(hd, "100", 0)
    (hd.scans / "100_T1.json.tmp").write_text("{\"half", encoding="utf-8")
    (hd.features / "100_T1.npz.tmp").write_bytes(b"\0")
    (hd.tmp / "100_T1").mkdir()
    assert hd.done() == {"100_T0"}

    hd.clean_leftovers()
    assert not list(hd.scans.glob("*.tmp")) and not list(hd.features.glob("*.tmp"))
    assert not any(hd.tmp.iterdir())


def test_failure_log_survives_a_torn_last_line(hd):
    hd.record_failure("100_T1", "100", "reading", "bad header")
    with open(hd.failed_log, "a", encoding="utf-8") as fh:
        fh.write('{"patient_id": "200_T0", "nlst')  # killed mid-write
    assert list(hd.failed()) == ["100_T1"]
