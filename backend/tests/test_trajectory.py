"""T0 + T1 -> T2: interpolation, the hand-written models and the CV harness.

Pure numpy on synthetic data; no model weights, no network.
"""
from __future__ import annotations

import csv

import numpy as np
import pytest

from app.trajectory import (CSV_COLUMNS, MLP, YEARS, LinearRegression, Spec, Trajectories,
                            combined_curve, cross_validate, curve_forecast, design,
                            load_trajectories, metrics, paired_difference, pchip, risk_columns)

K = np.arange(1, YEARS + 1)


def constant_hazard(h: float) -> np.ndarray:
    return 1 - np.exp(-h * K)


def test_pchip_hits_knots_and_stays_monotone():
    x = np.arange(7.0)
    y = np.array([0, 0.01, 0.011, 0.05, 0.051, 0.2, 0.21])
    f = pchip(x, y)
    assert np.allclose(f(x), y)
    dense = f(np.linspace(0, 6, 601))
    assert np.all(np.diff(dense) >= -1e-12)
    assert dense.min() >= 0 and dense.max() <= 0.21 + 1e-12  # no overshoot


def test_curve_passes_through_t0_and_is_continuous():
    r0, r1 = constant_hazard(0.02), constant_hazard(0.03)
    curve = combined_curve(r0, r1, offset=1.1)
    assert np.allclose(curve(np.arange(0, 2)), [0, r0[0]], atol=1e-3)
    assert np.all(np.diff(curve.values) >= 0)
    assert np.max(np.abs(np.diff(curve.values))) < 0.01  # no jumps at 1.1 or 6


def test_curve_forecast_recovers_a_constant_hazard():
    """With one constant hazard, every scan reports the same six numbers."""
    r = constant_hazard(0.03)
    curve = combined_curve(r, r, offset=1.0)
    assert np.allclose(curve_forecast(curve, 2.0), r, atol=2e-3)


def test_curve_rejects_bad_offset():
    r = constant_hazard(0.02)
    with pytest.raises(ValueError):
        combined_curve(r, r, offset=0.0)


def test_linear_regression_recovers_a_linear_map():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 13))
    W = rng.normal(size=(13, 6))
    Y = X @ W + 0.5
    model = LinearRegression(ridge=1e-8).fit(X, Y)
    z = model._predict((X - model.x_mean) / model.x_std) * model.y_std + model.y_mean
    assert np.allclose(z, Y, atol=1e-5)


def test_mlp_gradients_match_finite_differences():
    rng = np.random.default_rng(1)
    X, Y = rng.normal(size=(20, 13)), rng.normal(size=(20, 6))
    mlp = MLP(hidden=5, weight_decay=1e-2, seed=3)
    mlp.init(13, 6)
    _, grads = mlp.loss_and_grads(X, Y)
    for name, param in mlp.params.items():
        for idx in [(0,) * param.ndim, tuple(s - 1 for s in param.shape)]:
            old = param[idx]
            param[idx] = old + 1e-6
            up, _ = mlp.loss_and_grads(X, Y)
            param[idx] = old - 1e-6
            down, _ = mlp.loss_and_grads(X, Y)
            param[idx] = old
            assert grads[name][idx] == pytest.approx((up - down) / 2e-6, rel=1e-4, abs=1e-8)


def test_mlp_training_lowers_the_loss():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(100, 13))
    Y = np.tanh(X[:, :6]) + 0.1 * X[:, 6:12]
    mlp = MLP(hidden=8, epochs=500).fit(X, Y)
    assert mlp.losses[-1] < 0.5 * mlp.losses[0]


def _offset_matters(n: int = 120, seed: int = 0) -> Trajectories:
    """T2's risk depends on how late T1 was, which only the offset input reveals."""
    rng = np.random.default_rng(seed)
    hazard = np.exp(rng.normal(np.log(0.02), 0.5, n))
    years = np.column_stack([np.zeros(n), rng.uniform(0.6, 1.6, n), np.full(n, 2.0)])
    risks = np.stack([np.array([constant_hazard(h) for h in hazard]),
                      np.array([constant_hazard(h) for h in hazard]),
                      np.array([constant_hazard(h * np.exp(1.5 * (d - 1.1)))
                                for h, d in zip(hazard, years[:, 1])])], axis=1)
    return Trajectories([str(i) for i in range(n)], years, risks)


def test_design_has_13_inputs_with_offset_and_12_without():
    traj = _offset_matters(10)
    assert design(traj, with_offset=True)[0].shape == (10, 13)
    assert design(traj, with_offset=False)[0].shape == (10, 12)
    assert design(traj)[1].shape == (10, 6)


def test_cross_validation_detects_a_useful_offset():
    traj = _offset_matters()
    specs = {"without": Spec(False, lambda s: LinearRegression()),
             "with": Spec(True, lambda s: LinearRegression())}
    preds = cross_validate(traj, specs, folds=5, repeats=2)
    truth = traj.risks[:, 2]
    assert preds["with"].shape == (2, len(traj), YEARS)
    assert metrics(preds["with"], truth)["mae_pp"] < metrics(preds["without"], truth)["mae_pp"]
    err = {k: np.abs(v - truth).mean(axis=(0, 2)) for k, v in preds.items()}
    d = paired_difference(err["with"], err["without"])
    assert d["hi"] < 0


def test_cross_validation_needs_enough_people():
    with pytest.raises(ValueError):
        cross_validate(_offset_matters(6), {"x": Spec(True, lambda s: LinearRegression())})


def test_load_trajectories_round_trip(tmp_path):
    path = tmp_path / "t.csv"
    row = {"nlst_pid": "100", "t0_years": 0.0, "t1_years": 1.0, "t2_years": 2.1,
           "diagnosed": False, "years_rand_to_dx": ""}
    for r in range(3):
        row.update(zip(risk_columns(r), constant_hazard(0.01 * (r + 1))))
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    traj = load_trajectories(path)
    assert traj.pids == ["100"]
    assert traj.risks.shape == (1, 3, 6)
    assert traj.offsets[0] == pytest.approx(1.0)
    assert traj.t2_offsets[0] == pytest.approx(2.1)


def test_guide_for_one_participant_is_consistent():
    from app.experiment import build_guide

    years = np.array([0.03, 0.95, 2.08])
    risks = np.stack([constant_hazard(0.02), constant_hazard(0.03), constant_hazard(0.04)])
    g = build_guide("1", years, risks)
    assert g["offset"] == pytest.approx(0.92)
    assert len(g["network"]["inputs"]) == 13
    assert len(g["network"]["outputs"]) == YEARS
    # T1's points move onto T0's clock above the shared base, and stay monotone
    on_t0 = [p["risk"] for p in g["align"]["t1_on_t0_clock"]]
    assert on_t0[0] > g["align"]["base"] and np.all(np.diff(on_t0) > 0)
    combined = [p["combined"] for p in g["curve"]]
    assert np.all(np.diff(combined) >= 0)
    assert g["curve"][-1]["t"] == pytest.approx(g["t2_offset"] + YEARS, abs=0.1)
    f = g["forecast"]
    assert f["persistence"] == pytest.approx(list(risks[1]), abs=1e-6)
    assert f["persistence_mae_pp"] == pytest.approx(np.abs(risks[1] - risks[2]).mean() * 100, abs=1e-3)
