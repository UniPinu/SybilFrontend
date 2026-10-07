"""M0: prove the install really runs Sybil, and measure the UX budget.

Downloads the model weights (~700 MB, once, to ~/.sybil) and upstream's demo
scan, then asserts every one of the six scores matches the vector pinned in
upstream `tests/regression_test.py`. Logs wall-clock time per stage, which is
what the frontend's progress copy is designed around.

Run:  uv run python scripts/smoke_test.py
      uv run python scripts/smoke_test.py --compare-runner   # also check app/runner.py
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time

import numpy as np

from app.config import settings
from app.demo_data import EXPECTED_DEMO_SCORES, demo_dicom_paths

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("smoke_test")

REL_TOL = 1e-4  # MVP.md section 3; upstream's own test uses 1e-6


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compare-runner", action="store_true",
                    help="also run app/runner.py and require identical scores")
    ap.add_argument("--rel-tol", type=float, default=REL_TOL)
    ap.add_argument("--json", default=None, help="write timings to this path")
    args = ap.parse_args()

    import torch
    from sybil import Serie, Sybil

    timings: dict[str, float] = {}

    def stage(name: str, fn):
        t0 = time.time()
        out = fn()
        timings[name] = round(time.time() - t0, 2)
        log.info("%-14s %6.2fs", name, timings[name])
        return out

    log.info("device=%s threads=%s weights=%s",
             settings.device, settings.threads, settings.sybil_cache)
    torch.set_num_threads(settings.threads)

    paths = stage("demo_data", demo_dicom_paths)
    log.info("demo scan: %d slices", len(paths))

    model = stage(
        "load_model",
        lambda: Sybil(settings.model_name, cache=str(settings.sybil_cache),
                      device=settings.device),
    )
    serie = stage("serie", lambda: Serie(paths))
    stage("get_volume", serie.get_volume)
    prediction = stage("predict", lambda: model.predict([serie], return_attentions=True))

    scores = prediction.scores[0]
    log.info("scores   %s", [round(s, 5) for s in scores])
    log.info("expected %s", [round(s, 5) for s in EXPECTED_DEMO_SCORES])

    ok = len(scores) == len(EXPECTED_DEMO_SCORES)
    for expected, actual in zip(EXPECTED_DEMO_SCORES, scores):
        match = math.isclose(expected, actual, rel_tol=args.rel_tol)
        ok &= match
        if not match:
            log.error("mismatch: expected %.10f got %.10f", expected, actual)

    att = prediction.attentions[0]
    log.info("attention keys: %s",
             {k: tuple(np.asarray(v).shape) for k, v in att.items() if k != "hidden"})

    if args.compare_runner:
        from app.runner import run_sybil

        t0 = time.time()
        result = run_sybil(paths, emit=lambda stage, **kw: log.info("  emit %s %s", stage, kw))
        timings["runner"] = round(time.time() - t0, 2)
        same = np.allclose(np.array(result.calibrated), np.array(scores), rtol=0, atol=0)
        log.info("runner scores identical to Sybil.predict(): %s", same)
        if not same:
            log.error("runner %s", result.calibrated)
            ok = False

    total = round(sum(timings.values()), 2)
    log.info("stage timings: %s (total %.2fs)", timings, total)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"timings": timings, "scores": list(scores)}, fh, indent=2)

    if ok:
        log.info("SMOKE TEST PASSED (rel_tol=%g)", args.rel_tol)
        return 0
    log.error("SMOKE TEST FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
