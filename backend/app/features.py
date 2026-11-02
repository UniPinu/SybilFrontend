"""What Sybil's encoder extracted from one scan, kept for the Features page.

Each of the five networks in the ensemble is a 3D ResNet-18 encoder, an
attention pooling step and a small risk head:

    volume (3, 200, 256, 256)
      -> image_encoder         (512, 25, 16, 16)   "encoder": the masked mean of this
      -> MultiAttentionPool    (512,)              "hidden": what the head reads
      -> ReLU -> hazard head   (6,) cumulative logits -> sigmoid -> calibration

Two vectors per network are stored for every scan:

  hidden    the pooled 512-d embedding, after the ReLU. The head is a function of
            this vector alone, so it is everything Sybil "knows" about the scan.
  encoder   the encoder's output averaged over the cells that hold the scan. No
            learned pooling; the padding Sybil adds around short scans is left
            out, because its size depends on the scan's length, not the person.

The five networks were trained separately, so their 512 dimensions do not
correspond to each other and are never averaged across models.

Files live in data/features/, outside the evictable patient cache, so a
feature vector survives even after the scan's images have been evicted:

    data/features/{exam_id}.npz   hidden, encoder, raw_per_model, risk_by_year
    data/features/heads.npz       the five risk heads' weights (exported once)

With the heads exported, `head_logits` re-runs Sybil's last layer in numpy,
so a feature vector that was never a real scan (a forecast, say) can still be
scored exactly as Sybil would have scored it.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from app.config import settings

log = logging.getLogger(__name__)

SPACES = ("hidden", "encoder")
N_MODELS = 5
DIM = 512
YEARS = 6
HEADS_FILE = "heads.npz"


def feature_dir() -> Path:
    return settings.data_dir / "features"


def _path(exam_id: str) -> Path:
    safe = exam_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    return feature_dir() / f"{safe}.npz"


# --- extraction ---------------------------------------------------------------
def _cells(offset: int, size: int, total: int, factor: int) -> slice:
    """The encoder cells (of `factor` voxels each) fully inside the scan.

    The scan occupies voxels [offset, offset + size) of the padded volume,
    clipped to [0, total). A cell half in the padding is left out; if that leaves
    nothing (a very short scan), every cell the scan touches is kept instead.
    """
    lo, hi = max(0, offset), min(total, offset + size)
    first, last = math.ceil(lo / factor), hi // factor
    if last <= first:
        first, last = lo // factor, math.ceil(hi / factor)
    return slice(first, max(last, first + 1))


def valid_cells(geometry) -> tuple[slice, slice, slice]:
    """(z, row, col) slices of the 25 x 16 x 16 encoder grid that hold real data."""
    from app.attention import MODEL_IMG_SIZE, MODEL_NUM_IMAGES, XY_FACTOR, Z_FACTOR

    return (
        _cells(geometry.z_offset, geometry.resampled_slices, MODEL_NUM_IMAGES, Z_FACTOR),
        _cells(geometry.row_offset, geometry.resampled_rows, MODEL_IMG_SIZE, XY_FACTOR),
        _cells(geometry.col_offset, geometry.resampled_cols, MODEL_IMG_SIZE, XY_FACTOR),
    )


def encoder_mean(activ, geometry) -> np.ndarray:
    """(512,) mean of the encoder output (1, 512, T, H, W) over the scan's cells."""
    a = activ.detach().cpu().numpy() if hasattr(activ, "detach") else np.asarray(activ)
    z, r, c = valid_cells(geometry)
    return a[0, :, z, r, c].reshape(a.shape[1], -1).mean(axis=1).astype(np.float32)


