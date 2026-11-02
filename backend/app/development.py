"""How Sybil's features change across a participant's screening rounds.

Sybil scores one scan at a time and remembers nothing. This module takes the
vectors it extracted (app/features.py) and looks only at how *they* move from
T0 to T1 to T2; nothing here is trained on outcomes.

Everything is computed in one feature space at a time:

  space   "hidden" (what the risk head reads) or "encoder" (the encoder's mean)
  model   1..5 for one network, or None for all five side by side. The networks
          were trained separately, so their dimensions are only ever
          concatenated, never averaged.

Units. Each dimension is standardized over every scan with features (dims that
are almost never active are dropped), and the distance between two scans is
the root-mean-square of their standardized differences. Two unrelated scans are
then about sqrt(2) ~ 1.41 apart by construction; 0 means identical.

Sections (all deterministic):
  map        PCA of every scan, each participant's rounds joined in order
  stability  within-person changes vs between-person differences, and whether
             a person's later scan picks their own earlier one out of everyone's
  drift      how much of the average change is shared by everyone (scanner
             upgrades, ageing) rather than individual
  visibility the share of a change, in the network's own units, along the one
             direction that moves its 6-year score (hidden space only)
  groups     change per year by diagnosis and by whether the acquisition changed
  forecast   T2's features from T0's and T1's, scored by Sybil's own head
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app import data
from app import features as F
from app import participants as explore

MIN_ACTIVE = 0.10      # a dimension must be non-zero in at least 10% of scans
MIN_SCANS = 4          # below this, standardization and PCA mean nothing
TOP_FEATURES = 20
PAIRS = ((0, 1), (1, 2), (0, 2))
HIST_BINS = np.round(np.arange(0.0, 2.01, 0.1), 2)
PERMUTATIONS = 5000
SEED = 20261102


class NoFeatures(LookupError):
    """The participant has no scan with features yet."""


class BadRequest(ValueError):
    pass


def _r(x, digits: int = 4):
    if x is None:
        return None
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_r(v, digits) for v in x]
    x = float(x)
    return None if not math.isfinite(x) else round(x, digits)


def check_args(space: str, model: Optional[int]) -> None:
    if space not in F.SPACES:
        raise BadRequest(f"space must be one of {', '.join(F.SPACES)}")
    if model is not None and not 1 <= model <= F.N_MODELS:
        raise BadRequest(f"model must be 1..{F.N_MODELS}, or omitted for all five")


# --- the data -------------------------------------------------------------------
@dataclass
class Dataset:
    exam_ids: List[str]
    pids: List[str]
    rounds: np.ndarray            # (n,) 0, 1, 2
    years: np.ndarray             # (n,) years since randomization
    raw: Dict[str, np.ndarray]    # space -> (n, 5, 512)
    risk: np.ndarray              # (n, 6) Sybil's calibrated risks
    acquisition: List[dict]       # manufacturer, kernel, thickness per scan
    diagnosed: Dict[str, Optional[bool]]
    years_to_dx: Dict[str, Optional[float]]

    def __len__(self) -> int:
        return len(self.exam_ids)

    def scans_of(self, pid: str) -> Dict[int, int]:
        """round -> row index for one participant."""
        return {int(self.rounds[i]): i for i, p in enumerate(self.pids) if p == pid}

    @property
    def by_participant(self) -> Dict[str, Dict[int, int]]:
        out: Dict[str, Dict[int, int]] = {}
        for i, p in enumerate(self.pids):
            out.setdefault(p, {})[int(self.rounds[i])] = i
        return out


def _signature() -> Tuple[Any, ...]:
    ids = F.list_ids()
    d = F.feature_dir()
    latest = max((p.stat().st_mtime for p in d.glob("*.npz")), default=0.0) if d.exists() else 0.0
    return (tuple(ids), latest)


def dataset() -> Dataset:
    return _dataset(_signature())


@lru_cache(maxsize=2)
def _dataset(signature) -> Dataset:
    ids = list(signature[0])
    exams = data.exams()
    people = explore.table() if explore.have_participants() else None
    meta = exams.set_index("patient_id") if exams is not None else None
    rows = []
    for exam_id in ids:
        if meta is None or exam_id not in meta.index:
            continue  # the offline demo scan has no participant
        f = F.load(exam_id)
        if f is None or not all(s in f for s in F.SPACES):
            continue
        rows.append((exam_id, meta.loc[exam_id], f))
    return build_dataset(rows, people)


def build_dataset(rows, people) -> Dataset:
    """rows: (exam_id, exam row with nlst_pid/study_yr/days_since_rand/..., feature dict)."""
    rows = sorted(rows, key=lambda r: (str(r[1]["nlst_pid"]), int(r[1]["study_yr"])))
    pids = [str(r[1]["nlst_pid"]) for r in rows]
    diagnosed, to_dx = {}, {}
    for pid in set(pids):
        row = people.loc[pid] if people is not None and pid in people.index else None
        diagnosed[pid] = None if row is None else bool(row.get("diagnosed"))
        dx = None if row is None else row.get("years_rand_to_dx")
        to_dx[pid] = None if dx is None or (isinstance(dx, float) and math.isnan(dx)) else float(dx)

    def num(v) -> Optional[float]:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(v) else v

    return Dataset(
        exam_ids=[r[0] for r in rows],
        pids=pids,
        rounds=np.array([int(r[1]["study_yr"]) for r in rows], dtype=int),
        years=np.array([(num(r[1].get("days_since_rand")) or np.nan) / 365.25 for r in rows]),
        raw={s: np.stack([r[2][s] for r in rows]).astype(np.float64) if rows
             else np.zeros((0, F.N_MODELS, F.DIM)) for s in F.SPACES},
        risk=np.stack([r[2]["risk_by_year"] for r in rows]) if rows else np.zeros((0, F.YEARS)),
        acquisition=[{"manufacturer": r[1].get("manufacturer"), "kernel": r[1].get("kernel"),
                      "thickness_mm": num(r[1].get("thickness_mm"))} for r in rows],
        diagnosed=diagnosed,
        years_to_dx=to_dx,
    )


# --- one feature space ----------------------------------------------------------
@dataclass
class Space:
    """The selected features of every scan, standardized."""

    name: str
    model: Optional[int]
    columns: np.ndarray       # indices into the flattened (5 * 512) vector that are kept
    mean: np.ndarray
    sd: np.ndarray
    z: np.ndarray             # (n, d)

    def standardize(self, flat: np.ndarray) -> np.ndarray:
        return (flat[..., self.columns] - self.mean) / self.sd

    def label(self, j: int) -> str:
        col = int(self.columns[j])
        return f"N{col // F.DIM + 1}·{col % F.DIM}"


def _flat(ds: Dataset, space: str) -> np.ndarray:
    return ds.raw[space].reshape(len(ds), -1)


def select(ds: Dataset, space: str, model: Optional[int]) -> Space:
    flat = _flat(ds, space)
    cols = np.arange(flat.shape[1])
    if model is not None:
        cols = cols[(cols // F.DIM) == model - 1]
    x = flat[:, cols]
    sd = x.std(axis=0)
    active = (x > 0).mean(axis=0) if len(x) else np.zeros(len(cols))
    keep = (sd > 1e-8) & (active >= MIN_ACTIVE)
    cols, x, sd = cols[keep], x[:, keep], sd[keep]
    mean = x.mean(axis=0)
    return Space(space, model, cols, mean, sd, (x - mean) / sd)


def rms(a: np.ndarray, axis=-1) -> np.ndarray:
    return np.sqrt(np.mean(np.square(a), axis=axis))


def distances(z: np.ndarray) -> np.ndarray:
    """(n, n) RMS standardized distance between every pair of scans."""
    sq = np.square(z).sum(1)
    d2 = np.maximum(sq[:, None] + sq[None, :] - 2 * z @ z.T, 0.0)
    return np.sqrt(d2 / max(z.shape[1], 1))


def pca(z: np.ndarray, k: int = 2) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scores (n, k), explained-variance ratios (k,), components (k, d), signs fixed."""
    if len(z) < 2:
        return np.zeros((len(z), k)), np.zeros(k), np.zeros((k, z.shape[1]))
    u, s, vt = np.linalg.svd(z - z.mean(0), full_matrices=False)
    k = min(k, len(s))
    vt = vt[:k]
    flip = np.sign(vt[np.arange(k), np.abs(vt).argmax(1)])
    vt = vt * flip[:, None]
    var = s ** 2
    return (z - z.mean(0)) @ vt.T, var[:k] / var.sum(), vt


