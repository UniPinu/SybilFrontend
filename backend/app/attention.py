"""Mapping Sybil's attention back onto the original CT slices.

MVP.md section 6.4 flagged this as the one piece of upstream code we should not
trust blindly, and it was right. `sybil.utils.visualization.collate_attentions`
stretches the 25x16x16 attention grid linearly over the *original* N x 512 x 512
slices. But the model never saw those slices: `Serie.get_volume()` first resizes
each slice to 256x256, resamples the volume to 0.703125 x 0.703125 x 2.5 mm, and
then centre-pads/crops it to exactly 256 x 256 x 200. A typical 150-slice 2.5 mm
scan therefore occupies slots 25..174 of the 200, and the upstream overlay is
both shifted (~25 slots, i.e. ~62 mm) and stretched (200/150) in z.

So we invert the real chain instead. Every step is an axis-aligned affine map in
index space, so composing them is exact:

  1. cv2.resize  512 -> 256          half-pixel convention
  2. tio.Resample to VOXEL_SPACING   new = (old + .5) * (old_sp/new_sp) - .5,
                                     size = ceil(size * old_sp / new_sp)
  3. tio.CropOrPad to (256,256,200)  index shift of +/- ceil(diff / 2)
  4. attention pooling               8x in z, 16x in-plane, align_corners=False

Steps 2 and 3 are verified against torchio 0.18.74 itself in
tests/test_attention_alignment.py, including the odd-difference split.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Tuple

import numpy as np
import torch
import torch.nn.functional as F

# sybil.datasets.utils.VOXEL_SPACING and the Serie args at main@d9fc81b
VOXEL_SPACING: Tuple[float, float, float] = (0.703125, 0.703125, 2.5)
MODEL_IMG_SIZE = 256
MODEL_NUM_IMAGES = 200

# r3d_18 downsampling between the padded volume and the attention grid:
# 200/25 in z, 256/16 in plane.
ATT_Z, ATT_H, ATT_W = 25, 16, 16
Z_FACTOR = MODEL_NUM_IMAGES // ATT_Z   # 8
XY_FACTOR = MODEL_IMG_SIZE // ATT_H    # 16


@dataclass(frozen=True)
class Affine1D:
    """y = scale * x + shift, in index space."""

    scale: float
    shift: float

    def apply(self, x):
        return self.scale * x + self.shift

    def then(self, other: "Affine1D") -> "Affine1D":
        return Affine1D(other.scale * self.scale, other.scale * self.shift + other.shift)

    def inverse(self) -> "Affine1D":
        return Affine1D(1.0 / self.scale, -self.shift / self.scale)

    @staticmethod
    def identity() -> "Affine1D":
        return Affine1D(1.0, 0.0)

    @staticmethod
    def rescale(source_spacing: float, target_spacing: float) -> "Affine1D":
        """Half-pixel (align_corners=False) resampling: (x + .5) * s - .5."""
        s = source_spacing / target_spacing
        return Affine1D(s, 0.5 * s - 0.5)

    @staticmethod
    def resize(source_size: int, target_size: int) -> "Affine1D":
        """cv2.resize / F.interpolate index mapping for a size change.

        Index scale is target/source -- the inverse of the spacing change, which
        is why this is not `rescale(source_size, target_size)`.
        """
        return Affine1D.rescale(float(target_size), float(source_size))

    @staticmethod
    def shift_by(offset: int) -> "Affine1D":
        return Affine1D(1.0, float(offset))

    @staticmethod
    def pool(factor: int) -> "Affine1D":
        """Index of the pooled cell a voxel falls in (align_corners=False)."""
        return Affine1D(1.0 / factor, 0.5 / factor - 0.5)


def resampled_size(size: int, source_spacing: float, target_spacing: float) -> int:
    """torchio's Resample output size: ceil(size * source / target)."""
    return int(math.ceil(size * source_spacing / target_spacing))


def crop_or_pad_offset(source: int, target: int) -> int:
    """Index shift applied by `tio.CropOrPad` (new_index = old_index + offset).

    torchio puts the larger half on the *initial* side: ceil(diff / 2). Verified
    against torchio 0.18.74 for odd and even differences.
    """
    diff = target - source
    if diff > 0:
        return int(math.ceil(diff / 2))
    if diff < 0:
        return -int(math.ceil(-diff / 2))
    return 0


