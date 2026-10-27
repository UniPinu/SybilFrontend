"""Snapshot the cached results as static files, for a read-only deploy.

Every GET the frontend makes for an already-prepared person is answered once,
in-process, and written to disk as a file. The frontend, built with
VITE_READ_ONLY=1, reads these instead of a live backend, so the site can be
hosted anywhere static (e.g. Cloudflare R2) and nothing runs Sybil.

Layout: a JSON endpoint `/api/x/y` is written to `api/x/y/index.json`, and to
`index.blind.json` for its `?blind=true` variant. Images keep their URL paths.
Some files have no endpoint of their own:
  api/patients/index.json             every prepared exam, for the random picker
  api/participants/all.json           every participant as a compact table; the
                                      frontend searches and filters it itself
  api/participants/<pid>/bundle.json  detail + results, normal and blind, for
                                      every participant (run or not)
The model is never loaded.

Run:  uv run python scripts/export_static.py                # -> backend/static_export
      uv run python scripts/export_static.py --out ../somewhere
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.participants import ready_counts
from app.store import store

BACKEND_DIR = Path(__file__).resolve().parent.parent
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request otherwise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=BACKEND_DIR / "static_export")
    ap.add_argument("--no-images", action="store_true",
                    help="skip copying the WebP images (JSON only, for a quick refresh)")
    args = ap.parse_args()
    out: Path = args.out.resolve()

    # Not used as a context manager, so the lifespan (job worker, model preload) never runs.
    client = TestClient(app)

    def fetch(url: str, *, text: bool = False):
        response = client.get(url)
        if response.status_code != 200:
            raise RuntimeError(f"GET {url} -> {response.status_code}: {response.text[:200]}")
        return response.text if text else response.json()

    def write(rel: str, body) -> None:
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, str):
            path.write_text(body, encoding="utf-8")
        else:
            path.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")

    def endpoint(url: str, *, blind_variant: bool = False) -> None:
        write(f"{url.lstrip('/')}/index.json", fetch(url))
        if blind_variant:
            write(f"{url.lstrip('/')}/index.blind.json", fetch(f"{url}?blind=true"))

    exam_ids = store.list_ready()
    if not exam_ids:
        print("No prepared people in the cache; nothing to export.", file=sys.stderr)
        return 1
    pids = sorted(ready_counts())
    print(f"exporting {len(exam_ids)} exams from {len(pids)} participants -> {out}")

    # participants are rewritten in full below; drop files from older layouts
    shutil.rmtree(out / "api" / "participants", ignore_errors=True)

    endpoint("/api/health")
    endpoint("/api/cohort")
    write("api/patients/index.json", {"patient_ids": exam_ids})

    for i, exam_id in enumerate(exam_ids, 1):
        base = f"/api/patients/{exam_id}"
        endpoint(base)
        endpoint(f"{base}/result")
        endpoint(f"{base}/outcome")
        if not args.no_images:
            src = store.dir_for(exam_id)
            dst = out / base.lstrip("/")
            for sub in ("slices", "overlay"):
                if (src / sub).exists():
                    shutil.copytree(src / sub, dst / sub, dirs_exist_ok=True)
            if (src / "coronal.webp").exists():
                shutil.copy2(src / "coronal.webp", dst / "coronal.webp")
        print(f"  [{i}/{len(exam_ids)}] {exam_id}", flush=True)

    # Every participant, run or not: one bundle each with the four answers the
    # participant page asks for. Built from the same functions and response
    # schemas as the endpoints, without going through HTTP 96k times.
    from app import participants as explore
    from app.data import _clean
    from app.schemas import ParticipantDetail, ParticipantResults

    everyone = explore.table()
    ready = explore.ready_counts()
    print(f"bundling {len(everyone):,} participants")
    for i, pid in enumerate(everyone["nlst_pid"].tolist(), 1):
        bundle = {
            "detail": ParticipantDetail(**explore.detail(pid)).model_dump(mode="json"),
            "detail_blind": ParticipantDetail(**explore.detail(pid, blind=True)).model_dump(mode="json"),
            "results": ParticipantResults(**explore.results(pid)).model_dump(mode="json"),
            "results_blind": ParticipantResults(**explore.results(pid, blind=True)).model_dump(mode="json"),
        }
        write(f"api/participants/{pid}/bundle.json", bundle)
        if i % 2000 == 0:
            print(f"  {i:,} / {len(everyone):,}", flush=True)
    for pid in pids:  # CSV export only exists for people with results
        base = f"/api/participants/{pid}"
        write(f"{base.lstrip('/')}/export.csv", fetch(f"{base}/export.csv", text=True))
        write(f"{base.lstrip('/')}/export.blind.csv",
              fetch(f"{base}/export.csv?blind=true", text=True))

    # The Experiment page, for everyone with all three rounds run and dated.
    from app import experiment
    from app.schemas import TrajectoryGuide

    guides = 0
    for pid in pids:
        try:
            body = TrajectoryGuide(**experiment.guide(pid)).model_dump(mode="json")
        except experiment.NotReady:
            continue
        write(f"api/experiments/trajectory/{pid}/index.json", body)
        guides += 1
    print(f"experiment guides: {guides}")

    # Search runs in the browser over every participant. As plain objects that
    # is 11 MB, so strings are dictionary-coded and each person is one row.
    STATUS = {"eligible": "e", "excluded": "x", "no_usable_series": "u", "no_images": "n"}
    dicts: dict = {"sex": [], "smoking": [], "race": [], "manufacturer": [], "stage": []}

    def code(kind: str, value):
        if value is None:
            return None
        table = dicts[kind]
        if value not in table:
            table.append(value)
        return table.index(value)

    rows = []
    for row in everyone.to_dict("records"):
        item = explore._summary(_clean(row), int(ready.get(row["nlst_pid"], 0)), blind=False)
        o = item["outcome"]
        rows.append([
            item["nlst_pid"], item["age_at_randomization"], code("sex", item["sex"]),
            code("smoking", item["smoking_status"]), code("race", item["race"]),
            "".join(STATUS[r["status"]] for r in item["rounds"]), item["n_rounds"], item["n_eligible"],
            [code("manufacturer", m) for m in item["manufacturers"]], int(item["in_regression_set"]),
            item["results_ready"], int(o["diagnosed"]), o["years_rand_to_dx"], code("stage", o["stage"]),
            int(o["cancer_within_6y_any"]),
        ])
    write("api/participants/all.json", {
        "columns": ["nlst_pid", "age", "sex", "smoking", "race", "rounds", "n_rounds", "n_eligible",
                    "manufacturers", "in_regression_set", "results_ready", "diagnosed",
                    "years_rand_to_dx", "stage", "cancer_within_6y_any"],
        "status": {v: k for k, v in STATUS.items()},
        "dicts": dicts,
        "rows": rows,
    })

    files = [p for p in out.rglob("*") if p.is_file()]
    size_mb = sum(p.stat().st_size for p in files) / 1e6
    print(f"done: {len(files):,} files, {size_mb:.0f} MB in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