# --- the sections ---------------------------------------------------------------
def _pairs(ds: Dataset) -> List[Tuple[str, int, int, int, int]]:
    """(pid, round a, round b, row a, row b) for every pair of a person's rounds."""
    out = []
    for pid, scans in ds.by_participant.items():
        for a, b in PAIRS:
            if a in scans and b in scans:
                out.append((pid, a, b, scans[a], scans[b]))
    return out


def _acq_changed(ds: Dataset, i: int, j: int) -> bool:
    x, y = ds.acquisition[i], ds.acquisition[j]
    return x["manufacturer"] != y["manufacturer"] or x["kernel"] != y["kernel"]


def _between(ds: Dataset, D: np.ndarray, a: int, b: int) -> np.ndarray:
    """Distances between round a of one person and round b of *another*."""
    ia, ib = np.where(ds.rounds == a)[0], np.where(ds.rounds == b)[0]
    pids = np.array(ds.pids)
    block = D[np.ix_(ia, ib)]
    other = pids[ia][:, None] != pids[ib][None, :]
    if a == b:
        other &= np.triu(np.ones_like(other, dtype=bool), 1)
    return block[other]


def _quantiles(x: np.ndarray) -> Optional[Dict[str, float]]:
    if len(x) == 0:
        return None
    q = np.quantile(x, [0.05, 0.25, 0.5, 0.75, 0.95])
    return {"n": int(len(x)), "p5": _r(q[0]), "p25": _r(q[1]), "median": _r(q[2]),
            "p75": _r(q[3]), "p95": _r(q[4]), "mean": _r(x.mean())}


