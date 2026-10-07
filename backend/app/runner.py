"""The real Sybil ensemble, run one scan at a time with per-stage progress.

`Sybil.predict()` runs all five models with no callback, so the "5 experts vote"
step of the UI could not be narrated. We re-implement its loop using the same
internals -- the commit is pinned, so the private methods are stable -- and
tests/test_runner_parity.py asserts our scores are bit-identical to
`Sybil.predict()`.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from app.attention import VolumeGeometry, collate_attention_grid
from app.config import settings

log = logging.getLogger(__name__)

Emit = Callable[..., None]

_model = None
_model_lock = threading.Lock()


def _noop(stage: str, **payload: Any) -> None:
    pass


def get_model():
    """Load the ensemble once per process (~700 MB of weights, ~10 s)."""
    global _model
    with _model_lock:
        if _model is None:
            import torch
            from sybil import Sybil

            torch.set_num_threads(settings.threads)
            t0 = time.time()
            log.info("loading %s on %s (%d threads)",
                     settings.model_name, settings.device, settings.threads)
            _model = Sybil(
                settings.model_name,
                cache=str(settings.sybil_cache),
                device=settings.device,
            )
            log.info("model ready in %.1fs", time.time() - t0)
    return _model


def model_is_loaded() -> bool:
    return _model is not None


def weights_present() -> bool:
    """True if the checkpoints are already on disk (no download needed)."""
    from sybil.model import NAME_TO_FILE

    files = NAME_TO_FILE.get(settings.model_name)
    if not files:
        return False
    cache = settings.sybil_cache
    names = [f"{c}.ckpt" for c in files["checkpoint"]]
    names.append(f"{settings.model_name}_simple_calibrator.json")
    return all((cache / n).exists() for n in names)


@dataclass
class RunnerResult:
    calibrated: List[float]
    raw_per_model: List[List[float]]      # 5 x 6, uncalibrated "raw votes"
    raw_mean: List[float]
    attention_grid: np.ndarray            # (25, 16, 16)
    geometry: VolumeGeometry
    serie: Any
    timings: Dict[str, float] = field(default_factory=dict)

    @property
    def elapsed(self) -> float:
        return round(sum(self.timings.values()), 2)


def run_sybil(
    dicom_paths: Sequence[str],
    emit: Optional[Emit] = None,
    raw_images: Optional[List[np.ndarray]] = None,
) -> RunnerResult:
    """Run the ensemble on one series, emitting a progress event per stage.

    `raw_images` lets the caller reuse the windowed slices it already loaded for
    rendering; they are only needed here for the image dimensions.
    """
    import torch

    emit = emit or _noop
    from sybil import Serie

    model = get_model()
    timings: Dict[str, float] = {}

    def timed(name: str, fn):
        t0 = time.time()
        out = fn()
        timings[name] = round(time.time() - t0, 2)
        return out

    emit("reading", n_slices=len(dicom_paths))
    # Serie sorts the slices by ImagePositionPatient, reads spacing and rejects
    # anything thicker than 5 mm.
    serie = timed("reading", lambda: Serie(list(dicom_paths)))

    emit("standardizing")
    # lru_cached on the Serie, so every model below reuses this one volume.
    timed("standardizing", serie.get_volume)

    # Attention has to be mapped back onto the *original* slice grid, not the
    # 256x256 one the network sees, so take the dimensions from the DICOM.
    if raw_images:
        rows, cols = int(raw_images[0].shape[-2]), int(raw_images[0].shape[-1])
    else:
        import pydicom

        dcm = pydicom.dcmread(serie._meta.paths[0], stop_before_pixels=True)
        rows, cols = int(dcm.Rows), int(dcm.Columns)

    geometry = VolumeGeometry.from_serie(serie, rows=rows, cols=cols)
    log.info("geometry: %s", geometry.as_dict())

    raw_per_model: List[List[float]] = []
    attentions: List[Dict[str, Any]] = []
    t_models = time.time()
    for k, net in enumerate(model.ensemble):
        emit("model", index=k + 1, of=len(model.ensemble))
        with torch.no_grad():
            pred = model._predict(net, [serie], return_attentions=True)
        raw_per_model.append(list(pred.scores[0]))
        attentions.append(pred.attentions[0])
        log.info("model %d/%d done (%.1fs)", k + 1, len(model.ensemble), time.time() - t_models)
    timings["models"] = round(time.time() - t_models, 2)

    emit("calibrating")
    t0 = time.time()
    # Identical to Sybil.predict(): mean of the raw sigmoid outputs, then the
    # per-year isotonic calibrator.
    raw_mean = np.mean(np.array(raw_per_model), axis=0)
    calibrated = model._calibrate(raw_mean.reshape(1, -1))[0].tolist()

    stacked = {
        key: np.stack([np.asarray(a[key]) for a in attentions])
        for key in ("image_attention_1", "volume_attention_1")
    }
    grid = collate_attention_grid(stacked)
    timings["calibrating"] = round(time.time() - t0, 2)

    return RunnerResult(
        calibrated=[float(x) for x in calibrated],
        raw_per_model=[[float(x) for x in row] for row in raw_per_model],
        raw_mean=[float(x) for x in raw_mean],
        attention_grid=grid,
        geometry=geometry,
        serie=serie,
        timings=timings,
    )
