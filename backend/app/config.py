"""Runtime configuration. Everything is overridable through the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(os.path.expanduser(raw)).resolve() if raw else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- paths -----------------------------------------------------------
    data_dir: Path = field(default_factory=lambda: _env_path("DATA_DIR", BACKEND_DIR / "data"))
    cache_dir: Path = field(default_factory=lambda: _env_path("CACHE_DIR", BACKEND_DIR / "cache"))
    sybil_cache: Path = field(
        default_factory=lambda: _env_path("SYBIL_CACHE", Path(os.path.expanduser("~/.sybil")))
    )

    # --- model -----------------------------------------------------------
    model_name: str = os.environ.get("SYBIL_MODEL", "sybil_ensemble")
    # torch 1.13 has patchy MPS coverage and the Windows PyPI wheel is CPU-only,
    # so CPU is the only configuration we claim to reproduce upstream scores on.
    device: str = os.environ.get("SYBIL_DEVICE", "cpu")
    # Upstream defaults to min(8, cpu_count) with a comment that more never
    # helps. Measured on this machine (i7-13700K, 24 logical cores), one model
    # on the demo scan: 8 threads 24.8s, 12 -> 17.2s, 16 -> 14.6s, 24 -> 13.0s,
    # with bit-identical scores at every setting. 16 is the sweet spot and
    # takes the full ensemble from ~4.5 min to ~1.5 min.
    threads: int = _env_int("SYBIL_THREADS", min(16, os.cpu_count() or 1))
    max_followup: int = 6
    # Load the ensemble (~700 MB of weights) when the API boots rather than on
    # the first request. Turn off for fast API-only tests.
    eager_model: bool = _env_bool("SYBIL_EAGER_MODEL", True)

    # --- data ------------------------------------------------------------
    candidates_file: str = "candidates.parquet"
    exams_file: str = "exams.parquet"
    participants_file: str = "participants.parquet"
    max_series_mb: float = float(os.environ.get("MAX_SERIES_MB", "150"))

    # --- cache -----------------------------------------------------------
    cache_max_mb: int = _env_int("CACHE_MAX_MB", 1500)

    # --- rendering -------------------------------------------------------
    slice_quality: int = _env_int("SLICE_QUALITY", 80)
    # Low-dose CT is noisy, and noise is expensive to compress: at quality 80 a
    # quiet scan costs ~14 KB per slice and a noisy one ~75 KB, which would put a
    # 250-slice scan over the 15 MB per-patient budget in MVP.md 5.5. The
    # renderer measures one slice and steps the quality down until the estimate
    # fits, never below `slice_quality_floor`.
    slice_target_mb: float = float(os.environ.get("SLICE_TARGET_MB", "12"))
    slice_quality_floor: int = _env_int("SLICE_QUALITY_FLOOR", 50)
    overlay_quality: int = _env_int("OVERLAY_QUALITY", 70)
    # Attention below this fraction of the per-scan maximum is rendered fully
    # transparent, which keeps the overlay WebPs small and the picture readable.
    overlay_floor: float = float(os.environ.get("OVERLAY_FLOOR", "0.12"))

    @property
    def candidates_path(self) -> Path:
        return self.data_dir / self.candidates_file

    @property
    def exams_path(self) -> Path:
        return self.data_dir / self.exams_file

    @property
    def participants_path(self) -> Path:
        return self.data_dir / self.participants_file

    @property
    def patients_dir(self) -> Path:
        return self.cache_dir / "patients"

    @property
    def tmp_dir(self) -> Path:
        return self.cache_dir / "tmp"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir, self.patients_dir, self.tmp_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