def _hist(x: np.ndarray) -> List[float]:
    """Share of values in each HIST_BINS bin; the last bin takes everything above."""
    if len(x) == 0:
        return [0.0] * (len(HIST_BINS) - 1)
    clipped = np.clip(x, HIST_BINS[0], HIST_BINS[-1] - 1e-9)
    counts, _ = np.histogram(clipped, bins=HIST_BINS)
    return _r(counts / len(x))


def _reidentify(ds: Dataset, D: np.ndarray, a: int, b: int) -> Optional[Dict[str, Any]]:
    """Does each person's round-b scan pick their own round-a scan out of all round-a scans?"""
    gallery = np.where(ds.rounds == a)[0]
    pids = np.array(ds.pids)
    ranks = []
    for pid, scans in ds.by_participant.items():
        if a in scans and b in scans:
            d = D[scans[b], gallery]
            ranks.append(1 + int((d < D[scans[b], scans[a]]).sum()))
    if not ranks:
        return None
    ranks = np.array(ranks)
    return {"queries": int(len(ranks)), "gallery": int(len(gallery)),
            "top1": _r((ranks == 1).mean()), "chance": _r(1 / len(gallery)),
            "median_rank": _r(np.median(ranks), 1),
            "gallery_people": int(len(set(pids[gallery])))}


