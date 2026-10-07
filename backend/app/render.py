"""Turn one processed scan into the handful of small images the UI needs.

Everything is WebP: lung-windowed slices (grayscale), attention overlays (RGBA,
transparent where Sybil did not look), and one aspect-corrected coronal map for
the scrubber. Budget is ~5-10 MB per patient (MVP.md section 5.5).
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import numpy as np
from PIL import Image

from app.attention import VolumeGeometry, iter_original_attention, magma
from app.config import settings

log = logging.getLogger(__name__)


def _raw_loader(serie):
    from sybil.utils.loading import get_sample_loader

    return get_sample_loader("test", serie._args, apply_augmentations=False)


def _as_uint8(arr) -> np.ndarray:
    return np.clip(np.asarray(arr), 0, 255).astype(np.uint8)


def iter_raw_images(serie) -> Iterator[np.ndarray]:
    """The lung-windowed 0-255 slices exactly as Sybil reads them, one at a time.

    Same code path as `Serie.get_raw_images()` (window centre -600, width 1500,
    no augmentations) but without holding all ~150 slices in memory at once.
    """
    loader = _raw_loader(serie)
    for path in serie._meta.paths:
        yield _as_uint8(loader.get_image(path)["input"])


def raw_image(serie, index: int) -> np.ndarray:
    """One slice, without walking the series to get to it."""
    path = serie._meta.paths[index]
    return _as_uint8(_raw_loader(serie).get_image(path)["input"])


@dataclass
class RenderOutput:
    n_slices: int
    slice_quality: int
    width: int
    height: int
    slice_importance: List[float]
    attention_peak: float
    hotspot_slice: int
    coronal_size: Tuple[int, int]
    bytes_written: int

    def as_dict(self) -> dict:
        return {
            "n_slices": self.n_slices,
            "slice_quality": self.slice_quality,
            "width": self.width,
            "height": self.height,
            "slice_importance": self.slice_importance,
            "attention_peak": self.attention_peak,
            "hotspot_slice": self.hotspot_slice,
            "coronal_size": list(self.coronal_size),
            "artifact_bytes": self.bytes_written,
        }


def choose_slice_quality(sample: np.ndarray, n_slices: int) -> int:
    """Pick the highest quality that keeps this patient inside the size budget."""
    budget = settings.slice_target_mb * 1e6
    quality = settings.slice_quality
    while quality > settings.slice_quality_floor:
        buffer = io.BytesIO()
        Image.fromarray(sample, mode="L").save(
            buffer, format="WEBP", quality=quality, method=4
        )
        # + ~15% for the overlays and the coronal map
        if buffer.getbuffer().nbytes * n_slices * 1.15 <= budget:
            break
        quality -= 10
    if quality != settings.slice_quality:
        log.info("slice quality %d -> %d to fit %d slices in %.0f MB",
                 settings.slice_quality, quality, n_slices, settings.slice_target_mb)
    return max(quality, settings.slice_quality_floor)


def render_patient(
    serie,
    attention_grid: np.ndarray,
    geometry: VolumeGeometry,
    out_dir: Path,
    progress=None,
) -> RenderOutput:
    """Write slices/, overlay/ and coronal.webp under `out_dir`."""
    slices_dir = out_dir / "slices"
    overlay_dir = out_dir / "overlay"
    slices_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)

    # Estimate from the middle of the stack: the first slice is usually above or
    # below the lungs and compresses far better than the rest.
    quality = choose_slice_quality(
        raw_image(serie, geometry.n_slices // 2), geometry.n_slices
    )
    att_iter = iter_original_attention(attention_grid, geometry)
    coronal_rows: List[np.ndarray] = []
    importance: List[float] = []
    att_planes: List[np.ndarray] = []
    written = 0
    height = width = 0

    # Pass 1: slices + per-slice attention. The attention maps are kept at the
    # 16x16-ish detail level they carry, so holding them costs little, but we
    # need the scan-wide peak before colouring the overlays.
    for i, (image, (_, att)) in enumerate(zip(iter_raw_images(serie), att_iter)):
        height, width = image.shape[-2:]
        path = slices_dir / f"{i:03d}.webp"
        Image.fromarray(image, mode="L").save(path, format="WEBP", quality=quality, method=4)
        written += path.stat().st_size
        coronal_rows.append(image[height // 2, :].copy())
        att_small = _downsample(att, factor=4)
        att_planes.append(att_small)
        importance.append(float(att.sum()))
        if progress and i % 25 == 0:
            progress(i)

    n = len(att_planes)
    if n == 0:
        raise RuntimeError("no slices rendered")

    peak = max((float(p.max()) for p in att_planes), default=0.0)
    hotspot = int(np.argmax(importance)) if importance else 0

    # Pass 2: overlays, coloured against the scan-wide peak so brightness is
    # comparable between slices of the same scan.
    for i, att_small in enumerate(att_planes):
        rgba = _overlay_rgba(att_small, peak, (height, width))
        path = overlay_dir / f"{i:03d}.webp"
        Image.fromarray(rgba, mode="RGBA").save(
            path, format="WEBP", quality=settings.overlay_quality, method=4
        )
        written += path.stat().st_size

    coronal_path = out_dir / "coronal.webp"
    coronal_size = _write_coronal(coronal_rows, geometry, coronal_path, quality)
    written += coronal_path.stat().st_size

    total = float(sum(importance))
    norm = [round(v / total, 6) for v in importance] if total else [0.0] * n
    log.info("rendered %d slices (%.1f MB) hotspot=%d", n, written / 1e6, hotspot)
    return RenderOutput(
        n_slices=n,
        slice_quality=quality,
        width=width,
        height=height,
        slice_importance=norm,
        attention_peak=peak,
        hotspot_slice=hotspot,
        coronal_size=coronal_size,
        bytes_written=written,
    )


def _downsample(att: np.ndarray, factor: int) -> np.ndarray:
    """Attention is smooth (a 16x16 grid stretched out), so store it small."""
    if factor <= 1:
        return att
    h, w = att.shape
    hh, ww = h // factor, w // factor
    return att[: hh * factor, : ww * factor].reshape(hh, factor, ww, factor).mean(axis=(1, 3))


def _overlay_rgba(att_small: np.ndarray, peak: float, size: Tuple[int, int]) -> np.ndarray:
    """Colour + alpha for one slice, upsampled back to the slice's size."""
    norm = att_small / peak if peak > 0 else np.zeros_like(att_small)
    img = Image.fromarray((np.clip(norm, 0, 1) * 255).astype(np.uint8), mode="L")
    full = np.asarray(img.resize((size[1], size[0]), Image.BILINEAR), dtype=np.float32) / 255.0

    floor = settings.overlay_floor
    # Below the floor the overlay is fully transparent; above it alpha ramps up
    # with attention, so the picture stays readable instead of a wash of colour.
    alpha = np.clip((full - floor) / max(1e-6, 1.0 - floor), 0.0, 1.0)
    rgba = np.zeros((*full.shape, 4), dtype=np.uint8)
    rgba[..., :3] = magma(full)
    rgba[..., 3] = np.rint(np.sqrt(alpha) * 235).astype(np.uint8)
    return rgba


def _write_coronal(
    rows: List[np.ndarray], geometry: VolumeGeometry, path: Path, quality: int
) -> Tuple[int, int]:
    """Middle coronal plane, stretched in z so the chest is not squashed.

    Rows arrive feet-first (Serie sorts by ImagePositionPatient ascending), so
    the image is flipped to put the head at the top.
    """
    plane = np.stack(rows)                     # (n_slices, cols)
    width = plane.shape[1]
    physical_height = geometry.n_slices * geometry.thickness_mm
    height = max(1, int(round(physical_height / geometry.col_spacing_mm)))
    img = Image.fromarray(plane[::-1], mode="L").resize((width, height), Image.BILINEAR)
    img.save(path, format="WEBP", quality=quality, method=4)
    return (width, height)


def dir_size_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def artifact_counts(path: Path) -> Dict[str, int]:
    return {
        "slices": len(list((path / "slices").glob("*.webp"))) if (path / "slices").exists() else 0,
        "overlays": len(list((path / "overlay").glob("*.webp"))) if (path / "overlay").exists() else 0,
    }