@dataclass(frozen=True)
class VolumeGeometry:
    """Everything needed to move between original slices and attention cells."""

    n_slices: int
    rows: int
    cols: int
    thickness_mm: float
    row_spacing_mm: float
    col_spacing_mm: float

    # --- derived sizes ---------------------------------------------------
    @property
    def resampled_rows(self) -> int:
        return resampled_size(MODEL_IMG_SIZE, self.row_spacing_mm, VOXEL_SPACING[0])

    @property
    def resampled_cols(self) -> int:
        return resampled_size(MODEL_IMG_SIZE, self.col_spacing_mm, VOXEL_SPACING[1])

    @property
    def resampled_slices(self) -> int:
        return resampled_size(self.n_slices, self.thickness_mm, VOXEL_SPACING[2])

    @property
    def z_offset(self) -> int:
        return crop_or_pad_offset(self.resampled_slices, MODEL_NUM_IMAGES)

    @property
    def row_offset(self) -> int:
        return crop_or_pad_offset(self.resampled_rows, MODEL_IMG_SIZE)

    @property
    def col_offset(self) -> int:
        return crop_or_pad_offset(self.resampled_cols, MODEL_IMG_SIZE)

    # --- original index -> padded model volume index ---------------------
    @property
    def z_to_volume(self) -> Affine1D:
        return Affine1D.rescale(self.thickness_mm, VOXEL_SPACING[2]).then(
            Affine1D.shift_by(self.z_offset)
        )

    @property
    def row_to_volume(self) -> Affine1D:
        return (
            Affine1D.resize(self.rows, MODEL_IMG_SIZE)
            .then(Affine1D.rescale(self.row_spacing_mm, VOXEL_SPACING[0]))
            .then(Affine1D.shift_by(self.row_offset))
        )

    @property
    def col_to_volume(self) -> Affine1D:
        return (
            Affine1D.resize(self.cols, MODEL_IMG_SIZE)
            .then(Affine1D.rescale(self.col_spacing_mm, VOXEL_SPACING[1]))
            .then(Affine1D.shift_by(self.col_offset))
        )

    # --- original index -> attention grid coordinate ---------------------
    @property
    def z_to_attention(self) -> Affine1D:
        return self.z_to_volume.then(Affine1D.pool(Z_FACTOR))

    @property
    def row_to_attention(self) -> Affine1D:
        return self.row_to_volume.then(Affine1D.pool(XY_FACTOR))

    @property
    def col_to_attention(self) -> Affine1D:
        return self.col_to_volume.then(Affine1D.pool(XY_FACTOR))

    # --- reporting -------------------------------------------------------
    @property
    def slices_in_model_view(self) -> int:
        """How many original slices actually reached the network."""
        zs = self.z_to_volume
        return sum(1 for i in range(self.n_slices)
                   if -0.5 <= zs.apply(i) <= MODEL_NUM_IMAGES - 0.5)

    def as_dict(self) -> dict:
        return {
            "n_slices": self.n_slices,
            "rows": self.rows,
            "cols": self.cols,
            "thickness_mm": self.thickness_mm,
            "pixel_spacing_mm": [self.row_spacing_mm, self.col_spacing_mm],
            "resampled_shape": [self.resampled_rows, self.resampled_cols, self.resampled_slices],
            "crop_or_pad_offset": [self.row_offset, self.col_offset, self.z_offset],
            "slices_in_model_view": self.slices_in_model_view,
            "z_cropped": self.resampled_slices > MODEL_NUM_IMAGES,
            "z_padded": self.resampled_slices < MODEL_NUM_IMAGES,
        }

    @classmethod
    def from_serie(cls, serie: Any, rows: int, cols: int) -> "VolumeGeometry":
        meta = serie._meta  # Serie exposes no public accessor; the commit is pinned
        row_spacing, col_spacing = (list(meta.pixel_spacing) + [None, None])[:2]
        return cls(
            n_slices=len(meta.paths),
            rows=rows,
            cols=cols,
            thickness_mm=float(meta.thickness),
            row_spacing_mm=float(row_spacing),
            col_spacing_mm=float(col_spacing),
        )


# ---------------------------------------------------------------------------
# attention grid
# ---------------------------------------------------------------------------
def collate_attention_grid(attention: Dict[str, Any]) -> np.ndarray:
    """The 25x16x16 attention grid, exactly as `sybil.collate_attentions` builds it.

    image_attention_1 is (ensemble, 1, 25, 256) log-softmax over pixels within a
    slice; volume_attention_1 is (ensemble, 1, 25) log-softmax over slices. The
    product of their exponentials, averaged over the five models, is "where the
    ensemble looked".
    """
    a1 = torch.as_tensor(np.asarray(attention["image_attention_1"]), dtype=torch.float32)
    v1 = torch.as_tensor(np.asarray(attention["volume_attention_1"]), dtype=torch.float32)

    a1 = torch.exp(a1).mean(0)   # -> (1, 25, 256) or (25, 256)
    v1 = torch.exp(v1).mean(0)   # -> (1, 25)      or (25,)
    grid = (a1 * v1.unsqueeze(-1)).reshape(ATT_Z, ATT_H, ATT_W)
    return grid.numpy().astype(np.float32)


