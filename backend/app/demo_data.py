"""Upstream's demo scan: the install smoke test, and the offline fallback person.

This is the scan from `examples/utils.py::get_demo_data` (a Dropbox zip, ~60 MB).
It has a known expected score vector, which makes it our regression check. It has
no NLST outcome attached, so when it is used as a demo person the reveal is
disabled (MVP.md section 5.7).
"""
from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path
from urllib.request import urlopen

log = logging.getLogger(__name__)

DEMO_DATA_URL = (
    "https://www.dropbox.com/scl/fi/covbvo6f547kak4em3cjd/sybil_example.zip"
    "?rlkey=7a13nhlc9uwga9x7pmtk1cf1c&st=dqi0cf9k&dl=1"
)

# tests/regression_test.py at main@d9fc81b, `expected_scores`.
EXPECTED_DEMO_SCORES: tuple[float, ...] = (
    0.021628819563619374,
    0.03857256315036462,
    0.07191945816622261,
    0.07926975188037134,
    0.09584583525781108,
    0.13568094038444453,
)

DEMO_PATIENT_ID = "demo_offline"


def demo_dicom_paths(cache_dir: Path | None = None) -> list[str]:
    """Download (once) and return the demo scan's DICOM paths, sorted by name."""
    cache_dir = Path(cache_dir or os.path.expanduser("~/.sybil"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "sybil_example.zip"
    data_dir = cache_dir / "sybil_example"
    image_dir = data_dir / "sybil_demo_data"

    if not image_dir.exists():
        if not zip_path.exists():
            log.info("downloading demo scan to %s", zip_path)
            with urlopen(DEMO_DATA_URL) as resp, open(zip_path, "wb") as fh:
                fh.write(resp.read())
        log.info("extracting demo scan to %s", data_dir)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(data_dir)

    paths = sorted(str(p) for p in image_dir.iterdir() if p.is_file())
    if not paths:
        raise RuntimeError(f"no DICOM files found in {image_dir}")
    return paths