def _visibility(ds: Dataset, heads: Optional[F.Heads], i: int, j: int) -> Optional[Dict[str, float]]:
    """How much of the change from scan i to scan j moves Sybil's 6-year score."""
    if heads is None:
        return None
    h0, h1 = ds.raw["hidden"][i], ds.raw["hidden"][j]
    delta = h1 - h0
    g = 0.5 * (F.risk_gradient(heads, h0) + F.risk_gradient(heads, h1))   # (5, 512)
    num = np.square((g * delta).sum(-1))
    den = np.square(g).sum(-1) * np.square(delta).sum(-1)
    share = np.where(den > 0, num / np.maximum(den, 1e-30), 0.0)
    active = ((h0 > 0) | (h1 > 0)).sum(-1)
    logits = F.head_logits(heads, np.stack([h0, h1]))[:, :, -1]          # (2, 5)
    return {"share": float(share.mean()),
            "random_share": float(np.mean(1.0 / np.maximum(active, 1))),
            "delta_logit_6y": float((logits[1] - logits[0]).mean())}


def _pair_rows(ds: Dataset, sp: Space, D: np.ndarray, heads) -> List[Dict[str, Any]]:
    between = {(a, b): np.sort(_between(ds, D, a, b)) for a, b in PAIRS}
    rows = []
    for pid, a, b, i, j in _pairs(ds):
        gap = float(ds.years[j] - ds.years[i])
        dist = float(D[i, j])
        ref = between[(a, b)]
        vis = _visibility(ds, heads, i, j) if sp.name == "hidden" else None
        rows.append({
            "nlst_pid": pid, "from": f"T{a}", "to": f"T{b}", "rows": (i, j),
            "years_apart": _r(gap, 3),
            "distance": _r(dist),
            "per_year": _r(dist / gap) if gap > 0 else None,
            # share of different-person pairs that are *closer* than this change
            "percentile_vs_between": _r(np.searchsorted(ref, dist) / len(ref)) if len(ref) else None,
            "acquisition_changed": _acq_changed(ds, i, j),
            "risk_visible_share": _r(vis["share"]) if vis else None,
            "random_share": _r(vis["random_share"]) if vis else None,
            "delta_logit_6y": _r(vis["delta_logit_6y"]) if vis else None,
            "delta_risk_6y": _r(ds.risk[j, -1] - ds.risk[i, -1], 6),
        })
    return rows


def _perm_test(x: np.ndarray, y: np.ndarray) -> Optional[Dict[str, Any]]:
    """Difference in means, two-sided permutation p-value (seeded)."""
    if len(x) < 2 or len(y) < 2:
        return None
    rng = np.random.default_rng(SEED)
    both = np.concatenate([x, y])
    obs = x.mean() - y.mean()
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(both)
        hits += abs(both[:len(x)].mean() - both[len(x):].mean()) >= abs(obs) - 1e-12
    return {"difference": _r(obs), "p_value": _r((hits + 1) / (PERMUTATIONS + 1), 4)}


def _group(rows: List[dict], key, labels: Tuple[str, str]) -> Dict[str, Any]:
    yes = np.array([r["per_year"] for r in rows if key(r) is True and r["per_year"] is not None])
    no = np.array([r["per_year"] for r in rows if key(r) is False and r["per_year"] is not None])
    return {"labels": list(labels),
            "yes": _quantiles(yes), "no": _quantiles(no),
            "test": _perm_test(yes, no)}


# --- the forecast -----------------------------------------------------------------
METHODS = {
    "persistence": "T2 = T1 (no change)",
    "drift": "T1 + everyone else's average T1→T2 change",
    "linear": "T1 + the T0→T1 change, scaled to T2's date",
    "damped": "T1 + α × the T0→T1 change, α fitted on everyone else",
}


