"""Can two consecutive scans predict the third? T0 + T1 -> T2.

Sybil gives six cumulative risks per scan: P(cancer within k years of *this*
scan), k = 1..6. Three screening rounds about a year apart give 18 numbers per
participant. This module asks whether the first 12, plus the time between the
first two scans, say anything about the last 6 beyond "T2 looks like T1".

Three ingredients, all plain numpy:

* `combined_curve` turns T0's and T1's discrete points into one continuous,
  non-decreasing risk curve on T0's time axis. T0 covers years 1..6 after T0;
  T1 covers years 1..6 after T1, i.e. roughly years 2..7 after T0.
* `LinearRegression` and `MLP` (13 inputs -> 6 outputs, hand-written backprop)
  learn T2's six numbers from T0's six, T1's six and the T0 -> T1 offset.
* `cross_validate` + `paired_difference` score every model on held-out
  participants, so "does the offset help?" is a with/without comparison.

Data comes from scripts/build_trajectories.py; scripts/fit_trajectory.py runs
the comparison.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence

import numpy as np

YEARS = 6
ROUNDS = (0, 1, 2)
EPS = 1e-4  # Sybil's smallest outputs are ~1e-3; keeps logits finite


# --- interpolation ---------------------------------------------------------

def _edge_slope(h0: float, h1: float, d0: float, d1: float) -> float:
    """One-sided end slope for PCHIP that keeps the end segment monotone."""
    m = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
    if np.sign(m) != np.sign(d0):
        return 0.0
    if np.sign(d0) != np.sign(d1) and abs(m) > abs(3 * d0):
        return 3 * d0
    return m


def pchip(x: Sequence[float], y: Sequence[float]) -> Callable[[np.ndarray], np.ndarray]:
    """Monotone cubic interpolation (Fritsch-Carlson), extrapolated linearly.

    Unlike a cubic spline it never overshoots, so a non-decreasing set of
    cumulative risks gives a non-decreasing curve.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 3 or np.any(np.diff(x) <= 0):
        raise ValueError("pchip needs at least 3 strictly increasing knots")
    h = np.diff(x)
    delta = np.diff(y) / h
    m = np.zeros_like(y)
    for i in range(1, len(x) - 1):
        if delta[i - 1] * delta[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    m[0] = _edge_slope(h[0], h[1], delta[0], delta[1])
    m[-1] = _edge_slope(h[-1], h[-2], delta[-1], delta[-2])

    def f(t: np.ndarray) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        i = np.clip(np.searchsorted(x, t) - 1, 0, len(x) - 2)
        s = (t - x[i]) / h[i]
        inside = (y[i] * (2 * s**3 - 3 * s**2 + 1) + h[i] * m[i] * (s**3 - 2 * s**2 + s)
                  + y[i + 1] * (-2 * s**3 + 3 * s**2) + h[i] * m[i + 1] * (s**3 - s**2))
        out = np.where(t < x[0], y[0] + m[0] * (t - x[0]), inside)
        return np.where(t > x[-1], y[-1] + m[-1] * (t - x[-1]), out)

    return f


@dataclass
class RiskCurve:
    """Cumulative risk on T0's time axis, sampled densely; call it like a function."""
    grid: np.ndarray
    values: np.ndarray
    offset: float  # years from T0 to T1

    def __call__(self, t) -> np.ndarray:
        return np.interp(t, self.grid, self.values)


def combined_curve(r0: Sequence[float], r1: Sequence[float], offset: float, *,
                   horizon: float = 12.0, step: float = 0.01) -> RiskCurve:
    """One continuous curve from T0's and T1's six points.

    T1's numbers are conditional on being cancer-free at T1, so on T0's axis
    they become F(offset + k) = F(offset) + (1 - F(offset)) * r1[k], with
    F(offset) read off T0's own curve. Where the two curves overlap
    (offset .. 6) the weight slides linearly from T0 to the newer T1, which
    keeps the result continuous at both ends; past year 6 only T1 remains.
    """
    f0, f1, _ = curve_parts(r0, r1, offset)
    grid = np.arange(0.0, horizon + step / 2, step)
    w = blend_weight(grid, offset)
    values = (1 - w) * f0(grid) + w * f1(grid)
    values = np.clip(np.maximum.accumulate(values), 0.0, 1.0)
    return RiskCurve(grid, values, offset)


def curve_parts(r0: Sequence[float], r1: Sequence[float], offset: float):
    """T0's own curve, T1's curve moved onto T0's axis, and F0(offset) that links them."""
    if not 0 < offset < YEARS:
        raise ValueError(f"offset between T0 and T1 must be in (0, {YEARS}) years, got {offset}")
    knots = np.arange(YEARS + 1, dtype=float)
    f0 = pchip(knots, np.concatenate([[0.0], r0]))
    base = float(f0(offset))
    f1 = pchip(offset + knots, base + (1 - base) * np.concatenate([[0.0], r1]))
    return f0, f1, base


def blend_weight(t: np.ndarray, offset: float) -> np.ndarray:
    """How much the combined curve trusts T1 at time t: 0 up to T1, 1 from year 6."""
    return np.clip((np.asarray(t, dtype=float) - offset) / (YEARS - offset), 0.0, 1.0)


def scan_polynomial(risks: Sequence[float], degree: int = YEARS - 1) -> np.ndarray:
    """Coefficients (highest power first) of a polynomial through one scan's points (k, risk_k), k = 1..6.

    At the default degree 5 it passes exactly through all six points.
    """
    return np.polyfit(np.arange(1, YEARS + 1, dtype=float), np.asarray(risks, dtype=float), degree)


@dataclass
class Development:
    """T0 -> T1 carried forward to T2, everything on the newer scan's own clock (k = 1..6)."""
    t0_coef: np.ndarray
    t1_coef: np.ndarray
    t0_aligned: np.ndarray  # P0(k + d01): T0 read at the same moments T1 reports on
    offset: np.ndarray      # r1(k) - P0(k + d01): how much T1 moved away from T0
    t1_slid: np.ndarray     # P1(k + d12): T1 read at the same moments T2 reports on
    forecast: np.ndarray    # P1(k + d12) + offset, clipped to [0, 1]


def development_forecast(r0: Sequence[float], r1: Sequence[float], d01: float, d12: float,
                         degree: int = YEARS - 1) -> Development:
    """Predict T2 by assuming T1 -> T2 changes the way T0 -> T1 did.

    With d01 = 1 exactly, T0's 2-year point lines up with T1's 1-year point,
    and so on; the polynomials handle gaps that are not whole years. Note that
    P(k + d) for k = 6 reaches past the last point, i.e. the polynomial extrapolates.
    """
    k = np.arange(1, YEARS + 1, dtype=float)
    p0, p1 = scan_polynomial(r0, degree), scan_polynomial(r1, degree)
    t0_aligned = np.polyval(p0, k + d01)
    offset = np.asarray(r1, dtype=float) - t0_aligned
    t1_slid = np.polyval(p1, k + d12)
    return Development(p0, p1, t0_aligned, offset, t1_slid, np.clip(t1_slid + offset, 0.0, 1.0))


def curve_forecast(curve: RiskCurve, at: float) -> np.ndarray:
    """What a scan taken `at` years after T0 should report, read off the curve."""
    if at + YEARS > curve.grid[-1]:
        raise ValueError(f"curve only reaches {curve.grid[-1]} years; need {at + YEARS}")
    base = float(curve(at))
    ahead = curve(at + np.arange(1, YEARS + 1))
    return np.clip((ahead - base) / max(1 - base, EPS), 0.0, 1.0)


# --- data ------------------------------------------------------------------

def risk_columns(round_: int) -> List[str]:
    return [f"t{round_}_r{k}" for k in range(1, YEARS + 1)]


CSV_COLUMNS = (["nlst_pid"] + [f"t{r}_years" for r in ROUNDS]
               + [c for r in ROUNDS for c in risk_columns(r)]
               + ["diagnosed", "years_rand_to_dx"])


@dataclass
class Trajectories:
    """n participants, each with three scans: years since randomization and risks."""
    pids: List[str]
    years: np.ndarray  # (n, 3)
    risks: np.ndarray  # (n, 3, 6)

    def __len__(self) -> int:
        return len(self.pids)

    @property
    def offsets(self) -> np.ndarray:
        """T0 -> T1, the 13th input."""
        return self.years[:, 1] - self.years[:, 0]

    @property
    def t2_offsets(self) -> np.ndarray:
        """T0 -> T2, only used by the curve baseline."""
        return self.years[:, 2] - self.years[:, 0]

    def subset(self, idx: np.ndarray) -> "Trajectories":
        return Trajectories([self.pids[i] for i in idx], self.years[idx], self.risks[idx])


def load_trajectories(path: Path) -> Trajectories:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return Trajectories(
        pids=[r["nlst_pid"] for r in rows],
        years=np.array([[float(r[f"t{k}_years"]) for k in ROUNDS] for r in rows]).reshape(-1, 3),
        risks=np.array([[[float(r[c]) for c in risk_columns(k)] for k in ROUNDS]
                        for r in rows]).reshape(-1, 3, YEARS),
    )


# --- models ----------------------------------------------------------------

def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-z))


