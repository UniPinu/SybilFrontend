"""Sybil's features: extraction, storage, the numpy risk head, and the development analysis.

The fast tests use synthetic data and torch layers with random weights; the slow
one runs the real ensemble on upstream's demo scan.
"""
from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import torch

from app import development as dev
from app import features as F
from app.attention import VolumeGeometry


@pytest.fixture
def feature_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "feature_dir", lambda: tmp_path)
    F.load_heads.cache_clear()
    yield tmp_path
    F.load_heads.cache_clear()


def _fake_ensemble(seed: int = 0):
    from sybil.models.cumulative_probability_layer import Cumulative_Probability_Layer

    torch.manual_seed(seed)
    nets = []
    for _ in range(F.N_MODELS):
        layer = Cumulative_Probability_Layer(F.DIM, Namespace(), max_followup=F.YEARS)
        nets.append(SimpleNamespace(prob_of_failure_layer=layer))
    return SimpleNamespace(ensemble=nets)


# --- the head -------------------------------------------------------------------
def test_numpy_head_matches_sybils_layer():
    model = _fake_ensemble()
    heads = F.export_heads(model)
    h = np.abs(np.random.default_rng(1).normal(size=(3, F.N_MODELS, F.DIM))).astype(np.float32)
    ours = F.head_logits(heads, h)
    with torch.no_grad():
        theirs = np.stack([np.stack([net.prob_of_failure_layer(torch.from_numpy(h[:, k]))
                                     .numpy() for k, net in enumerate(model.ensemble)], 1)])[0]
    assert ours.shape == (3, F.N_MODELS, F.YEARS)
    assert np.allclose(ours, theirs, atol=1e-5)
    assert np.all(np.diff(ours, axis=-1) >= -1e-9)   # cumulative: never decreases


def test_risk_gradient_matches_finite_differences():
    heads = F.export_heads(_fake_ensemble(2))
    rng = np.random.default_rng(3)
    h, d = np.abs(rng.normal(size=(F.N_MODELS, F.DIM))), rng.normal(size=(F.N_MODELS, F.DIM))
    for year in (1, 6):
        eps = 1e-4
        numeric = (F.head_logits(heads, h + eps * d)[:, year - 1]
                   - F.head_logits(heads, h - eps * d)[:, year - 1]) / (2 * eps)
        assert np.allclose(numeric, (F.risk_gradient(heads, h, year) * d).sum(-1), atol=1e-6)


def test_heads_are_exported_once_and_reloaded(feature_dir):
    model = _fake_ensemble()
    assert F.load_heads() is None
    F.ensure_heads(model)
    loaded = F.load_heads()
    assert np.array_equal(loaded.hazard_w, F.export_heads(model).hazard_w)
    assert F.list_ids() == []   # heads.npz is not a scan


# --- extraction and storage -------------------------------------------------------
def _geometry(n_slices=120, thickness=2.5, spacing=0.703125):
    return VolumeGeometry(n_slices=n_slices, rows=512, cols=512, thickness_mm=thickness,
                          row_spacing_mm=spacing, col_spacing_mm=spacing)


def test_encoder_mean_leaves_out_the_padding():
    geom = _geometry(n_slices=120)              # 120 slices of 2.5 mm: padded 40 each side
    z, r, c = F.valid_cells(geom)
    assert (z.start, z.stop) == (5, 20)         # voxels 40..160 are cells 5..19
    assert (r.start, r.stop) == (0, 16)         # 0.703 mm in plane: no padding
    activ = np.full((1, F.DIM, 25, 16, 16), 100.0, dtype=np.float32)
    activ[:, :, z] = 1.0
    assert np.allclose(F.encoder_mean(torch.from_numpy(activ), geom), 1.0)


def test_cells_on_a_cropped_and_a_very_short_scan():
    long = _geometry(n_slices=400)              # longer than the model's 200 slots
    assert F.valid_cells(long)[0] == slice(0, 25)
    short = F._cells(offset=95, size=6, total=200, factor=8)   # inside one cell
    assert short.stop > short.start


def test_features_round_trip(feature_dir):
    hidden = np.random.default_rng(0).random((F.N_MODELS, F.DIM)).astype(np.float32)
    F.save("123_T0", {"hidden": hidden, "encoder": hidden * 2},
           raw_per_model=np.zeros((5, 6)), risk_by_year=np.arange(6) / 10)
    assert F.has("123_T0") and F.list_ids() == ["123_T0"]
    back = F.load("123_T0")
    assert np.array_equal(back["hidden"], hidden)
    assert np.allclose(back["risk_by_year"], np.arange(6) / 10)
    assert F.load("nope") is None


