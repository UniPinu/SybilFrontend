"""M2: the fetch -> verify -> render -> cache half of the pipeline.

Builds a small synthetic DICOM series on disk (no network) and pushes it through
the real `Serie`, the real renderer and the real cache layout. The model itself
is stubbed: `test_runner_parity.py` is what checks the arithmetic.
"""
from __future__ import annotations

import numpy as np
import pydicom
import pytest
from PIL import Image
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from app.attention import ATT_H, ATT_W, ATT_Z, VolumeGeometry
from app.fetch import FetchResult, verify_series
from app.config import settings
from app.render import choose_slice_quality, iter_raw_images, render_patient
from app.store import store

ROWS = COLS = 128
N_SLICES = 40
THICKNESS = 2.5
SPACING = 0.703125


def write_series(directory, n=N_SLICES, thickness=THICKNESS, spacing=SPACING):
    """A tiny CT series: air-filled chest with a bright block in the middle."""
    directory.mkdir(parents=True, exist_ok=True)
    series_uid, study_uid = generate_uid(), generate_uid()
    paths = []
    for i in range(n):
        pixels = np.full((ROWS, COLS), 1024 - 900, dtype=np.uint16)  # about -900 HU, lung
        pixels[40:90, 30:100] = 1024 + 40                            # soft tissue
        if 18 <= i <= 22:
            pixels[55:65, 55:65] = 1024 + 120                        # the "nodule"

        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = CTImageStorage
        ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.Modality = "CT"
        ds.PatientID = "SYNTH"
        ds.Manufacturer = "SYNTHETIC"
        ds.ManufacturerModelName = "pytest"
        ds.KVP = 120.0
        ds.Exposure = 40
        ds.ConvolutionKernel = "B30f"
        ds.Rows, ds.Columns = ROWS, COLS
        ds.PixelSpacing = [spacing, spacing]
        ds.SliceThickness = thickness
        ds.ImagePositionPatient = [0.0, 0.0, i * thickness]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.RescaleIntercept = -1024.0
        ds.RescaleSlope = 1.0
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.PixelData = pixels.tobytes()

        path = directory / f"1-{i:03d}.dcm"
        ds.save_as(str(path), write_like_original=False)
        paths.append(str(path))
    return paths


@pytest.fixture(scope="module")
def series(tmp_path_factory):
    return write_series(tmp_path_factory.mktemp("dicom"))


@pytest.fixture(scope="module")
def serie(series):
    from sybil import Serie

    return Serie(list(series))


def test_verify_series_reads_the_header(series):
    info = verify_series(series)
    assert info["n_files"] == N_SLICES
    assert info["thickness_mm"] == THICKNESS
    assert info["pixel_spacing_mm"] == [SPACING, SPACING]
    assert (info["rows"], info["cols"]) == (ROWS, COLS)
    assert info["manufacturer"] == "SYNTHETIC"
    assert info["kvp"] == 120.0


def test_raw_images_are_lung_windowed_8_bit(serie):
    images = list(iter_raw_images(serie))
    assert len(images) == N_SLICES
    first = images[0]
    assert first.dtype == np.uint8
    assert first.shape == (ROWS, COLS)
    # The DICOM windowing formula with centre -600 / width 1500, scaled to 16 bits
    # and then divided by 256, maps -900 HU to 76 and +40 HU to 237.
    assert first[0, 0] == 76      # lung
    assert first[60, 60] == 237   # soft tissue
    assert images[20][60, 60] > 237  # the brighter block in the middle slices


def test_slice_quality_drops_only_when_the_budget_needs_it():
    """Noise is what costs bytes, so quality adapts to the scan, not the count."""
    quiet = np.zeros((512, 512), dtype=np.uint8)
    quiet[100:400, 100:400] = 200
    noisy = (np.random.default_rng(0).random((512, 512)) * 255).astype(np.uint8)

    assert choose_slice_quality(quiet, 150) == settings.slice_quality
    assert choose_slice_quality(quiet, 400) == settings.slice_quality

    lowered = choose_slice_quality(noisy, 400)
    assert settings.slice_quality_floor <= lowered < settings.slice_quality