def forecast_features(ds: Dataset, space: str) -> Optional[Dict[str, Any]]:
    """Predict every 3-round participant's T2 vector, leaving them out of anything fitted."""
    trios = [(pid, s[0], s[1], s[2]) for pid, s in ds.by_participant.items()
             if all(r in s for r in (0, 1, 2))
             and np.isfinite(ds.years[[s[0], s[1], s[2]]]).all() and ds.years[s[1]] > ds.years[s[0]]]
    if len(trios) < 3:
        return None
    X = ds.raw[space]
    h0 = np.stack([X[t[1]] for t in trios])
    h1 = np.stack([X[t[2]] for t in trios])
    h2 = np.stack([X[t[3]] for t in trios])
    y = ds.years
    ratio = np.array([(y[t[3]] - y[t[2]]) / max(y[t[2]] - y[t[1]], 1e-6) for t in trios])
    step = (h1 - h0) * ratio[:, None, None]
    change = h2 - h1
    n = len(trios)
    preds = {"persistence": h1.copy(), "linear": h1 + step}
    drift, damped, alphas = np.empty_like(h1), np.empty_like(h1), []
    for k in range(n):
        others = np.arange(n) != k
        drift[k] = h1[k] + change[others].mean(0)
        a = float((step[others] * change[others]).sum() / max(np.square(step[others]).sum(), 1e-30))
        alphas.append(a)
        damped[k] = h1[k] + a * step[k]
    preds["drift"], preds["damped"] = drift, damped
    # both spaces are means of ReLU outputs, so a forecast below zero is impossible
    preds = {m: np.maximum(p, 0.0) for m, p in preds.items()}
    return {"pids": [t[0] for t in trios], "rows": [t[1:] for t in trios], "truth": h2,
            "preds": preds, "alpha": float(np.mean(alphas))}


def _forecast_block(ds: Dataset, sp: Space, heads) -> Optional[Dict[str, Any]]:
    fc = forecast_features(ds, sp.name)
    if fc is None:
        return None
    n = len(fc["pids"])
    truth_z = sp.standardize(fc["truth"].reshape(n, -1))
    t2_rows = [r[2] for r in fc["rows"]]
    sybil_t2 = ds.risk[t2_rows]
    out = {"n": n, "alpha": _r(fc["alpha"]), "methods": []}
    for name, pred in fc["preds"].items():
        err = rms(sp.standardize(pred.reshape(n, -1)) - truth_z)
        row = {"method": name, "description": METHODS[name], "rms_error": _quantiles(err),
               "risk_mae_pp": None}
        if sp.name == "hidden" and heads is not None:
            scored = F.score(heads, pred)["calibrated"]
            if scored is not None:
                row["risk_mae_pp"] = _r(np.abs(scored - sybil_t2).mean() * 100, 3)
        out["methods"].append(row)
    return out


# --- the two payloads -----------------------------------------------------------------
def _heads_for(space: str) -> Optional[F.Heads]:
    return F.load_heads() if space == "hidden" else None


def _counts(ds: Dataset) -> Dict[str, Any]:
    per = [len(s) for s in ds.by_participant.values()]
    return {"scans": len(ds), "participants": len(per),
            "with_2_rounds": sum(n >= 2 for n in per), "with_3_rounds": sum(n >= 3 for n in per),
            "diagnosed": sum(bool(ds.diagnosed.get(p)) for p in ds.by_participant)}


def overview(space: str = "hidden", model: Optional[int] = None) -> Dict[str, Any]:
    check_args(space, model)
    return _overview(_signature(), space, model)