# --- the development analysis -------------------------------------------------------
def _synthetic(n_people=12, noise=0.15, seed=0, trend=0.0, shared=0.0, dx_every=3):
    """Each person has a stable vector, plus noise per scan and an optional trend."""
    rng = np.random.default_rng(seed)
    rows, people = [], []
    common = rng.normal(size=(F.N_MODELS, F.DIM))
    for p in range(n_people):
        pid = str(100000 + p)
        base = rng.normal(size=(F.N_MODELS, F.DIM)) + 3
        slope = rng.normal(size=(F.N_MODELS, F.DIM))
        for r in range(3):
            vec = base + noise * rng.normal(size=base.shape) + trend * r * slope + shared * r * common
            vec = np.maximum(vec, 0)
            meta = pd.Series({"nlst_pid": pid, "study_yr": r, "days_since_rand": 365.25 * r + 10,
                              "manufacturer": "GE" if p % 2 else "SIEMENS", "kernel": "B30f",
                              "thickness_mm": 2.5})
            feats = {"hidden": vec, "encoder": vec, "risk_by_year": np.linspace(0.01, 0.06, 6)}
            rows.append((f"{pid}_T{r}", meta, feats))
        people.append({"nlst_pid": pid, "diagnosed": p % dx_every == 0,
                       "years_rand_to_dx": 4.0 if p % dx_every == 0 else None})
    return dev.build_dataset(rows, pd.DataFrame(people).set_index("nlst_pid"))


@pytest.fixture
def use_dataset(monkeypatch):
    def install(ds, heads=None):
        token = object()
        monkeypatch.setattr(dev, "_signature", lambda: (token,))
        monkeypatch.setattr(dev, "_dataset", lambda sig: ds)
        monkeypatch.setattr(dev, "dataset", lambda: ds)
        monkeypatch.setattr(F, "load_heads", lambda: heads)
        return ds
    return install


def test_unrelated_scans_are_about_sqrt2_apart():
    z = np.random.default_rng(0).normal(size=(400, 300))
    z = (z - z.mean(0)) / z.std(0)
    D = dev.distances(z)
    off = D[~np.eye(len(z), dtype=bool)]
    assert abs(np.median(off) - np.sqrt(2)) < 0.03
    assert np.allclose(np.diag(D), 0, atol=1e-6)


def test_stable_people_are_recognised_and_change_little(use_dataset):
    use_dataset(_synthetic())
    out = dev.overview("hidden", None)
    assert out["counts"] == {"scans": 36, "participants": 12, "with_2_rounds": 12,
                             "with_3_rounds": 12, "diagnosed": 4}
    t01 = out["stability"]["pairs"][0]
    assert t01["reidentification"]["top1"] == 1.0
    assert t01["within"]["median"] < 0.5 * t01["between"]["median"]
    assert all(p["percentile_vs_between"] == 0.0 for p in out["pairs"])
    assert len(out["map"]["points"]) == 36


def test_one_network_only(use_dataset):
    use_dataset(_synthetic(n_people=6))
    out = dev.overview("encoder", 3)
    assert out["dims"]["total"] == F.DIM
    detail = dev.participant("100000", "encoder", 3)
    assert all(f["network"] == 3 for f in detail["top_features"])
    assert detail["top_features"][0]["label"].startswith("N3·")


def test_a_change_everyone_shares_is_reported_as_drift(use_dataset):
    use_dataset(_synthetic(shared=1.0, noise=0.05))
    drift = {d["from"] + d["to"]: d for d in dev.overview()["drift"]}
    assert drift["T0T1"]["shared_share"] > 0.8
    use_dataset(_synthetic(trend=1.0, noise=0.05, seed=1))
    drift = {d["from"] + d["to"]: d for d in dev.overview()["drift"]}
    assert drift["T0T1"]["shared_share"] < 0.2


def test_linear_trends_are_forecast_better_than_persistence(use_dataset):
    use_dataset(_synthetic(trend=0.5, noise=0.02))
    methods = {m["method"]: m for m in dev.overview()["forecast"]["methods"]}
    assert methods["linear"]["rms_error"]["median"] < 0.5 * methods["persistence"]["rms_error"]["median"]
    assert methods["damped"]["rms_error"]["median"] < methods["persistence"]["rms_error"]["median"]


