"""app/runner.py must agree with `Sybil.predict()`, not merely resemble it.

Two levels:
  * a fast test that drives both code paths with a stub ensemble and the real
    calibrator, so the arithmetic (mean of raw sigmoids -> per-year isotonic
    calibration -> attention stacking) is compared exactly;
  * a slow test (-m slow) that runs the real five-model ensemble on upstream's
    demo scan and requires the published score vector.
"""
from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
import torch.nn as nn

from app.attention import ATT_H, ATT_W, ATT_Z, collate_attention_grid
from app.config import settings
from app.demo_data import EXPECTED_DEMO_SCORES

CALIBRATOR = settings.sybil_cache / f"{settings.model_name}_simple_calibrator.json"


class StubNet(nn.Module):
    """Deterministic stand-in for SybilNet with the same output contract."""

    def __init__(self, seed: int):
        super().__init__()
        self.seed = seed

    def forward(self, volume, batch=None):
        g = torch.Generator().manual_seed(self.seed)
        scale = 1.0 + 0.1 * self.seed
        return {
            "logit": torch.randn(1, 6, generator=g) * scale,
            "image_attention_1": torch.randn(1, ATT_Z, ATT_H * ATT_W, generator=g),
            "volume_attention_1": torch.randn(1, ATT_Z, generator=g),
            "hidden": torch.randn(1, 512, generator=g),
        }


def _serie_base():
    from sybil import Serie

    return Serie


class StubSerie(_serie_base()):
    """Enough of sybil.Serie for the runner: a volume and the DICOM metadata.

    Subclasses the real Serie (without running its __init__) because
    `Sybil._predict` isinstance-checks what it is handed.
    """

    def __init__(self, n_slices=120, thickness=2.5, spacing=0.703125):  # noqa: D107
        self._meta = SimpleNamespace(
            paths=[f"slice{i:03d}.dcm" for i in range(n_slices)],
            thickness=thickness,
            pixel_spacing=[spacing, spacing],
            manufacturer="STUB",
            slice_positions=list(range(n_slices)),
            voxel_spacing=torch.tensor([spacing, spacing, thickness, 1.0]),
        )
        self._args = Namespace(img_file_type="dicom", cache_path=None, img_size=[256, 256],
                               img_mean=[128.1722], img_std=[87.1849], num_chan=3,
                               use_annotations=False, num_images=200,
                               fix_seed_for_multi_image_augmentations=True,
                               slice_thickness_filter=5)

    def get_volume(self):
        return torch.zeros(1, 3, 200, 256, 256)


def make_sybil(calibrated: bool):
    """A Sybil instance with a stub ensemble, built without loading weights."""
    from sybil import Sybil
    from sybil.models.calibrator import SimpleClassifierGroup
    from sybil.utils.logging_utils import get_logger

    model = Sybil.__new__(Sybil)
    model._logger = get_logger()
    model.device = "cpu"
    model._device_flexible = False
    model.ensemble = nn.ModuleList([StubNet(i) for i in range(1, 6)])
    model.calibrator = (
        SimpleClassifierGroup.from_json_grouped(str(CALIBRATOR)) if calibrated else None
    )
    return model


@pytest.fixture
def patched(monkeypatch):
    import sybil

    from app import runner

    serie = StubSerie()
    monkeypatch.setattr(sybil, "Serie", lambda paths: serie, raising=True)
    monkeypatch.setattr(runner, "_model", None, raising=False)
    return serie


@pytest.mark.parametrize("calibrated", [False, True])
def test_runner_matches_sybil_predict(patched, monkeypatch, calibrated):
    if calibrated and not CALIBRATOR.exists():
        pytest.skip(f"calibrator not downloaded yet: {CALIBRATOR}")

    from app import runner

    model = make_sybil(calibrated)
    monkeypatch.setattr(runner, "get_model", lambda: model)

    expected = model.predict([patched], return_attentions=True)
    ours = runner.run_sybil(["slice000.dcm"], raw_images=[np.zeros((512, 512), dtype=np.uint8)])

    # Bit-for-bit, not approximately.
    assert np.array_equal(np.array(ours.calibrated), np.array(expected.scores[0]))

    expected_grid = collate_attention_grid(expected.attentions[0])
    assert np.array_equal(ours.attention_grid, expected_grid)
    assert ours.attention_grid.shape == (ATT_Z, ATT_H, ATT_W)


def test_runner_emits_every_stage(patched, monkeypatch):
    from app import runner

    monkeypatch.setattr(runner, "get_model", lambda: make_sybil(False))
    seen = []
    runner.run_sybil(
        ["slice000.dcm"],
        emit=lambda stage, **kw: seen.append((stage, kw)),
        raw_images=[np.zeros((512, 512), dtype=np.uint8)],
    )
    stages = [s for s, _ in seen]
    assert stages[:2] == ["reading", "standardizing"]
    assert stages.count("model") == 5
    assert [kw["index"] for s, kw in seen if s == "model"] == [1, 2, 3, 4, 5]
    assert stages[-1] == "calibrating"


def test_runner_reads_geometry_from_the_serie(patched, monkeypatch):
    from app import runner

    monkeypatch.setattr(runner, "get_model", lambda: make_sybil(False))
    result = runner.run_sybil(
        ["slice000.dcm"], raw_images=[np.zeros((512, 512), dtype=np.uint8)]
    )
    geom = result.geometry
    assert (geom.n_slices, geom.rows, geom.cols) == (120, 512, 512)
    assert geom.thickness_mm == 2.5
    assert geom.z_offset == 40  # (200 - 120) / 2
    assert geom.slices_in_model_view == 120


# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_real_ensemble_reproduces_published_scores():
    """The whole thing, for real: ~4-5 minutes of CPU on upstream's demo scan."""
    from app.demo_data import demo_dicom_paths
    from app.runner import run_sybil, weights_present

    if not weights_present():
        pytest.skip("model weights not downloaded; run scripts/smoke_test.py")

    result = run_sybil(demo_dicom_paths())
    for expected, actual in zip(EXPECTED_DEMO_SCORES, result.calibrated):
        assert actual == pytest.approx(expected, rel=1e-4)
    assert len(result.raw_per_model) == 5
    assert result.attention_grid.shape == (ATT_Z, ATT_H, ATT_W)
    assert result.attention_grid.min() >= 0.0
