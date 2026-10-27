# CTscannr

A research project on whether **successive** low-dose CT scans can sharpen lung-cancer risk estimates,
built on an interactive, beginner-friendly showcase of **Sybil**, the MIT/MGH deep-learning model that predicts
a person's lung-cancer risk for the next six years from a **single low-dose chest CT scan**.

The app really runs Sybil. It picks a real, de-identified participant from the National Lung Screening
Trial (NLST), fetches that one scan from the NCI Imaging Data Commons, runs the five-model ensemble on
this machine, shows where the model looked, and then reveals what actually happened to that person.

Three views:

- **Homepage**: the research question (aligning Sybil's curves from T0, T1 and T2 on one clock, and
  using the T0 → T1 offset to nudge T1 towards T2), with diagrams built from a real participant, followed
  by the original pick-a-person story.
- **Explore**: search participants and run several of their screening rounds.
- **Visualiser**: one real scan followed through every step of the model in three.js, replayed from a
  recorded run (`make visualiser`, plan in [docs/visualiser-plan.md](docs/visualiser-plan.md)).

Implements [MVP.md](MVP.md). Section numbers below refer to it.

---

## What you need

| | |
|---|---|
| Python | 3.10 (installed for you by `uv`) |
| Node | 20.19+ (or 22.12+) with `pnpm` |
| Disk | ~700 MB model weights, ~100 MB IDC index, 4-13 MB per prepared person |
| Network | public; no account and no credentials for IDC |
| OS | Windows x64 or Apple Silicon macOS (see [Platforms](#platforms)) |

## Setup

```bash
# Windows (PowerShell)
.\tasks.ps1 setup
.\tasks.ps1 pool          # ~45 min: 28 people, one scan at a time
.\tasks.ps1 dev

# macOS (Apple Silicon) with make
make setup
make pool
make dev
```

### On a Mac, from a fresh clone

Apple Silicon only (M1 or later); an Intel Mac cannot install Sybil's pinned torch.

```bash
xcode-select --install            # git and make, if you don't have them yet
brew install uv node              # Homebrew: https://brew.sh
corepack enable pnpm              # pnpm, at the version pinned in frontend/package.json

git clone git@github.com:UniPinu/SybilFrontend.git && cd SybilFrontend
make setup                        # uv installs Python 3.10 itself; ~700 MB of weights go to ~/.sybil
make pool                         # optional but recommended, see below
make dev                          # then open http://localhost:5173
```

`make setup` checks for `uv`, `node` and `pnpm` first and says what is missing.

The prepared scans (`backend/cache/`) and the candidate tables (`backend/data/*.parquet`) are not in
git. `setup` rebuilds the tables in under a minute, but the pool has to be prepared again on each
machine. If you'd rather skip that, copy `backend/cache/patients/` from a machine that already has it:
the results are plain JSON and WebP and are the same on both platforms.

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
uv run python scripts/build_candidates.py    # exams, 66k candidates, 24k participants (M1)
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
   |-- catalog.py    builds exams / candidates / participants tables
   |-- data.py       candidates + person cards + cohort
   |-- participants.py  Explore: search, multi-round runs, results over time
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

### The pages

**Story** (`/`, `?p=<exam>`): one scrolling story: how it works -> meet a person -> look at the scan
-> run Sybil (five experts voting, live) -> the prediction (headline number, 1-6 year curve,
100-person icon array) -> where Sybil looked (overlay + per-slice attention strip) -> what actually
happened -> scoreboard.

**Explore** (`?view=explore`): search all 24k participants by ID, demographics, scanner make, number
of usable rounds, diagnosis and whether anything has been run yet. A participant's page shows the
trial timeline and one card per screening round (usable, excluded and why, or missing). Tick the
rounds to run; they queue in round order, each with its own live progress. Once results exist:

* **risk curves** on one calendar: each scan's 1-6 year cumulative risk starts on its own date, with
  the diagnosis (or last cancer-free date) marked; or **one horizon** (e.g. 6-year risk) per scan;
* a table of every round's six numbers and the change since the previous round;
* the scans side by side, each opening on its attention hotspot (they are not registered to each
  other, and the page says so);
* **Export CSV**, one row per round, for analysis elsewhere.

Every view is a URL, so a filtered search or a participant can be shared. **Blind mode** hides every
outcome, so the story's predict-then-reveal works in Explore too. Any round opens in the story view.

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
thinnest per participant and round gives 66,511 exams from 24,163 participants; after applying
Sybil's own `check_label`/`skip_sample` exclusions, **66,285 candidate exams from 24,094
participants**, 2,073 of them diagnosed within six years (3.1%). Median series 82.7 MB, p90 123.3 MB.

The first build ranked series per *study*, which gave 66,332 candidates: IDC holds two studies for 47
participant-rounds (some byte-identical, one a B30f/B50f kernel pair), so those people had two
"exams" with the same id. Ranking per participant and round fixes that; `215006_T1` in the pool was
computed on the B30f copy, and its cached `meta.json` records which series it actually used.

The 226 exams Sybil's rules exclude are kept in `exams.parquet` and can still be run from Explore,
flagged and kept off the scoreboard. None is a scan taken after a diagnosis: NLST stopped screening
diagnosed people. 222 are rounds after the participant's last cancer-free date; 4 have images but no
screening date in `nlst_prsn`.

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
built and verified. Both platforms install from the same `uv.lock` and `pnpm-lock.yaml`, which include
the macOS arm64 wheels and native binaries.

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

**GPU on Windows, CPU on Macs.** On Windows, `pyproject.toml` sends `torch`/`torchvision` to the
PyTorch cu117 index, so `uv sync` installs `torch 1.13.1+cu117` (still Sybil's pinned version). CUDA 11.7
has no sm_89 kernels, but NVIDIA binaries are compatible within a major architecture, so its sm_86
kernels run on an RTX 40-series card (driver 516 or newer). Check with `.\tasks.ps1 gpu-check`. The app
itself still defaults to `SYBIL_DEVICE=cpu`, the configuration its scores were verified on; the bulk
harvest below uses the GPU and checks it against upstream's published demo scores before it starts.
MVP.md's MPS experiment (section 6.7) was not attempted, so Macs run on the CPU. Inference time on the
CPU depends on the core count: `SYBIL_THREADS` defaults to the number of cores, up to 16, which gives
~80 s for the full ensemble.

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
| `GET /api/participants` | Explore search: filters (`q, sex, smoking, race, age_min/max, rounds_min, manufacturer, diagnosed, has_results`), `sort`, paging, facet counts |
| `GET /api/participants/{nlst_pid}` | demographics, trial timeline, and each round's status, series, cache and job state |
| `POST /api/participants/{nlst_pid}/runs` | queue `{exam_ids}` (default: every runnable round) in round order |
| `GET /api/participants/{nlst_pid}/results` | every finished round on one time axis, with the change since the previous round |
| `GET /api/participants/{nlst_pid}/export.csv` | one row per finished round, for analysis |

Explore shows outcomes by default, because about 4% of participants were ever diagnosed and
finding them needs the filter. Every Explore endpoint takes `blind=true`, which drops all outcome
fields, refuses outcome filters and sorting, and replaces exclusion reasons with a neutral one. The
story page's `/api/patients/*` contract is unchanged.

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

The frontend reads two build-time variables:

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE` | empty (same origin) | where the API lives, e.g. `https://api.example.com` |
| `VITE_READ_ONLY` | unset | `1`: read the static snapshot below and never run Sybil |

### Read-only deploy (no backend)

Everything already computed can be published as static files: the story view, the scoreboard,
and Explore all work, and "Run" replays the cached run. Explore lists all ~24k participants (a
compact table the browser searches itself) and opens any of them from a per-participant bundle;
rounds without a result simply cannot be run. Nothing new can be analysed until a real backend is
behind `VITE_API_BASE`.

```bash
make static          # backend/static_export: ~400 MB, ~22k files, no model loaded
```

That is too big for a Vercel Hobby deploy (100 MB, 15k files), so the snapshot goes to a
Cloudflare R2 bucket and only the app goes to Vercel:

1. **R2:** create a bucket, enable its public `r2.dev` URL, and set this CORS policy so the site
   can fetch the JSON:
   ```json
   [{ "AllowedOrigins": ["https://your-domain.com", "http://localhost:5173"],
      "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 86400 }]
   ```
2. **Upload:** create an R2 API token (Object Read & Write), `brew install rclone`, and add a
   remote named `r2` with `rclone config` (type `s3`, provider `Cloudflare`, the token's keys,
   endpoint `https://<account-id>.r2.cloudflarestorage.com`). Then
   `make upload-static R2_BUCKET=<bucket>`. Run it again after `make static` to publish new results.
3. **Vercel:** import the repo with root directory `frontend` (framework: Vite), and set
   `VITE_READ_ONLY=1` and `VITE_API_BASE=https://pub-<id>.r2.dev`.

When the backend has a server of its own, drop `VITE_READ_ONLY`, point `VITE_API_BASE` at it,
add the site's origin to the backend's CORS list, and redeploy.

---

## Experiment: do T0 + T1 predict T2?

Each scan gives six cumulative risks (years 1–6 after that scan). With three rounds per
participant, [app/trajectory.py](backend/app/trajectory.py) tests whether T0's six numbers,
T1's six numbers and the T0 → T1 offset (13 inputs) predict Sybil's six T2 numbers better than
"T2 = T1". It contains:

- **Combined curve:** monotone cubic (PCHIP) interpolation of T0's points (years 1–6) and T1's
  points shifted onto T0's axis (years Δ+1 … Δ+6). T1's numbers are converted from "given
  cancer-free at T1". Reading the curve at T2's date gives a no-training baseline.
- **Linear regression and a hand-written numpy MLP** (13 → 8 tanh → 6, Adam), in logit space,
  each fitted with and without the offset input.
- **Repeated k-fold cross-validation** by participant, plus a paired bootstrap of the error
  difference "with offset − without offset".

```bash
cd backend
uv run python scripts/build_trajectories.py --n 100 --dry-run   # plan + time estimate
uv run python scripts/build_trajectories.py --n 100             # ~4.5 min per participant on CPU; resumable
uv run python scripts/fit_trajectory.py                         # the comparison table
uv run python scripts/fit_trajectory.py --show 217203           # one participant's curve
uv run python scripts/fit_trajectory.py --synthetic 200         # pipeline check, no Sybil needed
```

Results go to `backend/data/trajectories.csv`, one row per participant, written as each
participant finishes. `--cancer-share 0.3` enriches the sample with people diagnosed within six
years (about 2% of the population), which gives the models more spread to learn from.

### Everyone, on the GPU: `scripts/harvest.py`

[scripts/harvest.py](backend/scripts/harvest.py) runs Sybil on all three scans of every participant with
three eligible rounds: 19,667 people, 59,001 scans, about 4.9 TB of downloads that are deleted as soon as
each scan is read. On Windows:

```powershell
.\tasks.ps1 gpu-check          # torch 1.13.1+cu117, CUDA available: True
.\tasks.ps1 harvest            # start, or resume; -Workers 4, -Limit 200 for a trial
.\tasks.ps1 harvest-status     # from another window: progress, scans/h, days left
.\tasks.ps1 harvest-stop       # from another window: stop after the current scan
.\tasks.ps1 harvest-compile    # rebuild the tables (also done when a run ends)
```

- **Stopping is always safe.** Ctrl+C once (or `harvest-stop`) finishes the scan on the GPU and exits;
  Ctrl+C twice exits at once. Every file is written under a temporary name and renamed into place, so
  even a power cut leaves only whole scans. A second copy can't start in the same folder.
- **Resuming** skips finished scans. Download failures are retried on the next run; scans Sybil can't
  read are logged in `failed.jsonl` and skipped, along with the rest of that participant (`--retry-failed`
  tries them again).
- **Order** is a seeded shuffle, so whatever is finished when you stop is a random sample of complete
  triples. `--cancer-first` does the 455 people diagnosed within six years (2.3%) first instead.
- **Pipeline:** `--workers` threads download (s5cmd, straight from IDC's public S3 bucket) and prepare
  volumes on the CPU while the main thread runs the five networks on the GPU. Downloading is the
  bottleneck; `harvest-status` shows the measured rate.
- **Checked first:** before starting it scores upstream's demo scan on the GPU and refuses to run if it
  differs from the published scores by more than 0.1%. TF32 is switched off so the GPU computes in full
  fp32, like the CPU.

Output, in `backend/data/harvest/`:

| File | What |
|---|---|
| `scans/{exam}.json` | calibrated risks, the raw (uncalibrated) mean, each of the 5 networks' raw risks, labels (`cancer_within_6y`, `years_to_cancer`, `years_followed`), scanner and series facts |
| `features/{exam}.npz` | `hidden` (5 × 512): each network's last layer before its risk output; `attention` (25 × 16 × 16) |
| `scans.parquet` | every scan, one row each (from `compile`) |
| `features.npz` | complete participants: `pids`, `hidden` (n × 3 × 5 × 512), `attention` (n × 3 × 25 × 16 × 16) |
| `../trajectories.csv` | complete participants in the format above, so `fit_trajectory.py` and the Experiment page use them |

Why keep more than the six risks: the calibrated risks come from an isotonic calibrator, so they are a
step function with many ties. The raw mean keeps the ordering inside each step, and the 512 hidden
features per network describe the scan itself. A model predicting T2 from T0 + T1 can only learn from
what was saved, and re-running 59k scans to get it later would take days.

---

## Tests

```bash
.\tasks.ps1 test-fast     # 120 tests, no model and no network, ~15 s
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
* `test_catalog.py` — the exam / participant tables on synthetic rows, round statuses, and the index
  query (run in DuckDB) keeping one series per participant and round.
* `test_participants.py` — Explore search, filters and paging, round detail, batch runs in round
  order, results over time, CSV export, and that `blind=true` leaks no outcome anywhere.

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
