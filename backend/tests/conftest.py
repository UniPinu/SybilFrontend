"""Test-wide setup.

The cache is redirected to a throwaway directory *before* app.config is
imported, so tests never touch the real cache/ or evict a prepared patient.
`data/` is left alone: the tests read the real candidates.parquet when it
exists, and skip when it does not.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="sybil-explorer-tests-"))
os.environ.setdefault("CACHE_DIR", str(_TMP / "cache"))
os.environ.setdefault("SYBIL_EAGER_MODEL", "0")
os.environ.setdefault("CACHE_MAX_MB", "50")

import pytest  # noqa: E402

from app.config import settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _dirs():
    settings.ensure_dirs()
    yield


@pytest.fixture
def clean_cache():
    """Empty the patient cache around a test."""
    import shutil

    shutil.rmtree(settings.patients_dir, ignore_errors=True)
    (settings.cache_dir / "pool.json").unlink(missing_ok=True)
    settings.ensure_dirs()
    yield
    shutil.rmtree(settings.patients_dir, ignore_errors=True)
    (settings.cache_dir / "pool.json").unlink(missing_ok=True)
