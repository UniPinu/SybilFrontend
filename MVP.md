# Sybil Explorer — MVP

> An interactive, beginner-friendly showcase of **Sybil**, the MIT/MGH deep-learning model that predicts a person's lung-cancer risk for the next six years from a **single low-dose chest CT scan**.
> The app really runs Sybil (no mock-ups). It picks a real, de-identified person from the National Lung Screening Trial (NLST), shows their scan, runs the model live, visualizes the result, and then reveals what actually happened to that person.

Runs locally on an Apple-Silicon MacBook Pro. It never downloads the full dataset: one scan at a time, ~83 MB median, deleted after processing.

---

## 1. The demo story (what a visitor experiences)

1. **"One scan. Six years ahead."** A short intro explains, in three illustrated steps, what Sybil does.
2. **Meet a person.** The visitor clicks _Pick a random person_. A card appears:
      - shows: age, sex, smoking history, which screening round the scan is from;
      - hides: the outcome, behind a sealed "What happened?" card.
3. **Look at the scan.** The visitor scrubs through the CT slices like a radiologist would. A small coronal "map" shows where in the chest they are.
4. **Run Sybil.** A friendly progress stepper narrates each stage, with five "expert" avatars lighting up as each of Sybil's five ensemble models casts its vote:
      - "Reading the scan…"
      - "Standardizing it…"
      - "5 models vote…"
      - "Calibrating…"
5. **See the result.**
      - A big headline number ("6-year risk: 13.6%").
      - A 1→6 year risk curve.
      - A 100-person icon array ("about 14 in 100 people with a scan like this").
      - A comparison against a typical screening participant.
6. **Where did Sybil look?** A heat-map overlay on the scan, plus a per-slice "attention" strip under the scrubber with a _Jump to hotspot_ button.
7. **The reveal.** The sealed card flips: _"Diagnosed with lung cancer about 3 years after this scan"_ or _"No lung cancer during 6 years of follow-up"_. The outcome is also marked on the risk curve.
8. **Scoreboard.** A cohort view of every prepared patient, plotted by predicted risk and coloured by real outcome. Visitors see at a glance that the people who got cancer cluster at the high end. Published accuracy numbers are explained in plain words.

Tone throughout: curious and explanatory, never alarmist. This is a research demo, not a diagnostic tool.

---

## 2. Scope

**In scope (MVP)**

- Classic Sybil v1 ensemble (`sybil_ensemble`), run locally on CPU.
- NLST patients fetched on demand from NCI Imaging Data Commons (IDC). Outcomes come from IDC's public NLST clinical tables.
- A pre-processed "curated pool" so the demo is instant, plus a "live" mode that fetches and runs a brand-new random person.
- The single-page, guided experience in §1.

**Out of scope**

- **Sybil-2** (multi-scan, nodule tracking). It is in the repo's `v1.7.x` tags, but its environment targets Linux x86_64 + CUDA (nnUNet, torch-scatter, ANTs). Note it as "future work".
- Uploading your own scans.
- Training or fine-tuning.
- Any clinical use.

---

## 3. Verified facts that drive the design