def design(traj: Trajectories, *, with_offset: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """13 inputs (logit T0 x6, logit T1 x6, offset) -> 6 targets (logit T2)."""
    parts = [logit(traj.risks[:, 0]), logit(traj.risks[:, 1])]
    if with_offset:
        parts.append(traj.offsets[:, None])
    return np.hstack(parts), logit(traj.risks[:, 2])


class _Model:
    """Standardizes inputs and targets; predicts cumulative risks (non-decreasing)."""

    def fit(self, X: np.ndarray, Y: np.ndarray) -> "_Model":
        self.x_mean, self.x_std = X.mean(0), X.std(0) + 1e-8
        self.y_mean, self.y_std = Y.mean(0), Y.std(0) + 1e-8
        self._fit((X - self.x_mean) / self.x_std, (Y - self.y_mean) / self.y_std)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        z = self._predict((X - self.x_mean) / self.x_std) * self.y_std + self.y_mean
        return np.maximum.accumulate(sigmoid(z), axis=1)

    def _fit(self, X: np.ndarray, Y: np.ndarray) -> None:
        raise NotImplementedError

    def _predict(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class LinearRegression(_Model):
    """Least squares with a small ridge penalty (not on the bias)."""

    def __init__(self, ridge: float = 1e-2):
        self.ridge = ridge

    def _fit(self, X: np.ndarray, Y: np.ndarray) -> None:
        A = np.hstack([X, np.ones((len(X), 1))])
        penalty = self.ridge * np.eye(A.shape[1])
        penalty[-1, -1] = 0.0
        self.W = np.linalg.solve(A.T @ A + penalty, A.T @ Y)

    def _predict(self, X: np.ndarray) -> np.ndarray:
        return np.hstack([X, np.ones((len(X), 1))]) @ self.W


class MLP(_Model):
    """inputs -> tanh hidden layer -> 6 linear outputs, full-batch Adam, manual backprop."""

    # Defaults are deliberately conservative: with tens of participants, 2000
    # epochs at weight decay 1e-3 overfit badly on synthetic data.
    def __init__(self, hidden: int = 8, epochs: int = 500, lr: float = 1e-2,
                 weight_decay: float = 1e-2, seed: int = 0):
        self.hidden, self.epochs, self.lr = hidden, epochs, lr
        self.weight_decay, self.seed = weight_decay, seed

    def init(self, n_in: int, n_out: int) -> None:
        rng = np.random.default_rng(self.seed)
        self.params = {
            "W1": rng.normal(0, 1 / np.sqrt(n_in), (n_in, self.hidden)),
            "b1": np.zeros(self.hidden),
            "W2": rng.normal(0, 1 / np.sqrt(self.hidden), (self.hidden, n_out)),
            "b2": np.zeros(n_out),
        }

    def loss_and_grads(self, X: np.ndarray, Y: np.ndarray) -> tuple[float, Dict[str, np.ndarray]]:
        p, wd = self.params, self.weight_decay
        H = np.tanh(X @ p["W1"] + p["b1"])
        err = H @ p["W2"] + p["b2"] - Y
        loss = float(np.mean(err**2) + wd * (np.sum(p["W1"]**2) + np.sum(p["W2"]**2)))
        d_out = 2 * err / err.size
        d_hidden = (d_out @ p["W2"].T) * (1 - H**2)
        return loss, {
            "W1": X.T @ d_hidden + 2 * wd * p["W1"],
            "b1": d_hidden.sum(0),
            "W2": H.T @ d_out + 2 * wd * p["W2"],
            "b2": d_out.sum(0),
        }

    def _fit(self, X: np.ndarray, Y: np.ndarray) -> None:
        self.init(X.shape[1], Y.shape[1])
        b1, b2 = 0.9, 0.999
        m = {k: np.zeros_like(v) for k, v in self.params.items()}
        v = {k: np.zeros_like(w) for k, w in self.params.items()}
        self.losses = []
        for step in range(1, self.epochs + 1):
            loss, grads = self.loss_and_grads(X, Y)
            self.losses.append(loss)
            for k, g in grads.items():
                m[k] = b1 * m[k] + (1 - b1) * g
                v[k] = b2 * v[k] + (1 - b2) * g**2
                m_hat, v_hat = m[k] / (1 - b1**step), v[k] / (1 - b2**step)
                self.params[k] -= self.lr * m_hat / (np.sqrt(v_hat) + 1e-8)

    def _predict(self, X: np.ndarray) -> np.ndarray:
        p = self.params
        return np.tanh(X @ p["W1"] + p["b1"]) @ p["W2"] + p["b2"]


# --- evaluation ------------------------------------------------------------

@dataclass
class Spec:
    """A learned model: which inputs it sees and how to build a fresh one."""
    with_offset: bool
    make: Callable[[int], _Model]  # seed -> unfitted model


def persistence(traj: Trajectories) -> np.ndarray:
    """Baseline: T2 reports the same six numbers as T1."""
    return traj.risks[:, 1].copy()


def curve_baseline(traj: Trajectories) -> np.ndarray:
    """Baseline: read T2's six numbers off the combined T0+T1 curve, at T2's real date."""
    horizon = float(np.ceil(traj.t2_offsets.max() + YEARS + 1)) if len(traj) else 12.0
    return np.array([
        curve_forecast(combined_curve(r[0], r[1], d1, horizon=horizon), d2)
        for r, d1, d2 in zip(traj.risks, traj.offsets, traj.t2_offsets)
    ])


def development_baseline(traj: Trajectories, *, with_offset: bool = True) -> np.ndarray:
    """Baseline: T1 slid on to T2's date, plus (or without) the T0 -> T1 offset."""
    d12 = traj.years[:, 2] - traj.years[:, 1]
    out = [development_forecast(r[0], r[1], d01, d) for r, d01, d in zip(traj.risks, traj.offsets, d12)]
    return np.array([np.clip(f.t1_slid, 0, 1) if not with_offset else f.forecast for f in out])


def cross_validate(traj: Trajectories, specs: Dict[str, Spec], *, folds: int = 5,
                   repeats: int = 5, seed: int = 0) -> Dict[str, np.ndarray]:
    """Out-of-fold predictions, shape (repeats, n, 6), for every learned model.

    Folds split participants, so nobody's T2 is ever seen while fitting the
    model that predicts it.
    """
    n = len(traj)
    if n < 2 * folds:
        raise ValueError(f"need at least {2 * folds} participants for {folds}-fold CV, have {n}")
    rng = np.random.default_rng(seed)
    out = {name: np.zeros((repeats, n, YEARS)) for name in specs}
    for r in range(repeats):
        order = rng.permutation(n)
        for f, test in enumerate(np.array_split(order, folds)):
            train = np.setdiff1d(order, test)
            for name, spec in specs.items():
                X, Y = design(traj, with_offset=spec.with_offset)
                model = spec.make(seed + 1000 * r + f).fit(X[train], Y[train])
                out[name][r, test] = model.predict(X[test])
    return out


def abs_errors(pred: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """Mean absolute error per participant, in percentage points, averaged over repeats."""
    pred = pred if pred.ndim == 3 else pred[None]
    return np.abs(pred - truth[None]).mean(axis=(0, 2)) * 100


def metrics(pred: np.ndarray, truth: np.ndarray) -> Dict[str, float]:
    pred = pred if pred.ndim == 3 else pred[None]
    diff = (pred - truth[None]) * 100
    return {
        "mae_pp": float(np.abs(diff).mean()),
        "rmse_pp": float(np.sqrt((diff**2).mean())),
        "mae_6y_pp": float(np.abs(diff[..., -1]).mean()),
        "mae_by_year_pp": np.abs(diff).mean(axis=(0, 1)).round(3).tolist(),
    }


def paired_difference(err_a: np.ndarray, err_b: np.ndarray, *, n_boot: int = 2000,
                      seed: int = 0) -> Dict[str, float]:
    """Mean of (a - b) per participant with a 95% bootstrap interval.

    Negative means a is more accurate than b. If the interval straddles 0, the
    data can't tell the two apart.
    """
    d = err_a - err_b
    rng = np.random.default_rng(seed)
    boots = d[rng.integers(0, len(d), (n_boot, len(d)))].mean(1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"mean": float(d.mean()), "lo": float(lo), "hi": float(hi),
            "a_better": int((d < 0).sum()), "n": int(len(d))}


def default_specs(hidden: int = 8, epochs: int = 500) -> Dict[str, Spec]:
    return {
        "linear, no offset (12)": Spec(False, lambda s: LinearRegression()),
        "linear + offset (13)": Spec(True, lambda s: LinearRegression()),
        f"MLP 12-{hidden}-6, no offset": Spec(False, lambda s: MLP(hidden, epochs, seed=s)),
        f"MLP 13-{hidden}-6 + offset": Spec(True, lambda s: MLP(hidden, epochs, seed=s)),
    }
