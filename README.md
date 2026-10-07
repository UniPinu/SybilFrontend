# Sybil Explorer

An interactive, beginner-friendly showcase of **Sybil**, the MIT/MGH deep-learning model that predicts
a person's lung-cancer risk for the next six years from a **single low-dose chest CT scan**.

The app really runs Sybil. It picks a real, de-identified participant from the National Lung Screening
Trial (NLST), fetches that one scan from the NCI Imaging Data Commons, runs the five-model ensemble on
this machine, shows where the model looked, and then reveals what actually happened to that person.

Implements [MVP.md](MVP.md). Section numbers below refer to it.

---

## What you need

| | |
|---|---|
| Python | 3.10 (installed for you by `uv`) |
| Node | 20+ with `pnpm` |
| Disk | ~700 MB model weights, ~100 MB IDC index, 4-13 MB per prepared person |
| Network | public; no account and no credentials for IDC |
| OS | Windows x64 or Apple Silicon macOS (see [Platforms](#platforms)) |

## Setup

```bash
# Windows (PowerShell)
.\tasks.ps1 setup
.\tasks.ps1 pool          # ~45 min: 28 people, one scan at a time
.\tasks.ps1 dev

# macOS / Linux with make
make setup
make pool
make dev
```

`setup` installs both halves, downloads Sybil's checkpoints and **verifies the install against the
score vector the Sybil authors publish for their demo scan**, then builds the candidate list. Nothing
below that point will produce a number until the smoke test passes.

`dev` serves the API on <http://localhost:8000> and the UI on <http://localhost:5173>. Alternatively,
`make build` writes `frontend/dist`, which the backend then serves itself on port 8000.

### Step by step, if you prefer

```bash
cd backend
uv sync --extra dev
uv run python scripts/smoke_test.py          # weights + install check (M0)
uv run python scripts/inspect_data.py        # what IDC actually publishes (M0)
uv run python scripts/build_candidates.py    # 66k candidate exams (M1)
uv run python scripts/prepare_pool.py --pool 16 --reference 12   # (M4)
uv run uvicorn app.main:app --port 8000 --reload

cd ../frontend
pnpm install && pnpm dev
```

---

## What it does

```
frontend/  Vite + React + TS + Tailwind v4 + shadcn/ui
   |  fetch JSON / WebP images, EventSource for live progress
   v
backend/   FastAPI, Python 3.10, one inference worker
   |-- data.py       candidates + person cards + cohort
   |-- fetch.py      idc-index download of ONE series -> cache/tmp
   |-- runner.py     sybil.Serie + the five-model ensemble, with progress
   |-- attention.py  maps the attention grid back onto the original slices
   |-- render.py     slices / overlays / coronal map -> WebP
   |-- pipeline.py   fetch -> verify -> run -> render -> cache
   |-- jobs.py       FIFO queue + SSE
   `-- cache/        ~3-6 MB per patient; DICOMs deleted after processing
```

One scan at a time, ~83 MB median, deleted as soon as `result.json` is written. The full dataset is
never downloaded.

### The page

One scrolling story: how it works -> meet a person -> look at the scan -> run Sybil (five experts
voting, live) -> the prediction (headline number, 1-6 year curve, 100-person icon array) -> where
Sybil looked (overlay + per-slice attention strip) -> what actually happened -> scoreboard.

---

## Verified facts (M0)

Everything in MVP.md section 10 was checked against the real thing on this machine.

**Install.** `main@d9fc81b` reproduces the published demo scores exactly:
`[0.02163, 0.03857, 0.07192, 0.07927, 0.09585, 0.13568]`, matching to `rel_tol=1e-4` (upstream's own
test uses 1e-6 and that passes too). `scripts/smoke_test.py --compare-runner` additionally proves our
staged runner returns bit-identical scores to `Sybil.predict()`.

**Inference time** (i7-13700K, CPU, 194-slice demo scan, per model): 8 threads 24.8 s, 12 -> 17.2 s,
16 -> 14.6 s, 24 -> 13.0 s, **with identical scores at every setting**. Upstream defaults to
`min(8, cpu_count)` with a comment that more never helps; it does here, so the default is
`min(16, cpu_count)`, overridable with `SYBIL_THREADS`. A full run is ~80-110 s end to end including
the download and rendering, rather than the 1-4 minutes MVP.md budgeted for.

**IDC clinical columns.** `nlst_prsn` as IDC publishes it is a *subset* of the CDAS participant table.
It has `scr_days0/1/2`, `candx_days`, `cancyr`, `canc_free_days`, `age`, `gender`, `race`, `cigsmok`,
`de_stag`. It does **not** have `fup_days`, `lung_cancer` or `pkyr`. So, as MVP.md section 5.1
instructs:

* `canc_free_days` ("last known to be free of lung cancer") replaces `fup_days`. For the question this
  app asks it is the more direct denominator anyway.
* A non-empty `candx_days` *is* the diagnosis flag, which is exactly the test Sybil's own
  `get_label` applies. (`canc_rpt_link` covers only 969 of the 2,058 diagnosed participants, so it is
  not usable.)
* Pack-years are not shown anywhere. The UI states the cohort-level fact instead: every participant was
  55-74 with at least 30 pack-years.
* Missing values are **empty strings**, not NaN and not -1.

**Candidate counts.** The MVP's numbers reproduce exactly: 203,087 NLST CT series from 26,254 patients
in the index; filtering to axial `OPA` series 1.0-2.5 mm, <=150 MB, >=80 instances and taking the
thinnest per study gives 66,558 exams from 24,163 participants; after applying Sybil's own
`check_label`/`skip_sample` exclusions, **66,332 candidate exams from 24,094 participants**, 2,074 of
them diagnosed within six years (3.1%). Median series 82.7 MB, p90 123.3 MB.

**SeriesDescription parsing** (`2,OPA,GE,LSPLUS,LUNG,360,2.5,120,...`) holds on real rows: field 1 is
the screening round, 2 the series kind, 5 the kernel, 6 the reconstruction FOV, 7 the slice thickness.
Spot-checked against the DICOM headers of the first 15 downloaded series: **0 thickness mismatches**,
and the index's `instanceCount` matched the downloaded file count every time. The pipeline still
re-reads `SliceThickness` after download and logs any disagreement, because the parsing is derived
from observed data rather than a spec.

Those 15 scans also show why the alignment work matters: pixel spacing ranged 0.566-0.820 mm, so the
in-plane crop/pad offset ranged from -8 (cropped) to +25 (padded) pixels, and the z offset from +6 to
+40 slots.

**19 of the 26** series in upstream's `tests/regression_test.py` survive the candidate filter; the pool
is seeded from those first (MVP.md section 5.6). All 19 happen to be people who were *not* diagnosed,
so they seed only the cancer-free half.

### The attention overlay really was misaligned (section 6.4)

`sybil.utils.visualization.collate_attentions` stretches the 25x16x16 attention grid linearly over the
original N x 512 x 512 slices. The model never saw those slices: `Serie.get_volume()` resizes each
slice to 256x256, resamples the volume to 0.703125 x 0.703125 x 2.5 mm, then centre-pads or crops to
exactly 256 x 256 x 200. A 150-slice 2.5 mm scan therefore sits in slots 25..174 of 200, so the
upstream overlay is both shifted (~25 slots, ~60 mm) and stretched (200/150) in z.

`app/attention.py` inverts the real chain instead. Every step is an axis-aligned affine map in index
space:

1. `cv2.resize` 512 -> 256, half-pixel convention
2. `tio.Resample`: `new = (old + 0.5) * (old_spacing / new_spacing) - 0.5`, size `ceil(size * ratio)`
3. `tio.CropOrPad`: index shift of `+/- ceil(diff / 2)` — torchio puts the larger half on the
   **initial** side, including for odd differences
4. attention pooling: 8x in z, 16x in plane, `align_corners=False`

`tests/test_attention_alignment.py` pushes a synthetic bright cube through the *real* torchio
transforms for six scan geometries and checks the inverse mapping lands back on the cube (within 0.75
voxels), pins down the odd-difference pad/crop split against torchio itself, checks that slices cropped
out of the model's view get no attention, and demonstrates the upstream offset.

**End to end, measured on this machine**: a live person (never seen before) is picked, downloaded
(83-134 MB), run through all five models and rendered in **83-112 seconds**, with every progress stage
streaming to the browser. The 28-person pool took 42.7 minutes unattended and occupies 195 MB.

---

## Platforms

MVP.md targets Apple Silicon. This implementation also runs on Windows x64, which is where it was
built and verified.

Sybil's `setup.cfg` pins `torch==1.13.1+cu117` when `platform_machine == "x86_64"` — a wheel that does
not exist for macOS, and that `uv`'s universal resolver trips over. Windows reports `AMD64`, so it
takes the `!= "x86_64"` branch and installs the plain PyPI wheels, exactly as Apple Silicon does.
`backend/pyproject.toml` therefore restricts resolution to those two platforms:

```toml
[tool.uv]
environments = [
  "sys_platform == 'darwin' and platform_machine == 'arm64'",
  "sys_platform == 'win32' and platform_machine == 'AMD64'",
]
```

Linux or an Intel Mac needs `tool.uv.override-dependencies` plus the PyTorch cu117 index.

**CPU only.** The PyPI `torch==1.13.1` Windows wheel is CPU-only. There is an RTX 4090 in this machine,
but torch 1.13's cu117 build predates sm_89 and would not run on it, so CUDA is not an option without
moving off the pinned torch. MVP.md's MPS experiment (section 6.7) is macOS-only and was not attempted.
CPU is fast enough: ~80 s for the full ensemble.

---

## API

| Method & path | Returns |
|---|---|
| `GET /api/health` | model loaded, device, weights present, cache MB, pool/reference counts |
| `GET /api/patients/random?mode=curated\|live` | person card (no outcome) + `ready` flag |
| `GET /api/patients/{id}` | person card + series info |
| `POST /api/patients/{id}/run` | `{job_id}`, or `{ready: true}` if cached |
| `GET /api/jobs/{job_id}/events` | SSE: `queued, downloading, reading, standardizing, model, calibrating, rendering, done, error` |
| `GET /api/patients/{id}/result` | 6 calibrated risks, slice attention, hotspot, timings, reference curve |
| `GET /api/patients/{id}/slices/{i}.webp` | CT slice |
| `GET /api/patients/{id}/overlay/{i}.webp` | attention overlay (RGBA) |
| `GET /api/patients/{id}/coronal.webp` | coronal map |
| `GET /api/patients/{id}/outcome` | the reveal, kept separate so the client cannot peek early |
| `GET /api/cohort` | every prepared person: 6-year risk + outcome |

Interactive docs at <http://localhost:8000/docs>.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SYBIL_THREADS` | `min(16, cpu_count)` | torch CPU threads |
| `SYBIL_DEVICE` | `cpu` | passed straight to `Sybil(device=...)` |
| `SYBIL_EAGER_MODEL` | `1` | load the ensemble at startup instead of on first use |
| `CACHE_DIR` | `backend/cache` | processed patients and in-flight DICOMs |
| `CACHE_MAX_MB` | `1500` | LRU cap; pool and reference people are pinned |
| `DATA_DIR` | `backend/data` | where `candidates.parquet` lives |
| `SLICE_QUALITY` | `80` | WebP quality for the slices |
| `SLICE_TARGET_MB` | `12` | per-patient size target; quality steps down to meet it |
| `SLICE_QUALITY_FLOOR` | `50` | never go below this, however noisy the scan |
| `OVERLAY_FLOOR` | `0.12` | attention below this fraction of the scan's peak is transparent |

Low-dose CT is noisy, and noise is what costs bytes: at quality 80 a quiet scan compresses to ~14 KB
per slice and a noisy one to ~75 KB, so a 250-slice scan reached 22 MB before this was added. The
renderer now measures the middle slice and steps the quality down until the patient fits
`SLICE_TARGET_MB`. Across the 28 prepared people that gives a **median of 5.8 MB and a mean of 7.0
MB**; the single noisiest 249-slice scan still lands at 16.3 MB, because quality stops at the floor
rather than smudging a scan that is genuinely full of detail. `result.json` also carries the 25x16x16
attention grid (~100 KB), so the overlays can be redrawn later without another inference pass.

---

## Tests

```bash
.\tasks.ps1 test-fast     # 83 tests, no model and no network, ~15 s
.\tasks.ps1 test-slow     # runs the real ensemble on the demo scan, ~2 min
.\tasks.ps1 test          # both, plus the runner-vs-upstream comparison
```

* `test_attention_alignment.py` — the geometry work above, against real torchio.
* `test_runner_parity.py` — our staged runner vs `Sybil.predict()`, bit-for-bit, with a stub ensemble
  and the real calibrator; plus a slow test on the real weights.
* `test_labels.py` — the outcome labels, ported from `sybil/datasets/nlst.py`, including every
  exclusion `skip_sample` makes.
* `test_api.py` — every endpoint, the job queue, SSE stage by stage, cache eviction, and the rule that
  the outcome is not served before a result exists.
* `test_pipeline.py` — fetch -> verify -> render -> cache against a synthetic DICOM series: the
  windowing, the WebP artifacts, the aspect-corrected coronal map, the per-patient size budget, that
  the DICOMs are deleted, and that no outcome field reaches `meta.json` or `result.json`.

---

## Accessibility

Checked against the running app, not just asserted (`frontend/live-check.mjs` has the live-mode
equivalent):

* every one of the 44 keyboard stops on a fully loaded page has a visible focus indicator -- which
  needed two fixes: shadcn's `ChartContainer` applies `[&_.recharts-surface]:outline-hidden`, and
  `TabsContent` is tabbable without a ring;
* the slice scrubber is operable from the keyboard and announces itself -- Radix puts
  `role="slider"` on the *thumb*, so a label on the root never reached assistive tech
  (`components/ui/slider.tsx` now forwards it);
* the 173-bar attention strip is one labelled image rather than 173 tab stops; the slider and the
  *Jump to hotspot* button are its keyboard route;
* colour never carries meaning alone, and every text colour is at least 4.5:1 against its background
  in both themes (graphics at least 3:1) -- verified by converting the oklch tokens to sRGB and
  computing the contrast ratios;
* under `prefers-reduced-motion` the count-up, the vote animation and the reveal flip are off, and the
  headline renders at its final value.

## Honesty notes

These are in the UI as well, not just here.

* **Training data.** About 45% of NLST CT participants were in Sybil's training or development sets.
  The public repo does not ship the split, so the app cannot tell which demo people the model has
  already seen. The pool is seeded from the 26 series upstream calls `nlst_test_series_uids`, which
  *suggests* held-out data but is unconfirmed. The scoreboard says so, and the headline accuracy
  numbers quoted are the published ones, measured on people the model had never seen.
* **The pool is deliberately unbalanced.** Half of the curated pool was diagnosed within six years, far
  more than the real 3.1%, so that there is something to see. The reference sample is left unbalanced
  on purpose, because that is what defines "a typical participant" on the chart.
* **The cohort scoreboard is illustrative.** With 28 people, one person moving would change the
  ordering.
* **Not a detector.** The attention overlay shows where the model's weights concentrated, not a tumour
  outline.
* **`lesionsize`** exists in IDC's table but its units are not documented there, so it is not shown.
* Research demonstration using public, de-identified trial data. Not for medical decisions.

## Out of scope

Sybil-2 (multi-scan, nodule tracking) targets Linux x86_64 + CUDA with nnUNet, torch-scatter and ANTs;
installing its tags breaks `import sybil` on this platform. Uploading your own scans, training and any
clinical use are also out of scope.

## Credits

* Sybil (MIT licence), pinned at `main@d9fc81b`:
  <https://github.com/reginabarzilaygroup/Sybil>
* Mikhael, Wohlwend, Yala et al., *Sybil: a validated deep learning model to predict future lung cancer
  risk from a single low-dose chest computed tomography*, J Clin Oncol 2023.
* **NLST attribution (CC BY 4.0):** National Lung Screening Trial Research Team. (2013). Data from the
  National Lung Screening Trial (NLST) [Data set]. The Cancer Imaging Archive.
  <https://doi.org/10.7937/TCIA.HMQ8-J677>
* NCI Imaging Data Commons / `idc-index`: <https://pypi.org/project/idc-index/>