| Fact                                                                                                                                                                                                                                            | Consequence                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `main` (commit `d9fc81b`, = v1.6.0 + a `torch.load` hotfix) is classic Sybil. It pins `torch==1.13.1`, `numpy==1.24.1`, `python_requires >=3.8,<3.11`.                                                                                          | Use **Python 3.10** and pin to that commit.                                                              |
| Tags `v1.7.2`/`v1.7.3` import Sybil-2 deps (`ants`, `lungmask`, `cc3d`, …) at `import sybil`.                                                                                                                                                   | **Do not** install the latest tag. Stay on `main@d9fc81b`.                                               |
| macOS arm64 wheels exist for every pinned dep on Python 3.10: torch 1.13.1, torchvision 0.14.1, opencv 4.5.4.60, numpy 1.24.1, pylibjpeg-\*. A full `uv pip compile` for `aarch64-apple-darwin`/3.10 with idc-index + FastAPI resolves cleanly. | Apple Silicon works out of the box.                                                                      |
| On Intel Macs the `setup.cfg` marker demands `torch==1.13.1+cu117` (x86_64), which doesn't exist for macOS.                                                                                                                                     | Apple Silicon only, unless you add a dependency override.                                                |
| **The PyPI package named `sybil` is an unrelated doctest library.**                                                                                                                                                                             | Never `pip install sybil`. Install from GitHub.                                                          |
| Weights download automatically on first use: `sybil_checkpoints.zip` ≈ **696 MB** → `~/.sybil/`.                                                                                                                                                | One-time cost. Show a first-run screen.                                                                  |
| `get_default_device()` uses MPS only if `PYTORCH_ENABLE_MPS_FALLBACK=1`. torch 1.13 has limited MPS op coverage.                                                                                                                                | Default to **CPU**. MPS is an experiment (§6.7).                                                         |
| NLST in IDC: 26,254 CT patients, public, CC BY 4.0, no login. The `idc-index` package downloads single series from public S3 via `s5cmd`.                                                                                                       | No account and no bulk download.                                                                         |
| Filtering for axial (`OPA`) series ≤2.5 mm, ≤150 MB, picking the thinnest per study, leaves 66,558 exams from 24,163 patients. Median series is **82.7 MB** (p90 123 MB).                                                                       | ~5–15 s download per person on normal broadband.                                                         |
| The paper picks "the thinnest series ≤2.5 mm" per exam.                                                                                                                                                                                         | Mirror this rule (with a size cap).                                                                      |
| Sybil's NLST split: 9,646 train / 2,336 dev / 2,203 test participants. Test came from Ardila et al.                                                                                                                                             | ~45% of NLST CT participants were used to train or tune Sybil. See §5.6 for how we handle this honestly. |
| Upstream regression test: the demo scan must give `[0.02163, 0.03857, 0.07192, 0.07927, 0.09585, 0.13568]`.                                                                                                                                     | This is our install smoke test.                                                                          |

---

## 4. Architecture

```
┌──────────────────────────── MacBook Pro ─────────────────────────────┐
│                                                                      │
│  frontend/  (Vite + React + TS + Tailwind v4 + shadcn/ui)            │
│     │   fetch JSON / images,  EventSource for live progress          │
│     ▼                                                                │
│  backend/   (FastAPI, Python 3.10, single inference worker)          │
│     ├── data.py      IDC index + NLST clinical → candidates          │
│     ├── fetch.py     idc-index download of ONE series → tmp/         │
│     ├── runner.py    sybil.Serie + Sybil ensemble (+ progress)       │
│     ├── render.py    slices / overlays / coronal map → WebP          │
│     ├── jobs.py      queue + SSE events                              │
│     └── cache/       small per-patient artifacts (~5–10 MB each)     │
│                                                                      │
│  ~/.sybil/           Sybil weights (~700 MB, one-time)               │
│  ~/.local/share/IDC  IDC index + clinical tables (one-time)          │
└──────────────────────────────────────────────────────────────────────┘
        ▲ per-scan download (~83 MB, deleted after processing)
        │
   NCI Imaging Data Commons, public AWS bucket (NLST, CC BY 4.0)
```

Repo layout:

```
sybil-explorer/
├── MVP.md
├── Makefile                 # setup / pool / dev / test
├── backend/
│   ├── pyproject.toml
│   ├── app/{main,config,data,fetch,runner,render,jobs,cache,schemas}.py
│   ├── scripts/{smoke_test,build_candidates,prepare_pool}.py
│   └── tests/
└── frontend/
    └── src/{pages,components,lib,hooks}/
```

---

## 5. Data

### 5.1 Source: NLST via Imaging Data Commons

`idc-index` (≥0.12, Python ≥3.10) ships a DuckDB-queryable index of every DICOM series and downloads exactly what you select. No authentication.