def test_change_along_the_risk_direction_is_fully_visible(use_dataset):
    heads = F.export_heads(_fake_ensemble(4))
    ds = _synthetic(n_people=5, noise=0.0)
    i, j = ds.scans_of("100000")[0], ds.scans_of("100000")[1]
    g = F.risk_gradient(heads, ds.raw["hidden"][i])
    ds.raw["hidden"][j] = ds.raw["hidden"][i] + 1e-3 * g     # a tiny step straight up the score
    vis = dev._visibility(ds, heads, i, j)
    assert vis["share"] > 0.99 and vis["delta_logit_6y"] > 0
    orth = np.random.default_rng(0).normal(size=g.shape)
    orth -= (orth * g).sum(-1, keepdims=True) / np.square(g).sum(-1, keepdims=True) * g
    ds.raw["hidden"][j] = ds.raw["hidden"][i] + 1e-3 * orth   # sideways: invisible to the score
    assert dev._visibility(ds, heads, i, j)["share"] < 1e-6


def test_participant_payload(use_dataset):
    use_dataset(_synthetic(trend=0.3), heads=F.export_heads(_fake_ensemble()))
    out = dev.participant("100001", "hidden", None)
    assert [r["round"] for r in out["rounds"]] == ["T0", "T1", "T2"]
    assert [(p["from"], p["to"]) for p in out["pairs"]] == [("T0", "T1"), ("T1", "T2"), ("T0", "T2")]
    assert len(out["top_features"]) == dev.TOP_FEATURES
    assert all(len(f["z"]) == 3 and f["risk_weight"] is not None for f in out["top_features"])
    assert {m["method"] for m in out["forecast"]["methods"]} == set(dev.METHODS)
    assert out["outcome"]["diagnosed"] is False
    with pytest.raises(dev.NoFeatures):
        dev.participant("999999")


def test_bad_arguments_are_refused(use_dataset):
    use_dataset(_synthetic(n_people=4))
    with pytest.raises(dev.BadRequest):
        dev.overview("pixels")
    with pytest.raises(dev.BadRequest):
        dev.overview("hidden", 6)


def test_too_few_scans_returns_counts_only(use_dataset):
    ds = _synthetic(n_people=1)
    use_dataset(ds)
    out = dev.overview()
    assert out["counts"]["scans"] == 3 and out["map"] is None and out["stability"] is None


def test_export_csv(use_dataset):
    use_dataset(_synthetic(n_people=2))
    lines = dev.export_csv("hidden", 2).strip().split("\n")
    head = lines[0].split(",")
    assert len(lines) == 7 and head[8] == "n2_0" and len(head) == 8 + F.DIM
    assert lines[1].startswith("100000,100000_T0,T0,")


# --- the real thing ----------------------------------------------------------------
@pytest.mark.slow
def test_real_features_reproduce_sybils_scores():
    from app.demo_data import EXPECTED_DEMO_SCORES, demo_dicom_paths
    from app.runner import get_model, run_sybil, weights_present

    if not weights_present():
        pytest.skip("no weights")
    result = run_sybil(demo_dicom_paths())
    assert np.allclose(result.calibrated, EXPECTED_DEMO_SCORES, rtol=1e-4)
    assert result.features["hidden"].shape == (F.N_MODELS, F.DIM)
    assert result.features["encoder"].shape == (F.N_MODELS, F.DIM)
    scored = F.score(F.export_heads(get_model()), result.features["hidden"][None])
    assert np.allclose(scored["raw_per_model"][0], result.raw_per_model, atol=1e-6)
    assert np.allclose(scored["calibrated"][0], result.calibrated, atol=1e-6)


# --- the endpoints -------------------------------------------------------------------
def test_endpoints(use_dataset):
    from fastapi.testclient import TestClient

    from app.main import app

    use_dataset(_synthetic(n_people=5, trend=0.2), heads=F.export_heads(_fake_ensemble()))
    client = TestClient(app)
    body = client.get("/api/features/overview?space=hidden").json()
    assert body["counts"]["scans"] == 15 and body["visibility"] is not None
    assert client.get("/api/features/overview?space=encoder&model=2").json()["visibility"] is None
    assert client.get("/api/features/overview?space=pixels").status_code == 400
    assert client.get("/api/features/overview?model=7").status_code == 422
    one = client.get("/api/features/participants/100002?space=hidden&model=1").json()
    assert one["nlst_pid"] == "100002" and len(one["rounds"]) == 3
    assert client.get("/api/features/participants/424242").status_code == 404
    csv = client.get("/api/features/export.csv?space=encoder&model=5")
    assert csv.status_code == 200 and "sybil_features_encoder_n5.csv" in csv.headers["content-disposition"]
