"""Snapshot the cached results as static files, for a read-only deploy.

Every GET the frontend makes for an already-prepared person is answered once,
in-process, and written to disk as a file. The frontend, built with
VITE_READ_ONLY=1, reads these instead of a live backend, so the site can be
hosted anywhere static (e.g. Cloudflare R2) and nothing runs Sybil.

Layout: a JSON endpoint `/api/x/y` is written to `api/x/y/index.json`, and to
`index.blind.json` for its `?blind=true` variant. Images keep their URL paths.
Two files have no endpoint: `api/patients/index.json` (every prepared exam, for
the random picker) and `api/participants/index[.blind].json` (every participant
with a result, which the frontend searches itself). The model is never loaded.

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

    for pid in pids:
        base = f"/api/participants/{pid}"
        endpoint(base, blind_variant=True)
        endpoint(f"{base}/results", blind_variant=True)
        write(f"{base.lstrip('/')}/export.csv", fetch(f"{base}/export.csv", text=True))
        write(f"{base.lstrip('/')}/export.blind.csv",
              fetch(f"{base}/export.csv?blind=true", text=True))

    # Search runs in the browser over this list, so page through all of it here.
    for blind, name in ((False, "index.json"), (True, "index.blind.json")):
        items, page = [], 1
        while True:
            body = fetch(f"/api/participants?has_results=true&page_size=100&page={page}"
                         f"{'&blind=true' if blind else ''}")
            items += body["items"]
            if page * body["page_size"] >= body["total"]:
                break
            page += 1
        write(f"api/participants/{name}", {"items": items})

    files = [p for p in out.rglob("*") if p.is_file()]
    size_mb = sum(p.stat().st_size for p in files) / 1e6
    print(f"done: {len(files):,} files, {size_mb:.0f} MB in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