```python
from idc_index import IDCClient
client = IDCClient()
client.download_dicom_series(seriesInstanceUID=uid, downloadDir=tmp, dirTemplate=None)
```

Outcomes come from IDC's public NLST clinical tables:

```python
client.fetch_index("clinical_index")          # one-time download of clinical tables
prsn = client.get_clinical_table("nlst_prsn") # participant table; join on dicom_patient_id == PatientID
```

**Columns we expect** (names per the CDAS NLST participant dictionary):

| Column                             | Meaning                                |
| ---------------------------------- | -------------------------------------- |
| `scr_days0/1/2`                    | Days from randomization to each screen |
| `candx_days`                       | Days to first lung-cancer diagnosis    |
| `cancyr`                           | Study year of diagnosis                |
| `fup_days`                         | Days to last known alive               |
| `lung_cancer`                      | Confirmed lung cancer (0/1)            |
| `age`, `gender`, `pkyr`, `cigsmok` | Shown on the person card               |

TCIA/IDC distribute a _subset_ of NLST clinical data. **M0 must print the actual `nlst_prsn` columns** and adapt (see §10). If timing columns are missing, fall back to yes/no outcome only.

### 5.2 Candidate selection (no downloads needed)

NLST encodes acquisition info in `SeriesDescription`, e.g. `2,OPA,GE,HSQX,BONE,260,2.5,120,…`. Field 1 is the screening round (T0/T1/T2). Field 2 is the series kind: `OPA` is an axial scan, `OPL` a localizer. Field 7 is the slice thickness.

This parsing is derived from observed data, so the backend must re-check the real `SliceThickness` from the DICOM after download. `sybil.Serie` already rejects >5 mm.

```sql
WITH s AS (
  SELECT PatientID, StudyInstanceUID, SeriesInstanceUID,
         TRY_CAST(split_part(SeriesDescription, ',', 1) AS INT)    AS study_yr,
         split_part(SeriesDescription, ',', 2)                     AS kind,
         TRY_CAST(split_part(SeriesDescription, ',', 7) AS DOUBLE) AS thickness_mm,
         instanceCount, series_size_MB, Manufacturer
  FROM index WHERE collection_id = 'nlst' AND Modality = 'CT'
), ok AS (
  SELECT * FROM s
  WHERE kind = 'OPA' AND thickness_mm BETWEEN 1.0 AND 2.5
    AND series_size_MB <= 150 AND instanceCount >= 80
), best AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY StudyInstanceUID
                               ORDER BY thickness_mm, series_size_MB) AS rk
  FROM ok
)
SELECT * FROM best WHERE rk = 1;
```

`scripts/build_candidates.py` runs this, joins `nlst_prsn`, computes labels (§5.3), and writes `backend/data/candidates.parquet`. This takes seconds and is tiny on disk.

### 5.3 Outcome labels: replicate Sybil's own logic

Port `sybil/datasets/nlst.py::get_label` exactly, so "what happened" matches how Sybil was evaluated:

```python
def nlst_label(row, screen_yr, max_followup=6):
    days_since_rand = row[f"scr_days{screen_yr}"]
    days_to_cancer  = row["candx_days"] - days_since_rand
    years_to_cancer = int(days_to_cancer // 365) if row["candx_days"] > -1 else 100
    years_to_last_fu = int(row["fup_days"] - days_since_rand) // 365
    cancer_within_6y = years_to_cancer < max_followup
    return {
        "cancer_within_6y": cancer_within_6y,
        "years_to_cancer": years_to_cancer if cancer_within_6y else None,   # 0 = within 1st year
        "years_followed": min(years_to_last_fu, max_followup - 1) + 1,
    }
```

Treat missing values (NaN / `.N`) as "no diagnosis" or "unknown follow-up", and exclude rows whose `scr_days{T}` is missing (Sybil does the same via `check_label`).

### 5.4 Curated pool, live mode and reference sample

Only ~4% of screened people develop lung cancer within six years, so pure random picks would almost always be "healthy, low risk". The demo makes this explicit:

| Set                  | Built by                         | Default size                   | Purpose                                                                     |
| -------------------- | -------------------------------- | ------------------------------ | --------------------------------------------------------------------------- |
| **Curated pool**     | `prepare_pool.py --pool 16`      | 16 (8 cancer-within-6y, 8 not) | Instant demo. "Random person" picks from here.                              |
| **Reference sample** | `prepare_pool.py --reference 12` | 12, _unbalanced_ random        | Defines "typical participant" on the risk chart.                            |
| **Live mode**        | UI toggle                        | n/a                            | Picks any candidate, downloads, runs Sybil live, then adds it to the cache. |

The UI states plainly: _"This demo deliberately includes more people who developed cancer than a real screening population would, so there's something to see."_

**One-time cost** with the defaults: ≈ 700 MB weights + 28 × ~83 MB ≈ 2.3 GB of scan downloads. These are processed and deleted one by one.

### 5.5 Storage budget (nothing huge stays on disk)

For each processed patient, keep only:

```
cache/patients/{pid}_T{yr}/
  meta.json        # person card, series info, timings
  result.json      # calibrated + raw per-model scores, slice attention, hotspot
  outcome.json     # served only on reveal
  slices/000.webp …  # 512×512 lung-window, q≈80   (~3–6 MB total)
  overlay/000.webp … # attention heat-map RGBA     (~1–2 MB total)
  coronal.webp     # aspect-correct coronal map
```

DICOMs go to `cache/tmp/` and are deleted as soon as `result.json` is written. An LRU cap (`CACHE_MAX_MB=1500`) evicts the oldest live-mode patients first. Curated and reference patients are pinned.

### 5.6 Honesty about training data

Roughly 45% of NLST CT participants were in Sybil's training or development sets. The public repo doesn't ship the split, so the app can't tell which demo patients Sybil has "seen". Handle this as follows:

1. **Seed the pool from the 26 NLST series the authors use in `tests/regression_test.py`** (variable `nlst_test_series_uids`). The name suggests held-out scans, but this is unconfirmed, so label it that way.
2. Show a persistent, friendly note in the scoreboard and About:
   _"Some of these people may have been part of the data Sybil learned from. The published accuracy numbers come from people it had never seen."_
3. Use **published** metrics (§7.3) as the headline. The cohort scoreboard is illustrative only (n is tiny).
4. _Stretch:_ if the Ardila et al. NLST test-split IDs can be obtained, restrict live mode to them and drop the caveat.

### 5.7 Offline fallback

Upstream's demo scan (`examples/utils.py::get_demo_data`, Dropbox zip) has no outcome. It is used for the smoke test and as an "offline demo" person with the reveal disabled.

---

## 6. Backend

### 6.1 Environment

```bash
brew install uv            # or: curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.10
cd backend && uv sync      # uses pyproject below
uv run python scripts/smoke_test.py     # downloads weights (~700 MB) + demo scan, checks scores
```

`backend/pyproject.toml` (essentials):

```toml
[project]
name = "sybil-explorer-backend"
requires-python = "==3.10.*"
dependencies = [
  "sybil @ git+https://github.com/reginabarzilaygroup/Sybil.git@d9fc81b93c1c6239a570c1c570c1f2a2e6266a4a",
  "idc-index>=0.12",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sse-starlette>=2.1",
]
```

**Smoke test:** load `Sybil("sybil_ensemble", device="cpu")`, run the demo scan, and assert each score matches the upstream expected vector with `rel_tol=1e-4`. Also log wall-clock time per stage, which sets the UX budget.

### 6.2 Sybil runner: real model, with per-stage progress

`Sybil.predict()` runs all five models with no callback. To animate "5 models vote", re-implement its loop using the same internals. The commit is pinned, so the private methods are stable. A unit test asserts byte-equal output against `model.predict()`.