def _inplane_sampling_grid(geom: VolumeGeometry) -> torch.Tensor:
    """grid_sample coordinates taking one 16x16 attention plane to rows x cols."""
    row_map, col_map = geom.row_to_attention, geom.col_to_attention
    rows = row_map.apply(torch.arange(geom.rows, dtype=torch.float32))
    cols = col_map.apply(torch.arange(geom.cols, dtype=torch.float32))
    # grid_sample(align_corners=False) wants normalised coords where a cell
    # centre i sits at (i + 0.5) * 2 / size - 1.
    ys = (rows + 0.5) * 2.0 / ATT_H - 1.0
    xs = (cols + 0.5) * 2.0 / ATT_W - 1.0
    grid = torch.stack(
        (xs.view(1, -1).expand(geom.rows, -1), ys.view(-1, 1).expand(-1, geom.cols)),
        dim=-1,
    )
    return grid.unsqueeze(0)  # (1, rows, cols, 2)


def _z_blend(grid: np.ndarray, z: float) -> torch.Tensor | None:
    """The 16x16 plane at continuous attention-z `z`, or None if out of view."""
    if z < -0.5 or z > ATT_Z - 0.5:
        return None
    lo = int(math.floor(z))
    hi = lo + 1
    w = z - lo
    lo_c, hi_c = min(max(lo, 0), ATT_Z - 1), min(max(hi, 0), ATT_Z - 1)
    plane = (1.0 - w) * grid[lo_c] + w * grid[hi_c]
    return torch.as_tensor(plane, dtype=torch.float32).view(1, 1, ATT_H, ATT_W)


def iter_original_attention(
    grid: np.ndarray, geom: VolumeGeometry
) -> Iterator[Tuple[int, np.ndarray]]:
    """Yield (slice index, attention map) in the original slices' pixel grid.

    Slices the network never saw (cropped out in z) yield an all-zero map, which
    is the honest answer: the model paid them no attention because it never read
    them.
    """
    sampling = _inplane_sampling_grid(geom)
    z_map = geom.z_to_attention
    empty = np.zeros((geom.rows, geom.cols), dtype=np.float32)
    for i in range(geom.n_slices):
        plane = _z_blend(grid, float(z_map.apply(i)))
        if plane is None:
            yield i, empty
            continue
        out = F.grid_sample(
            plane, sampling, mode="bilinear", padding_mode="zeros", align_corners=False
        )
        yield i, out[0, 0].numpy()


def map_attention_to_original(grid: np.ndarray, geom: VolumeGeometry) -> np.ndarray:
    """Dense (n_slices, rows, cols) attention. Convenient for tests; ~150 MB for
    a 150-slice scan, so the renderer uses `iter_original_attention` instead."""
    out = np.zeros((geom.n_slices, geom.rows, geom.cols), dtype=np.float32)
    for i, plane in iter_original_attention(grid, geom):
        out[i] = plane
    return out


def upstream_attention(grid: np.ndarray, n_slices: int, rows: int = 512, cols: int = 512) -> np.ndarray:
    """What `sybil.collate_attentions` produces, for comparison in the tests."""
    t = torch.as_tensor(grid, dtype=torch.float32).view(1, 1, ATT_Z, ATT_H, ATT_W)
    up = F.interpolate(t, (n_slices, rows, cols), mode="trilinear")
    return up.squeeze().numpy()


# ---------------------------------------------------------------------------
# colour map
# ---------------------------------------------------------------------------
# A nine-anchor approximation of matplotlib's magma, linearly interpolated --
# close enough for a heat overlay and it keeps matplotlib out of the dependency
# list. Perceptually ordered and readable on a near-black panel; the overlay also
# carries an opacity ramp, so colour is never the only cue.
_MAGMA_ANCHORS = np.array(
    [
        [0, 0, 4],
        [28, 16, 68],
        [79, 18, 123],
        [129, 37, 129],
        [181, 54, 122],
        [229, 80, 100],
        [251, 135, 97],
        [254, 194, 135],
        [252, 253, 191],
    ],
    dtype=np.float32,
)


def magma(x: np.ndarray) -> np.ndarray:
    """Map x in [0, 1] to uint8 RGB with shape x.shape + (3,)."""
    xs = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0) * (len(_MAGMA_ANCHORS) - 1)
    lo = np.floor(xs).astype(int)
    hi = np.minimum(lo + 1, len(_MAGMA_ANCHORS) - 1)
    w = (xs - lo)[..., None]
    rgb = _MAGMA_ANCHORS[lo] * (1.0 - w) + _MAGMA_ANCHORS[hi] * w
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