def test_render_writes_the_expected_artifacts(serie, tmp_path):
    geom = VolumeGeometry(N_SLICES, ROWS, COLS, THICKNESS, SPACING, SPACING)
    grid = np.zeros((ATT_Z, ATT_H, ATT_W), dtype=np.float32)
    hot_bin = int(round(geom.z_to_attention.apply(20)))
    grid[hot_bin, 7, 7] = 1.0

    out = render_patient(serie, grid, geom, tmp_path)

    assert out.n_slices == N_SLICES
    assert (out.height, out.width) == (ROWS, COLS)
    assert len(list((tmp_path / "slices").glob("*.webp"))) == N_SLICES
    assert len(list((tmp_path / "overlay").glob("*.webp"))) == N_SLICES

    assert sum(out.slice_importance) == pytest.approx(1.0, abs=1e-4)
    # the hotspot must land on the slices the hot attention bin covers
    assert abs(out.hotspot_slice - 20) <= 6

    slice_img = Image.open(tmp_path / "slices" / "000.webp")
    assert slice_img.size == (COLS, ROWS)
    assert slice_img.mode in {"L", "RGB"}

    overlay = Image.open(tmp_path / "overlay" / f"{out.hotspot_slice:03d}.webp")
    assert overlay.size == (COLS, ROWS)
    alpha = np.asarray(overlay.convert("RGBA"))[..., 3]
    assert alpha.max() > 0, "the hot slice should have a visible overlay"
    far = np.asarray(Image.open(tmp_path / "overlay" / "000.webp").convert("RGBA"))[..., 3]
    assert far.max() <= alpha.max()

    coronal = Image.open(tmp_path / "coronal.webp")
    # the z axis is stretched so millimetres are square: 40 * 2.5 / 0.703125
    assert coronal.size[0] == COLS
    assert coronal.size[1] == pytest.approx(142, abs=2)

    assert out.bytes_written < 15_000_000  # the per-patient budget in MVP.md 5.5


def test_process_patient_writes_the_three_jsons_and_cleans_up(
    series, serie, monkeypatch, clean_cache
):
    """End to end with the download and the model stubbed out."""
    from app import pipeline
    from app.data import candidates
    from app.runner import RunnerResult

    patient_id = str(candidates()["patient_id"].iloc[0])
    risks = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    geom = VolumeGeometry(N_SLICES, ROWS, COLS, THICKNESS, SPACING, SPACING)

    def fake_fetch(series_uid, dest, expected_mb=None, progress=None, **kwargs):
        if progress:
            progress(1_000, 2_000)
            progress(2_000, 2_000)
        return FetchResult(paths=list(series), bytes_downloaded=2_000,
                           seconds=0.1, directory=dest)

    def fake_run(paths, emit=None, raw_images=None):
        if emit:
            emit("reading", n_slices=len(paths))
            emit("standardizing")
            for i in range(5):
                emit("model", index=i + 1, of=5)
            emit("calibrating")
        grid = np.zeros((ATT_Z, ATT_H, ATT_W), dtype=np.float32)
        grid[int(round(geom.z_to_attention.apply(20))), 7, 7] = 1.0
        return RunnerResult(
            calibrated=risks,
            raw_per_model=[risks] * 5,
            raw_mean=risks,
            attention_grid=grid,
            geometry=geom,
            serie=serie,
            timings={"models": 1.0},
        )

    monkeypatch.setattr(pipeline, "fetch_series", fake_fetch)
    monkeypatch.setattr(pipeline, "run_sybil", fake_run)

    stages = []
    processed = pipeline.process_patient(patient_id, emit=lambda s, **kw: stages.append(s))

    assert processed.risk_by_year == risks
    assert processed.from_cache is False
    assert stages[0] == "downloading" and stages[-1] == "done"

    meta = store.meta(patient_id)
    result = store.result(patient_id)
    outcome = store.outcome(patient_id)
    assert meta["series"]["thickness_mm"] == THICKNESS
    assert meta["candidate"]["patient_id"] == patient_id
    assert result["risk_by_year"] == risks
    assert result["model"]["device"]
    assert result["n_slices"] == N_SLICES
    assert "cancer_within_6y" in outcome
    # the reveal must not leak into the two files the client can read early
    assert "cancer" not in str(meta).lower()
    assert "cancer" not in str(result).lower()

    # the DICOMs are gone, the WebPs are not
    assert not (store.tmp_dir_for(patient_id) / "1-000.dcm").exists()
    assert store.slice_path(patient_id, 0).exists()
    assert store.size_mb(patient_id) < 15

    # second call is a cache hit
    again = pipeline.process_patient(patient_id)
    assert again.from_cache is True