```python
# app/runner.py
import os, time, numpy as np, torch
from sybil import Sybil, Serie

MODEL = Sybil("sybil_ensemble", device="cpu")   # load once at startup
torch.set_num_threads(min(8, os.cpu_count()))

def run_sybil(dicom_paths, emit):
    t0 = time.time()
    emit("reading", detail=f"{len(dicom_paths)} slices")
    serie = Serie(dicom_paths)                  # sorts slices, checks thickness, reads spacing

    emit("standardizing")
    serie.get_volume()                          # lru_cached → reused by every model

    raw_per_model, att_per_model = [], []
    for k, net in enumerate(MODEL.ensemble):
        emit("model", index=k + 1, of=len(MODEL.ensemble))
        pred = MODEL._predict(net, [serie], return_attentions=True)
        raw_per_model.append(pred.scores)        # [[6 floats]]
        att_per_model.append(pred.attentions)

    emit("calibrating")
    raw = np.mean(np.array(raw_per_model), axis=0)   # identical to Sybil.predict
    calibrated = MODEL._calibrate(raw)[0].tolist()
    attentions = {key: np.stack([a[0][key] for a in att_per_model])
                  for key in att_per_model[0][0].keys()}
    return serie, calibrated, np.array(raw_per_model)[:, 0, :], attentions, time.time() - t0
```

Notes:

- `per-model raw` scores are **uncalibrated**. If shown at all (stretch), label them "raw votes".
- A single inference worker (one thread, FIFO queue) avoids running two 3D CNNs at once. Peak RAM is a few GB, because the stem activation alone is 64×200×128×128 floats ≈ 0.84 GB.

### 6.3 Job pipeline and live progress (SSE)

`POST /api/patients/{id}/run` returns `job_id`. `GET /api/jobs/{job_id}/events` streams:

| event           | payload                  | UI text                                  |
| --------------- | ------------------------ | ---------------------------------------- |
| `queued`        | position                 | "Waiting for Sybil…"                     |
| `downloading`   | bytes_done / bytes_total | "Fetching the scan (83 MB)…"             |
| `reading`       | n_slices                 | "Reading 154 slices…"                    |
| `standardizing` | —                        | "Making every scan look alike…"          |
| `model`         | index, of                | "Expert 3 of 5 is looking…"              |
| `calibrating`   | —                        | "Turning votes into honest percentages…" |
| `rendering`     | —                        | "Preparing the pictures…"                |
| `done`          | patient_id               | —                                        |
| `error`         | message, stage           | friendly message + retry                 |

Curated and reference patients skip straight to `done` (already cached).

### 6.4 Rendering

- **Slices:** `serie.get_raw_images()` returns the lung-windowed 0–255 slices exactly as Sybil sees them before resizing. Save each as WebP.
- **Coronal map:** take the middle coronal plane of the stacked slices and resize the z-axis by `SliceThickness / PixelSpacing` so the chest isn't squashed. Draw the current-slice line client-side.
- **Attention:**
     - Use `exp(log-attention)` averaged over the 5 models, image attention × volume attention. This is what `sybil.collate_attentions` does.
     - Per-slice importance = sum over each slice. This drives the strip chart, and its argmax is the "hotspot" slice.
     - Overlays use a perceptual colormap (e.g. magma) with alpha ∝ attention, rendered as transparent WebP.
- **⚠ Alignment check (must do in M2):**
     - Upstream `collate_attentions` linearly stretches the 25×16×16 attention grid over the _original_ N×512×512 slices.
     - But `Serie.get_volume()` first resamples to 2.5 mm spacing and **center-pads/crops to 200 slices and 256×256**. A typical 300–350 mm scan becomes ~120–140 slices padded to 200.
     - So the upstream overlay is likely offset in z (and slightly in-plane when the field of view ≠ 360 mm).
     - Implement `map_attention_to_original()`. Each z bin covers 8 slots of the 200-slot volume; subtract the pad offset (or add the crop offset) to get a resampled index; multiply by `2.5 / SliceThickness` to get the original slice index. Do the same in-plane with `PixelSpacing / 0.703125` on the 256 grid.
     - Use Sybil's own spacing assumption (`SliceThickness` tag), not recomputed slice positions.
     - Unit-test the mapping: push a synthetic volume with a bright cube through the same torchio `Resample` + `CropOrPad`, and check the inverse mapping lands on the cube. Confirm torchio's padding split for odd sizes.
     - If the upstream visualizer turns out to be correct, keep it and delete this section.