@lru_cache(maxsize=16)
def _overview(signature, space: str, model: Optional[int]) -> Dict[str, Any]:
    ds = _dataset(signature)
    out: Dict[str, Any] = {
        "space": space, "model": model, "counts": _counts(ds),
        "heads_available": F.load_heads() is not None, "min_scans": MIN_SCANS,
        "dims": None, "map": None, "stability": None, "drift": None,
        "visibility": None, "groups": None, "forecast": None, "pairs": [],
        "participants": [{"nlst_pid": pid, "rounds": sorted(s),
                          "diagnosed": ds.diagnosed.get(pid),
                          "years_rand_to_dx": _r(ds.years_to_dx.get(pid), 2)}
                         for pid, s in ds.by_participant.items()],
        "hist_bins": HIST_BINS.tolist(),
    }
    if len(ds) < MIN_SCANS:
        return out
    sp = select(ds, space, model)
    total = F.N_MODELS * F.DIM if model is None else F.DIM
    out["dims"] = {"kept": int(len(sp.columns)), "total": total, "min_active": MIN_ACTIVE}
    D = distances(sp.z)
    scores, explained, _ = pca(sp.z)
    out["map"] = {
        "explained": _r(explained),
        "points": [{"nlst_pid": ds.pids[i], "round": f"T{ds.rounds[i]}",
                    "x": _r(scores[i, 0]), "y": _r(scores[i, 1]),
                    "diagnosed": ds.diagnosed.get(ds.pids[i])} for i in range(len(ds))],
    }
    heads = _heads_for(space)
    rows = _pair_rows(ds, sp, D, heads)
    out["pairs"] = [{k: v for k, v in r.items() if k != "rows"} for r in rows]

    stability = {"pairs": []}
    for a, b in PAIRS:
        within = np.array([r["distance"] for r in rows if (r["from"], r["to"]) == (f"T{a}", f"T{b}")])
        between = _between(ds, D, a, b)
        stability["pairs"].append({
            "from": f"T{a}", "to": f"T{b}",
            "within": _quantiles(within), "between": _quantiles(between),
            "within_hist": _hist(within), "between_hist": _hist(between),
            "reidentification": _reidentify(ds, D, a, b),
        })
    out["stability"] = stability

    drift = []
    for a, b in PAIRS:
        sel = [r["rows"] for r in rows if (r["from"], r["to"]) == (f"T{a}", f"T{b}")]
        if len(sel) < 2:
            continue
        delta = np.stack([sp.z[j] - sp.z[i] for i, j in sel])
        shared = float(np.square(delta.mean(0)).sum() / np.square(delta).sum(1).mean())
        drift.append({"from": f"T{a}", "to": f"T{b}", "n": len(sel),
                      "shared_share": _r(shared), "mean_change": _r(rms(delta).mean()),
                      "shared_change": _r(rms(delta.mean(0)))})
    out["drift"] = drift

    if space == "hidden" and heads is not None:
        shares = np.array([r["risk_visible_share"] for r in rows])
        randoms = np.array([r["random_share"] for r in rows])
        if len(shares):
            out["visibility"] = {"share": _quantiles(shares), "random_share": _quantiles(randoms),
                                 "times_random_median": _r(np.median(shares / np.maximum(randoms, 1e-12)), 2)}

    consecutive = [r for r in rows if r["from"] != "T0" or r["to"] != "T2"]
    out["groups"] = {
        "diagnosis": _group(consecutive, lambda r: ds.diagnosed.get(r["nlst_pid"]),
                            ("diagnosed", "not diagnosed")),
        "acquisition": _group(consecutive, lambda r: r["acquisition_changed"],
                              ("scanner or kernel changed", "same scanner and kernel")),
    }
    out["forecast"] = _forecast_block(ds, sp, heads)
    return out