# --- storage ---------------------------------------------------------------
def save(exam_id: str, features: Dict[str, np.ndarray], *, raw_per_model, risk_by_year) -> Path:
    path = _path(exam_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez_compressed(
        tmp,
        **{k: np.asarray(v, dtype=np.float32) for k, v in features.items()},
        raw_per_model=np.asarray(raw_per_model, dtype=np.float64),
        risk_by_year=np.asarray(risk_by_year, dtype=np.float64),
        created_at=np.array(dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
    )
    tmp.replace(path)
    return path


def has(exam_id: str) -> bool:
    return _path(exam_id).exists()


def load(exam_id: str) -> Optional[Dict[str, np.ndarray]]:
    path = _path(exam_id)
    if not path.exists():
        return None
    with np.load(path) as f:
        return {k: f[k] for k in f.files}


def list_ids() -> List[str]:
    d = feature_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.npz")
                  if p.name != HEADS_FILE and not p.stem.endswith(".tmp"))


# --- the risk heads -------------------------------------------------------------
@dataclass(frozen=True)
class Heads:
    """Sybil's Cumulative_Probability_Layer for each of the five networks."""

    hazard_w: np.ndarray   # (5, 6, 512)
    hazard_b: np.ndarray   # (5, 6)
    base_w: np.ndarray     # (5, 512)
    base_b: np.ndarray     # (5,)


def export_heads(model) -> Heads:
    layers = [net.prob_of_failure_layer for net in model.ensemble]
    return Heads(
        hazard_w=np.stack([l.hazard_fc.weight.detach().cpu().numpy() for l in layers]),
        hazard_b=np.stack([l.hazard_fc.bias.detach().cpu().numpy() for l in layers]),
        base_w=np.stack([l.base_hazard_fc.weight.detach().cpu().numpy()[0] for l in layers]),
        base_b=np.stack([l.base_hazard_fc.bias.detach().cpu().numpy()[0] for l in layers]),
    )


def ensure_heads(model) -> None:
    """Write heads.npz once; the weights are pinned, so they never change."""
    path = feature_dir() / HEADS_FILE
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    h = export_heads(model)
    np.savez(path, hazard_w=h.hazard_w, hazard_b=h.hazard_b, base_w=h.base_w, base_b=h.base_b)
    load_heads.cache_clear()
    log.info("exported the risk heads to %s", path)


@lru_cache(maxsize=1)
def load_heads() -> Optional[Heads]:
    path = feature_dir() / HEADS_FILE
    if not path.exists():
        return None
    with np.load(path) as f:
        return Heads(f["hazard_w"], f["hazard_b"], f["base_w"], f["base_b"])


def head_logits(heads: Heads, hidden: np.ndarray) -> np.ndarray:
    """Cumulative logits (..., 5, 6) from hidden features (..., 5, 512).

    Mirrors Cumulative_Probability_Layer.forward: year y's logit is the base
    hazard plus the sum of the ReLU'd hazards of years 1..y.
    """
    h = np.asarray(hidden, dtype=np.float64)
    hazards = np.maximum(np.einsum("mtd,...md->...mt", heads.hazard_w, h) + heads.hazard_b, 0.0)
    base = np.einsum("md,...md->...m", heads.base_w, h) + heads.base_b
    return np.cumsum(hazards, axis=-1) + base[..., None]


def risk_gradient(heads: Heads, hidden: np.ndarray, year: int = YEARS) -> np.ndarray:
    """d(year-`year` cumulative logit) / d(hidden), per model: (..., 5, 512).

    The head is piecewise linear, so this is exact everywhere except on the
    ReLU's kinks: the base direction plus every hazard that is switched on.
    """
    h = np.asarray(hidden, dtype=np.float64)
    pre = np.einsum("mtd,...md->...mt", heads.hazard_w, h) + heads.hazard_b
    on = (pre[..., :year] > 0).astype(np.float64)
    return heads.base_w + np.einsum("...mt,mtd->...md", on, heads.hazard_w[:, :year])


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=np.float64)))


@lru_cache(maxsize=1)
def _calibrator():
    from sybil.models.calibrator import SimpleClassifierGroup

    path = settings.sybil_cache / f"{settings.model_name}_simple_calibrator.json"
    return SimpleClassifierGroup.from_json_grouped(str(path)) if path.exists() else None


def calibrate(raw_mean: np.ndarray) -> Optional[np.ndarray]:
    """Sybil's per-year isotonic calibration of the ensemble mean, (n, 6) -> (n, 6)."""
    cal = _calibrator()
    if cal is None:
        return None
    raw = np.atleast_2d(np.asarray(raw_mean, dtype=np.float64))
    return np.stack([cal[f"Year{y + 1}"].predict_proba(raw[:, y].reshape(-1, 1))[:, -1]
                     for y in range(raw.shape[1])], axis=1)


def score(heads: Heads, hidden: np.ndarray) -> Dict[str, Any]:
    """Score hidden features (n, 5, 512) the way Sybil would: raw per model, mean, calibrated."""
    raw = sigmoid(head_logits(heads, hidden))          # (n, 5, 6)
    mean = raw.mean(axis=-2)
    return {"raw_per_model": raw, "raw_mean": mean, "calibrated": calibrate(mean)}