### 6.5 API

| Method & path                                 | Returns                                                                |
| --------------------------------------------- | ---------------------------------------------------------------------- |
| `GET /api/health`                             | model loaded, device, weights present, cache MB, pool/reference counts |
| `GET /api/patients/random?mode=curated\|live` | person card (no outcome) + `ready` flag                                |
| `GET /api/patients/{id}`                      | person card + series info                                              |
| `POST /api/patients/{id}/run`                 | `{job_id}` (or `{ready: true}` if cached)                              |
| `GET /api/jobs/{job_id}/events`               | SSE stream (§6.3)                                                      |
| `GET /api/patients/{id}/result`               | 6 calibrated risks, slice attention, hotspot, timings, reference curve |
| `GET /api/patients/{id}/slices/{i}.webp`      | CT slice                                                               |
| `GET /api/patients/{id}/overlay/{i}.webp`     | attention overlay                                                      |
| `GET /api/patients/{id}/coronal.webp`         | coronal map                                                            |
| `GET /api/patients/{id}/outcome`              | the reveal (kept separate so the client can't peek early)              |
| `GET /api/cohort`                             | all prepared patients: 6-yr risk + outcome (scoreboard)                |

### 6.6 Person card fields

Show: age, sex, smoking status, pack-years, screening round (`T0` = first screen), scanner manufacturer, number of slices. Show the de-identified NLST ID truncated, e.g. "Participant #2188…".

Never show: real dates. NLST dates are shifted anyway.

### 6.7 Performance on a MacBook

- **Baseline:** CPU, torch 1.13.1, threads = min(8, cores). M0 measures the real time. Design the UX for **1–4 minutes** of inference in live mode; the curated pool makes the default path instant.
- **Experiment (stretch, gated):** a second env using a `uv` override to torch 2.x with `PYTORCH_ENABLE_MPS_FALLBACK=1`. Adopt it **only if** the smoke-test scores still match within 1e-4 and it is faster.
- **Caching:** results are deterministic for a given scan and weights, so never recompute a cached patient.

---

## 7. Frontend

### 7.1 Setup

```bash
pnpm dlx shadcn@latest init -t vite        # Vite + React + TS + Tailwind v4
pnpm dlx shadcn@latest add button card badge tabs slider progress tooltip hover-card \
  dialog sheet skeleton sonner chart toggle separator alert accordion switch
pnpm add @tanstack/react-query motion lucide-react
```

`vite.config.ts` proxies `/api` → `http://localhost:8000`. Charts use shadcn `chart` (Recharts v3; colors via `var(--chart-n)`).

### 7.2 Screens and components

One scrolling page with anchored sections (works as a guided story; also deep-linkable).

**① Hero / "How it works"**

- Headline: _"Can a computer spot lung cancer years before it appears?"_
- Three `Card`s with icons: 📷 _One ordinary CT scan_ → 🧠 _Sybil studies all ~150 slices_ → 📈 _Risk for each of the next 6 years_.
- An `Accordion` "Want to know more?" with 4 short plain-language paragraphs (no tensors).
- First-run state: if weights are missing, an `Alert` with download progress.

**② Meet a person**

- A large _🎲 Pick a random person_ `Button`, plus a `Switch` for "Live mode (downloads a new scan, takes a few minutes)".
- Person `Card` with `Badge`s (age, sex, smoking, screening round).
- Sealed outcome card (blurred, lock icon): _"We'll reveal what happened after Sybil makes its prediction."_

**③ The scan**

- `<canvas>` viewer: wheel/drag to scroll, a `Slider` scrubber and a ▶ cine `Toggle`.
- Coronal map on the side with a moving line; click to jump.
- `HoverCard` glossary on terms such as "slice", "low-dose CT" and "nodule".
- Overlay `Switch` (disabled until Sybil has run).

**④ Run Sybil**

- Big _Run Sybil_ button → stepper driven by SSE (`Progress` for the download).
- Five round avatars "Expert 1…5" that fill in as each model finishes.
- Elapsed timer. `Skeleton`s for the upcoming results.

**⑤ The prediction**

- Headline number for year 6 (count-up animation via `motion`), with a sub-line: _"About 14 in 100 people with a scan like this are diagnosed within 6 years."_
- **Risk curve** (`chart`, area/line): 6 points for this person, plus a dashed "typical participant" line (median of the reference sample). Tooltip per year: _"By year 3: 7.2%"_.
- **Icon array**: 100 small person icons, filled count = round(6-year risk × 100).
- **Relative band** `Badge`: _Lower / Typical / Higher / Much higher than typical_, computed against the reference sample's percentiles. Never phrase it as a diagnosis.

**⑥ Where Sybil looked**

- Turns on the overlay automatically.
- Attention strip (small bar chart under the scrubber, one bar per slice), clickable.
- _Jump to hotspot_ button.
- Caption: _"Brighter = where Sybil paid most attention. During training it was taught to look at the same places radiologists marked."_

**⑦ What actually happened**

- Flip animation on the sealed card. On the risk curve, a vertical marker at the diagnosis year, or a shaded "followed up, cancer-free" range.
- Copy is chosen per outcome (see §8). Includes a reminder that a high risk is not a diagnosis, and a low risk is not a guarantee.

**⑧ Scoreboard** (`Tabs`: _Published results_ | _This demo's people_)

- _Published:_ three `Card`s with plain-language AUC explanations (§7.3).
- _This demo:_ a strip/beeswarm of every prepared person's 6-yr risk, coloured by outcome, with the current person highlighted. Includes the training-data caveat (§5.6) and "n is tiny".

**Footer / About:** what Sybil is, MIT licence, citation, NLST attribution (CC BY 4.0), "Research demo — not medical advice".

### 7.3 Published performance (headline numbers, from the JCO 2023 paper)

| Dataset                                      | 1-year AUC | 6-year C-index |
| -------------------------------------------- | ---------- | -------------- |
| NLST test (2,203 people, unseen in training) | 0.92       | 0.75           |
| Mass General Hospital                        | 0.86       | 0.81           |
| Chang Gung Memorial (Taiwan)                 | 0.94       | 0.80           |

Plain-language explainer for the UI:

> _"Take one person who was diagnosed within a year and one who wasn't. 92 times out of 100, Sybil gives the person who got cancer the higher risk."_

### 7.4 Visual language

- **Risk colours:** a calm sequential scale (teal → amber → deep orange). Avoid pure red for "high". Colour never carries meaning alone; always pair it with a label or number.
- **Outcome colours:** neutral slate for "no cancer", a single accent for "cancer". Same in light and dark mode.
- **Scan:** grayscale on a near-black panel. The overlay is a perceptual colormap with an opacity slider.
- **Motion:** used for meaning only (votes filling in, count-up, reveal flip). Respect `prefers-reduced-motion`.
- **Layout:** responsive down to laptop widths. The viewer and charts stack vertically on narrow screens.

### 7.5 State

- TanStack Query for REST, plus a small `useJobEvents(jobId)` hook wrapping `EventSource`.
- Current person in the URL (`?p=218892_T1`) so a specific person can be shared or re-demoed.
- Preload ±10 slice images around the cursor; lazy-load the rest.

---

## 8. Copy guardrails

- Always use absolute numbers ("14 in 100") alongside percentages.
- Say "risk" and "chance", never "Sybil says you have cancer".
- **Cancer reveal:** _"This person was diagnosed with lung cancer about {n} year(s) after this scan. Sybil's risk for that year was {x}%, {higher/lower} than for a typical participant."_
- **No-cancer reveal:** _"This person had no lung-cancer diagnosis during {y} years of follow-up."_
- When the prediction "missed", say so plainly. It builds trust: _"Not every case is caught. Sybil rated this person as typical risk."_
- A persistent footer reads: _"Research demonstration using public, de-identified trial data. Not for medical decisions."_

---

## 9. Milestones and acceptance criteria

| #   | Milestone                         | Done when                                                                                                                                                                                                    |
| --- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| M0  | **Environment and facts**         | `uv sync` works on Apple Silicon. `smoke_test.py` reproduces upstream scores (rel 1e-4) and logs per-stage timings. `nlst_prsn` columns are printed and the label fields confirmed (or the fallback chosen). |
| M1  | **Data layer**                    | `build_candidates.py` writes `candidates.parquet` (≥10k candidates with outcomes). Fetching one series by UID works and the temp dir is cleaned up.                                                          |
| M2  | **Runner and rendering**          | Running one patient end-to-end produces `meta/result/outcome.json` plus WebPs, under ~15 MB per patient. Runner output equals `Sybil.predict()`. The attention-alignment test passes.                        |
| M3  | **API and jobs**                  | All endpoints from §6.5 work. SSE streams every stage. A second request queues correctly. Cache eviction works.                                                                                              |
| M4  | **Pool**                          | `prepare_pool.py --pool 16 --reference 12` completes unattended and is resumable. The cohort endpoint returns 28 people.                                                                                     |
| M5  | **Frontend story**                | Sections ①–⑦ work against the curated pool, with no layout shift and no console errors.                                                                                                                      |
| M6  | **Live mode, scoreboard, polish** | Live mode runs a fresh patient with progress. The scoreboard, glossary, About and accessibility pass (keyboard, contrast, reduced motion) are done.                                                          |

`make dev` runs uvicorn (:8000) and Vite (:5173) together. `make pool` runs M4. `make test` runs the smoke test and unit tests.

---

## 10. Verify early (open questions)

1. **Clinical columns:** exact names in IDC's `nlst_prsn` (e.g. `candx_days`, `fup_days`, `scr_days0-2`, `lung_cancer`, `pkyr`) and how missing values are coded.
2. **Inference time** on the target Mac (CPU), and whether the torch 2.x + MPS variant is both identical and faster.
3. **Attention alignment** (§6.4). Is the upstream overlay offset in z and in-plane?
4. **SeriesDescription parsing:** spot-check ~20 downloaded series to confirm field 7 matches the DICOM `SliceThickness`.
5. **Clinical index size and the one-time download time** for `fetch_index("clinical_index")`. Show progress on first run if it's slow.
6. **Held-out patients:** can Sybil's NLST test split (Ardila et al.) be obtained?

---

## 11. References

- Sybil code (MIT): https://github.com/reginabarzilaygroup/Sybil (pinned `main@d9fc81b`)
- Mikhael et al., _Sybil: a validated deep learning model to predict future lung cancer risk from a single low-dose chest CT_, J Clin Oncol 2023. https://cap.csail.mit.edu/sites/default/files/research-pdfs/Sybil2023.pdf
- NLST on TCIA (CC BY 4.0): https://www.cancerimagingarchive.net/collection/nlst/
- NCI Imaging Data Commons / `idc-index`: https://pypi.org/project/idc-index/
- NLST participant data dictionary (CDAS): https://cdas.cancer.gov/datasets/nlst
- shadcn/ui (Vite install, charts): https://ui.shadcn.com/docs/installation/vite · https://ui.shadcn.com/docs/components/chart

**Attribution required by NLST's licence:** National Lung Screening Trial Research Team. (2013). Data from the National Lung Screening Trial (NLST) [Data set]. The Cancer Imaging Archive. https://doi.org/10.7937/TCIA.HMQ8-J677
