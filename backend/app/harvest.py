"""Bulk Sybil runs for the T0 + T1 -> T2 dataset (scripts/harvest.py).

Unlike app/pipeline.py, which prepares one patient for the viewer (WebP slices,
overlays, a size-capped cache), a harvest keeps only what a later model can
learn from, and keeps all of it, because re-running ~59k scans is the expensive
part:

    {out}/scans/{patient_id}.json     scores, labels, series facts -- the "done" marker
    {out}/features/{patient_id}.npz   hidden (5, 512) float32, attention (25, 16, 16) float16
    {out}/failed.jsonl                one line per failed scan
    {out}/STOP                        ask a running harvest to stop after the current scan

`hidden` is the 512-number summary each of the five networks computes just
before its risk layer: a far richer description of the scan than six risks.

Every file is written to a temporary name and renamed into place, and the JSON
is written after the npz, so a scan either exists completely or not at all, no
matter when the process is killed.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from app import participants as people
from app.attention import collate_attention_grid
from app.config import settings
from app.data import exams
from app.trajectory import CSV_COLUMNS, ROUNDS, risk_columns

log = logging.getLogger(__name__)

SYBIL_COMMIT = "d9fc81b93c1c6239a570c1c570c1f2a2e6266a4a"
ATTENTION_KEYS = ("image_attention_1", "volume_attention_1")
# per-exam columns copied into each scan record; none of them identify anyone
EXAM_FIELDS = ("series_uid", "manufacturer", "kernel", "thickness_mm", "n_instances",
               "series_size_mb", "days_since_rand", "age_at_scan", "sex", "smoking_status",
               "race", "cancer_within_6y", "years_to_cancer", "years_followed")


def default_dir() -> Path:
    return settings.data_dir / "harvest"


# --- who -------------------------------------------------------------------

def eligible() -> pd.DataFrame:
    """Participants with an eligible exam in every round and a date for each.

    Indexed by nlst_pid, with one exam id column per round (`exam_t0` ..).
    """
    df = exams()
    if df is None:
        raise SystemExit("data/exams.parquet is missing -- run scripts/build_candidates.py")
    ok = df[df["eligible"] & df["study_yr"].isin(ROUNDS)]
    wide = ok.pivot_table(index="nlst_pid", columns="study_yr", values="patient_id",
                          aggfunc="first").dropna()
    wide.columns = [f"exam_t{int(c)}" for c in wide.columns]
    prsn = people.table()
    year_cols = [f"t{r}_years" for r in ROUNDS]
    joined = wide.join(prsn[year_cols + ["diagnosed", "years_rand_to_dx",
                                         "cancer_within_6y_any"]], how="inner")
    joined = joined.dropna(subset=year_cols)
    # the curve needs T1 strictly after T0
    return joined[joined["t1_years"] > joined["t0_years"]]


def order(pool: pd.DataFrame, seed: int, cancer_first: bool = False) -> List[str]:
    """A seeded shuffle, so stopping at any point leaves a random sample."""
    shuffled = list(pool.sample(frac=1.0, random_state=seed).index)
    if not cancer_first:
        return shuffled
    cancer = set(pool.index[pool["cancer_within_6y_any"].fillna(False).astype(bool)])
    return [p for p in shuffled if p in cancer] + [p for p in shuffled if p not in cancer]


# --- the model ---------------------------------------------------------------

def load_model(device: str):
    """The ensemble on `device`, with TF32 off so a GPU computes in full fp32 like the CPU."""
    import torch
    from sybil import Sybil

    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_num_threads(settings.threads)
    return Sybil(settings.model_name, cache=str(settings.sybil_cache), device=device)


@dataclass
class Scored:
    calibrated: List[float]
    raw_mean: List[float]
    raw_per_model: List[List[float]]
    hidden: np.ndarray     # (5, 512)
    attention: np.ndarray  # (25, 16, 16)


def score_volume(model, volume) -> Scored:
    """Sybil.predict() on one prepared volume, keeping each network's hidden layer.

    Same arithmetic as app/runner.py (and so as upstream): sigmoid per network,
    mean over the five, then the calibrator.
    """
    import torch

    volume = volume.to(model.device)
    raw, hidden, attentions = [], [], []
    with torch.no_grad():
        for net in model.ensemble:
            out = net(volume)
            raw.append(out["logit"].sigmoid().squeeze(0).cpu().numpy().tolist())
            hidden.append(out["hidden"].squeeze(0).cpu().numpy())
            attentions.append({k: out[k].cpu().numpy() for k in ATTENTION_KEYS})
    raw_mean = np.mean(np.array(raw), axis=0)
    calibrated = model._calibrate(raw_mean.reshape(1, -1))[0].tolist()
    stacked = {k: np.stack([a[k] for a in attentions]) for k in ATTENTION_KEYS}
    return Scored(
        calibrated=[float(x) for x in calibrated],
        raw_mean=[float(x) for x in raw_mean],
        raw_per_model=[[float(x) for x in row] for row in raw],
        hidden=np.stack(hidden).astype(np.float32),
        attention=np.asarray(collate_attention_grid(stacked), dtype=np.float32),
    )


# --- storage -----------------------------------------------------------------

def _replace(tmp: Path, path: Path) -> None:
    # On Windows a virus scanner or indexer can hold the target for a moment.
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.2 * (attempt + 1))


def write_json(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=_jsonable)
        fh.flush()
        os.fsync(fh.fileno())
    _replace(tmp, path)


def write_npz(path: Path, **arrays: np.ndarray) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez_compressed(fh, **arrays)
        fh.flush()
        os.fsync(fh.fileno())
    _replace(tmp, path)


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


def _clean(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and value != value:
        return None
    return value


class HarvestDir:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.scans = self.root / "scans"
        self.features = self.root / "features"
        self.failed_log = self.root / "failed.jsonl"
        self.stop_file = self.root / "STOP"
        self.lock_file = self.root / ".lock"
        self.tmp = self.root / "tmp"

    def ensure(self) -> None:
        for d in (self.root, self.scans, self.features, self.tmp):
            d.mkdir(parents=True, exist_ok=True)

    def clean_leftovers(self) -> None:
        """Half-written files and DICOMs from a run that was killed."""
        import shutil

        for d in (self.scans, self.features):
            for p in d.glob("*.tmp"):
                p.unlink(missing_ok=True)
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True, exist_ok=True)

    def done(self) -> set:
        return {p.stem for p in self.scans.glob("*.json")}

    def failed(self) -> Dict[str, dict]:
        """exam id -> its latest failure. A torn last line (killed mid-write) is ignored."""
        out: Dict[str, dict] = {}
        if not self.failed_log.exists():
            return out
        with open(self.failed_log, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out[rec["patient_id"]] = rec
        return out

    def record_failure(self, patient_id: str, nlst_pid: str, stage: str, error: str) -> None:
        rec = {"patient_id": patient_id, "nlst_pid": nlst_pid, "stage": stage,
               "error": error[:500], "at": now()}
        with open(self.failed_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def save(self, record: dict, scored: Scored) -> None:
        pid = record["patient_id"]
        write_npz(self.features / f"{pid}.npz", hidden=scored.hidden,
                  attention=scored.attention.astype(np.float16))
        write_json(self.scans / f"{pid}.json", record)  # last: marks the scan done

    def records(self) -> Iterable[dict]:
        for p in sorted(self.scans.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as fh:
                    yield json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("unreadable %s: %s", p.name, exc)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def scan_record(exam_id: str, nlst_pid: str, round_: int, years: float, exam: dict,
                series: dict, scored: Scored, device: str, timings: dict) -> dict:
    import torch

    return {
        "patient_id": exam_id,
        "nlst_pid": nlst_pid,
        "round": round_,
        "years_since_rand": _clean(years),
        "risk_by_year": [round(v, 6) for v in scored.calibrated],
        "raw_mean": [round(v, 8) for v in scored.raw_mean],
        "raw_per_model": [[round(v, 8) for v in row] for row in scored.raw_per_model],
        "exam": {k: _clean(exam.get(k)) for k in EXAM_FIELDS},
        "series": series,
        "model": {"name": settings.model_name, "device": device, "torch": torch.__version__,
                  "sybil_commit": SYBIL_COMMIT},
        "timings": timings,
        "finished_at": now(),
    }


# --- compile -------------------------------------------------------------------

def compile_dataset(hd: HarvestDir, trajectories_csv: Optional[Path] = None) -> Dict[str, Any]:
    """Collect the per-scan files into tables a model can train on.

    {out}/scans.parquet     one row per finished scan, every field flattened
    {out}/features.npz      complete participants only: pids, hidden (n, 3, 5, 512),
                            attention (n, 3, 25, 16, 16)
    trajectories_csv        complete participants in the CSV the Experiment page and
                            scripts/fit_trajectory.py read (written only if given)
    """
    rows = []
    for rec in hd.records():
        row = {"patient_id": rec["patient_id"], "nlst_pid": rec["nlst_pid"],
               "round": rec["round"], "years_since_rand": rec["years_since_rand"],
               "device": rec["model"]["device"], "finished_at": rec["finished_at"]}
        row.update({f"r{k}": v for k, v in enumerate(rec["risk_by_year"], 1)})
        row.update({f"raw{k}": v for k, v in enumerate(rec["raw_mean"], 1)})
        for m, scores in enumerate(rec["raw_per_model"], 1):
            row.update({f"m{m}_raw{k}": v for k, v in enumerate(scores, 1)})
        row.update(rec["exam"])
        row.update({f"series_{k}": v for k, v in rec["series"].items()
                    if not isinstance(v, (list, dict))})
        rows.append(row)
    scans = pd.DataFrame(rows)
    summary: Dict[str, Any] = {"scans": len(scans), "participants_complete": 0}
    if scans.empty:
        return summary
    _atomic_parquet(scans, hd.root / "scans.parquet")

    counts = scans.groupby("nlst_pid")["round"].nunique()
    complete = sorted(counts.index[counts == len(ROUNDS)])
    summary["participants_complete"] = len(complete)
    summary["devices"] = sorted(scans["device"].unique().tolist())
    if not complete:
        return summary

    by_key = scans.set_index(["nlst_pid", "round"])
    prsn = people.table()
    hidden = np.zeros((len(complete), len(ROUNDS), 5, 512), np.float32)
    attention = np.zeros((len(complete), len(ROUNDS), 25, 16, 16), np.float16)
    csv_rows = []
    for i, pid in enumerate(complete):
        out = {"nlst_pid": pid,
               "diagnosed": _clean(prsn.loc[pid, "diagnosed"]) if pid in prsn.index else None,
               "years_rand_to_dx": _clean(prsn.loc[pid, "years_rand_to_dx"]) if pid in prsn.index else None}
        for r in ROUNDS:
            scan = by_key.loc[(pid, r)]
            out[f"t{r}_years"] = scan["years_since_rand"]
            out.update({c: scan[f"r{k}"] for k, c in enumerate(risk_columns(r), 1)})
            with np.load(hd.features / f"{scan['patient_id']}.npz") as z:
                hidden[i, r], attention[i, r] = z["hidden"], z["attention"]
        csv_rows.append(out)
    tmp = hd.root / "features.npz.tmp"
    with open(tmp, "wb") as fh:
        np.savez(fh, pids=np.array(complete), hidden=hidden, attention=attention)
    _replace(tmp, hd.root / "features.npz")

    if trajectories_csv is not None:
        tmp = trajectories_csv.with_name(trajectories_csv.name + ".tmp")
        pd.DataFrame(csv_rows, columns=CSV_COLUMNS).to_csv(tmp, index=False)
        _replace(tmp, trajectories_csv)
        summary["trajectories_csv"] = str(trajectories_csv)
    return summary


def _atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    _replace(tmp, path)
