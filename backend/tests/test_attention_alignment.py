"""M2's alignment check (MVP.md section 6.4).

Pushes a synthetic volume with a bright cube through the *real* preprocessing
chain -- cv2 resize to 256, torchio Resample to 2.5 mm, CropOrPad to 200 slices --
and checks that our inverse mapping lands back on the cube. Also pins down
torchio's behaviour for odd-sized pads and crops, and documents that the
upstream overlay really is offset.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest
import torch
import torchio as tio

from app.attention import (
    ATT_H,
    ATT_W,
    ATT_Z,
    MODEL_IMG_SIZE,
    MODEL_NUM_IMAGES,
    VOXEL_SPACING,
    VolumeGeometry,
    crop_or_pad_offset,
    map_attention_to_original,
    resampled_size,
    upstream_attention,
)

# (n_slices, rows, cols, thickness, pixel spacing) -- covers 2.5/2.0/1.25 mm
# scans, a padded case, a cropped case and odd-sized differences.
CASES = [
    (150, 512, 512, 2.5, 0.703125),
    (157, 512, 512, 2.5, 0.683594),
    (131, 512, 512, 2.0, 0.625),
    (101, 512, 512, 2.0, 0.78125),
    (283, 512, 512, 1.25, 0.585938),
    (220, 512, 512, 2.5, 0.742188),
]


def forward(volume: np.ndarray, thickness: float, spacing: float) -> torch.Tensor:
    """Exactly what `Serie.get_volume()` does to the pixel data, minus the
    normalisation (which does not move anything)."""
    resized = np.stack(
        [cv2.resize(s, dsize=(MODEL_IMG_SIZE, MODEL_IMG_SIZE),
                    interpolation=cv2.INTER_LINEAR) for s in volume]
    )                                              # (T, 256, 256)
    x = torch.from_numpy(resized).float().permute(1, 2, 0).unsqueeze(0)  # (1, H, W, T)
    image = tio.ScalarImage(
        affine=torch.diag(torch.tensor([spacing, spacing, thickness, 1.0])), tensor=x
    )
    image = tio.transforms.Resample(target=VOXEL_SPACING)(image)
    image = tio.transforms.CropOrPad(
        target_shape=(MODEL_IMG_SIZE, MODEL_IMG_SIZE, MODEL_NUM_IMAGES), padding_mode=0
    )(image)
    return image.data[0]  # (H, W, T)


def centroid(arr: np.ndarray) -> tuple[float, ...]:
    total = arr.sum()
    assert total > 0, "nothing survived the preprocessing chain"
    return tuple(
        float((arr.sum(axis=tuple(a for a in range(arr.ndim) if a != k))
               * np.arange(arr.shape[k])).sum() / total)
        for k in range(arr.ndim)
    )


def cube_volume(n, rows, cols, centre, half=8):
    vol = np.zeros((n, rows, cols), dtype=np.float32)
    z, r, c = centre
    vol[max(0, z - half):z + half + 1,
        max(0, r - half):r + half + 1,
        max(0, c - half):c + half + 1] = 1000.0
    return vol


# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source,target", [
    (150, 200), (157, 200), (199, 200), (200, 200), (201, 200),
    (81, 200), (105, 200), (427, 256), (541, 256), (255, 256), (257, 256),
])
def test_crop_or_pad_offset_matches_torchio(source, target):
    """torchio puts ceil(diff/2) on the initial side -- including odd diffs."""
    x = torch.arange(source, dtype=torch.float32).view(1, 1, 1, source) + 1.0
    out = tio.transforms.CropOrPad(target_shape=(1, 1, target), padding_mode=0)(
        tio.ScalarImage(tensor=x)
    ).data[0, 0, 0].numpy()

    offset = crop_or_pad_offset(source, target)
    for old_index in range(source):
        new_index = old_index + offset
        if 0 <= new_index < target:
            assert out[new_index] == pytest.approx(old_index + 1.0), (
                f"value {old_index + 1} should sit at {new_index}")


@pytest.mark.parametrize("size,source_sp", [(150, 2.5), (157, 2.5), (283, 1.25), (101, 2.0),
                                            (256, 0.585938), (256, 0.78125)])
def test_resampled_size_matches_torchio(size, source_sp):
    target_sp = 2.5 if source_sp > 1.0 else VOXEL_SPACING[0]
    x = torch.zeros(1, 1, 1, size)
    image = tio.ScalarImage(
        affine=torch.diag(torch.tensor([1.0, 1.0, source_sp, 1.0])), tensor=x
    )
    out = tio.transforms.Resample(target=(1.0, 1.0, target_sp))(image)
    assert out.spatial_shape[2] == resampled_size(size, source_sp, target_sp)


@pytest.mark.parametrize("n,rows,cols,thickness,spacing", CASES)
def test_geometry_predicts_where_the_cube_lands(n, rows, cols, thickness, spacing):
    """Our forward affine must agree with torchio to well under a voxel."""
    centre = (n // 2, 300, 220)
    vol = cube_volume(n, rows, cols, centre)
    padded = forward(vol, thickness, spacing).numpy()  # (H, W, T)

    geom = VolumeGeometry(n, rows, cols, thickness, spacing, spacing)
    measured_r, measured_c, measured_z = centroid(padded)
    predicted = (
        geom.row_to_volume.apply(centre[1]),
        geom.col_to_volume.apply(centre[2]),
        geom.z_to_volume.apply(centre[0]),
    )
    assert measured_r == pytest.approx(predicted[0], abs=0.75)
    assert measured_c == pytest.approx(predicted[1], abs=0.75)
    assert measured_z == pytest.approx(predicted[2], abs=0.75)


@pytest.mark.parametrize("n,rows,cols,thickness,spacing", CASES)
def test_attention_maps_back_onto_the_cube(n, rows, cols, thickness, spacing):
    """A single hot attention cell must light up the cube, and only the cube."""
    centre = (n // 2, 300, 220)
    geom = VolumeGeometry(n, rows, cols, thickness, spacing, spacing)

    cell = (
        int(round(geom.z_to_attention.apply(centre[0]))),
        int(round(geom.row_to_attention.apply(centre[1]))),
        int(round(geom.col_to_attention.apply(centre[2]))),
    )
    assert 0 <= cell[0] < ATT_Z and 0 <= cell[1] < ATT_H and 0 <= cell[2] < ATT_W

    grid = np.zeros((ATT_Z, ATT_H, ATT_W), dtype=np.float32)
    grid[cell] = 1.0
    mapped = map_attention_to_original(grid, geom)
    assert mapped.shape == (n, rows, cols)

    peak = np.unravel_index(int(np.argmax(mapped)), mapped.shape)
    # One attention cell covers 8 original-ish slices in z and ~16 resampled
    # pixels in plane, so the peak must be within that cell's footprint.
    z_tol = max(4.0, 0.5 * 8 * VOXEL_SPACING[2] / thickness)
    xy_tol = max(16.0, 0.5 * 16 * VOXEL_SPACING[0] / spacing * rows / MODEL_IMG_SIZE)
    assert abs(peak[0] - centre[0]) <= z_tol
    assert abs(peak[1] - centre[1]) <= xy_tol
    assert abs(peak[2] - centre[2]) <= xy_tol


def test_slices_outside_the_model_view_get_no_attention():
    """A 220-slice 2.5 mm scan is 550 mm of chest: too tall for the 200-slot
    volume, so torchio crops it and the lost slices must stay blank."""
    n, thickness, spacing = 220, 2.5, 0.742188
    geom = VolumeGeometry(n, 512, 512, thickness, spacing, spacing)
    assert geom.resampled_slices > MODEL_NUM_IMAGES  # i.e. it really is cropped
    assert geom.slices_in_model_view < n

    grid = np.ones((ATT_Z, ATT_H, ATT_W), dtype=np.float32)
    mapped = map_attention_to_original(grid, geom)
    per_slice = mapped.sum(axis=(1, 2))
    assert per_slice[0] == 0.0 and per_slice[-1] == 0.0
    assert per_slice[n // 2] > 0.0


def test_upstream_overlay_is_offset_in_z():
    """Documents why we do not use `sybil.collate_attentions` for the overlay.

    Upstream stretches the 25-bin z axis over all N slices, as if the volume
    filled the padded 200 slots exactly. For a 150-slice 2.5 mm scan the volume
    actually sits in slots 25..174, so the same attention cell is drawn ~25
    slots -- about 60 mm -- away from where the model was looking.
    """
    n, thickness, spacing = 150, 2.5, 0.703125
    geom = VolumeGeometry(n, 512, 512, thickness, spacing, spacing)
    assert geom.z_offset == 25

    grid = np.zeros((ATT_Z, ATT_H, ATT_W), dtype=np.float32)
    grid[12] = 1.0  # the middle attention bin

    ours = map_attention_to_original(grid, geom).sum(axis=(1, 2))
    # The model's bin 12 covers padded slots 96..103, i.e. original slices
    # 71..78 for this scan, which is where our mapping puts it. At the middle
    # bin the two mappings happen to agree, because the stretch is symmetric.
    assert abs(int(np.argmax(ours)) - 75) <= 6

    # Away from the middle they do not, and that is what matters: the lungs are
    # not in the middle bin.
    grid = np.zeros((ATT_Z, ATT_H, ATT_W), dtype=np.float32)
    grid[4] = 1.0
    ours = map_attention_to_original(grid, geom).sum(axis=(1, 2))
    theirs = upstream_attention(grid, n).sum(axis=(1, 2))
    gap = abs(int(np.argmax(ours)) - int(np.argmax(theirs)))
    assert gap >= 10, f"expected a visible z offset, got {gap} slices"
