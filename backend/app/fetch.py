"""Download exactly one DICOM series from NCI Imaging Data Commons.

`idc-index` resolves the series to its public AWS S3 prefix and pulls it with
s5cmd. No account, no bulk download: ~83 MB median per series (MVP.md section 3),
deleted again as soon as the result JSON is written.

idc-index gives no progress callback, so a watcher thread polls the destination
directory and reports bytes-so-far against the size the index already told us.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

ProgressCb = Callable[[int, int], None]


@dataclass
class FetchResult:
    paths: List[str]
    bytes_downloaded: int
    seconds: float
    directory: Path


def _dir_bytes(path: Path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return 0


def _dicom_paths(path: Path) -> List[str]:
    files = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".dcm", ""}]
    # NLST series files are named 1-001.dcm etc.; sort so the order is stable
    # (Serie re-sorts by ImagePositionPatient anyway).
    return sorted(str(p) for p in files)


def fetch_series(
    series_uid: str,
    dest: Path,
    expected_mb: Optional[float] = None,
    progress: Optional[ProgressCb] = None,
    poll_seconds: float = 0.4,
) -> FetchResult:
    """Download one series into `dest` (flat) and return its DICOM paths."""
    from app.idc import get_client

    dest.mkdir(parents=True, exist_ok=True)
    expected_bytes = int((expected_mb or 0) * 1e6)
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(poll_seconds):
            done = _dir_bytes(dest)
            if progress:
                progress(done, expected_bytes)

    watcher = threading.Thread(target=watch, name="fetch-progress", daemon=True)
    if progress:
        watcher.start()

    client = get_client()
    t0 = time.time()
    try:
        client.download_dicom_series(
            seriesInstanceUID=series_uid,
            downloadDir=str(dest),
            dirTemplate=None,  # flat: no collection/patient/study folders
            quiet=True,
            show_progress_bar=False,
        )
    finally:
        stop.set()
        if watcher.is_alive():
            watcher.join(timeout=2)

    seconds = time.time() - t0
    paths = _dicom_paths(dest)
    total = _dir_bytes(dest)
    if progress:
        progress(total, total)
    if not paths:
        raise RuntimeError(f"no DICOM files downloaded for series {series_uid}")
    log.info("fetched %s: %d files, %.1f MB in %.1fs", series_uid, len(paths),
             total / 1e6, seconds)
    return FetchResult(paths=paths, bytes_downloaded=total, seconds=seconds, directory=dest)


def verify_series(paths: List[str]) -> dict:
    """Re-check from the DICOM headers what the index only implied.

    The SeriesDescription parsing in scripts/build_candidates.py is derived from
    observed data, so the real SliceThickness is confirmed here before the scan
    reaches the model (MVP.md section 5.2). `Serie` itself rejects > 5 mm.
    """
    import pydicom

    first = pydicom.dcmread(paths[0], stop_before_pixels=True)
    thickness = float(first.SliceThickness)
    spacing = [float(x) for x in first.PixelSpacing]
    return {
        "n_files": len(paths),
        "thickness_mm": thickness,
        "pixel_spacing_mm": spacing,
        "rows": int(first.Rows),
        "cols": int(first.Columns),
        "manufacturer": str(getattr(first, "Manufacturer", "") or ""),
        "model": str(getattr(first, "ManufacturerModelName", "") or ""),
        "kvp": float(getattr(first, "KVP", 0) or 0) or None,
        "exposure_mas": float(getattr(first, "Exposure", 0) or 0) or None,
        "convolution_kernel": str(getattr(first, "ConvolutionKernel", "") or ""),
    }