def participant(nlst_pid: str, space: str = "hidden", model: Optional[int] = None) -> Dict[str, Any]:
    check_args(space, model)
    ds = dataset()
    scans = ds.scans_of(nlst_pid)
    if not scans:
        raise NoFeatures(f"Participant {nlst_pid} has no scan with features yet. Run "
                         "scripts/build_features.py, or run their rounds in Explore.")
    if len(ds) < MIN_SCANS:
        raise NoFeatures(f"Only {len(ds)} scans have features; at least {MIN_SCANS} are "
                         "needed to standardize them.")
    sp = select(ds, space, model)
    D = distances(sp.z)
    scores, _, _ = pca(sp.z)
    heads = _heads_for(space)
    order = sorted(scans)
    idx = [scans[r] for r in order]

    pair_rows = [r for r in _pair_rows(ds, sp, D, heads) if r["nlst_pid"] == nlst_pid]

    # the dimensions that moved most between consecutive rounds
    z = sp.z[idx]
    steps = np.abs(np.diff(z, axis=0)).max(0) if len(idx) > 1 else np.abs(z[0])
    top = np.argsort(-steps)[:TOP_FEATURES]
    weights = None
    if heads is not None:
        g = F.risk_gradient(heads, ds.raw["hidden"][idx]).mean(0).reshape(-1)  # (2560,)
        weights = g[sp.columns] * sp.sd       # 6-year logit per +1 SD
    flat = _flat(ds, space)
    top_rows = [{
        "label": sp.label(int(j)),
        "network": int(sp.columns[j] // F.DIM) + 1,
        "index": int(sp.columns[j] % F.DIM),
        "z": _r(z[:, j], 3),
        "raw": _r(flat[idx, sp.columns[j]], 4),
        "risk_weight": _r(weights[j]) if weights is not None else None,
    } for j in top]

    fc_block = None
    fc = forecast_features(ds, space)
    if fc is not None and nlst_pid in fc["pids"]:
        k = fc["pids"].index(nlst_pid)
        truth_z = sp.standardize(fc["truth"][k].reshape(-1))
        fc_block = {"alpha": _r(fc["alpha"]), "sybil_t2": _r(ds.risk[idx[-1]], 6), "methods": []}
        for name, pred in fc["preds"].items():
            row = {"method": name, "description": METHODS[name],
                   "rms_error": _r(rms(sp.standardize(pred[k].reshape(-1)) - truth_z)),
                   "risk_by_year": None}
            if heads is not None:
                cal = F.score(heads, pred[k][None])["calibrated"]
                row["risk_by_year"] = _r(cal[0], 6) if cal is not None else None
            fc_block["methods"].append(row)

    outcome = {"diagnosed": ds.diagnosed.get(nlst_pid),
               "years_rand_to_dx": _r(ds.years_to_dx.get(nlst_pid), 2)}
    return {
        "nlst_pid": nlst_pid, "space": space, "model": model,
        "outcome": outcome,
        "rounds": [{"round": f"T{r}", "exam_id": ds.exam_ids[i], "years": _r(ds.years[i], 3),
                    "risk_by_year": _r(ds.risk[i], 6), "acquisition": ds.acquisition[i],
                    "x": _r(scores[i, 0]), "y": _r(scores[i, 1]),
                    "active_share": _r((ds.raw[space][i] > 0).mean(), 3)}
                   for r, i in zip(order, idx)],
        "pairs": [{k: v for k, v in r.items() if k != "rows"} for r in pair_rows],
        "top_features": top_rows,
        "forecast": fc_block,
    }


def export_csv(space: str = "hidden", model: Optional[int] = None) -> str:
    """Every scan's raw features, one row per scan, for analysis elsewhere."""
    check_args(space, model)
    ds = dataset()
    flat = _flat(ds, space)
    cols = np.arange(flat.shape[1])
    if model is not None:
        cols = cols[(cols // F.DIM) == model - 1]
    head = ["nlst_pid", "exam_id", "round", "years_since_randomization", "diagnosed",
            "manufacturer", "kernel", "sybil_risk_6y"] + [f"n{c // F.DIM + 1}_{c % F.DIM}" for c in cols]
    lines = [",".join(head)]
    for i in range(len(ds)):
        acq = ds.acquisition[i]
        dx = ds.diagnosed.get(ds.pids[i])
        lines.append(",".join([ds.pids[i], ds.exam_ids[i], f"T{ds.rounds[i]}",
                               f"{ds.years[i]:.3f}", "" if dx is None else str(int(dx)),
                               str(acq["manufacturer"] or ""), str(acq["kernel"] or ""),
                               f"{ds.risk[i, -1]:.6f}"]
                              + [f"{v:.6g}" for v in flat[i, cols]]))
    return "\n".join(lines) + "\n"


def participants_with_features() -> Sequence[str]:
    return list(dataset().by_participant)
