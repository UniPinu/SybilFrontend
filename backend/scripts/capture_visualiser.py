"""Record one real Sybil run, step by step, for the Visualiser page.

Downloads one NLST series, repeats Sybil's preprocessing one step at a time
(asserting that the result equals `Serie.get_volume()`), then runs all five
models with forward hooks that record what each part of the network produced:
the first convolution, the four ResNet stages, both attention pools, the global
max pool, the 512-wide hidden vector, the six hazard neurons, the cumulative
sum and sigmoid, and the per-year isotonic calibration of the ensemble mean.

Large tensors are summarised inside the hooks (channel means, a handful of
channels at the hotspot slab) so the run fits in memory. Everything lands in
frontend/public/visualiser/<case>/: `case.json` plus WebP atlases (a grid of
slices in one image) that the page uploads as textures. Re-running reproduces
the same files; the page never needs the model.

Run:  uv run python scripts/capture_visualiser.py                 # 217203_T2
      uv run python scripts/capture_visualiser.py --case 100570_T0
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from PIL import Image

from app import data
from app.config import settings
from app.fetch import fetch_series

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_ROOT = ROOT / "frontend" / "public" / "visualiser"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("capture")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
class RunLog:
    """Timestamped log lines, printed and kept for the page's run console."""

    def __init__(self) -> None:
        self.t0 = time.time()
        self.lines: List[Dict[str, Any]] = []

    def __call__(self, step: str, message: str, **facts: Any) -> None:
        t = round(time.time() - self.t0, 2)
        self.lines.append({"t": t, "step": step, "message": message, **facts})
        extra = " ".join(f"{k}={v}" for k, v in facts.items())
        log.info("[%7.2fs] %-12s %s %s", t, step, message, extra)


def r(x: Any, nd: int = 4) -> Any:
    """Round floats (recursively) so the JSON stays small."""
    if isinstance(x, (list, tuple)):
        return [r(v, nd) for v in x]
    if isinstance(x, np.ndarray):
        return r(x.tolist(), nd)
    if isinstance(x, (float, np.floating)):
        return round(float(x), nd)
    return x


def atlas(stack: np.ndarray, lo: float, hi: float, size: int, path: Path) -> Dict[str, Any]:
    """Write N slices (N, H, W) as one grayscale WebP grid; return how to read it back."""
    n = stack.shape[0]
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    sheet = Image.new("L", (cols * size, rows * size), 0)
    span = (hi - lo) or 1.0
    for i in range(n):
        tile = np.clip((stack[i] - lo) / span, 0, 1) * 255
        img = Image.fromarray(tile.astype(np.uint8)).resize((size, size), Image.BILINEAR)
        sheet.paste(img, ((i % cols) * size, (i // cols) * size))
    sheet.save(path, "WEBP", quality=88, method=6)
    return {"file": path.name, "count": n, "cols": cols, "rows": rows, "tile": size,
            "lo": r(lo), "hi": r(hi), "bytes": path.stat().st_size}


def picture(arr: np.ndarray, lo: float, hi: float, path: Path, size: int | None = None) -> str:
    tile = np.clip((arr - lo) / ((hi - lo) or 1.0), 0, 1) * 255
    img = Image.fromarray(tile.astype(np.uint8))
    if size:
        img = img.resize((size, size), Image.BILINEAR)
    img.save(path, "WEBP", quality=90, method=6)
    return path.name


def receptive_field(encoder) -> List[Dict[str, Any]]:
    """Walk the r3d_18 main path and grow the receptive field conv by conv.

    The 1x1x1 downsample convs sit on the skip path and do not widen it.
    """
    import torch.nn as nn

    rf = [1, 1, 1]
    jump = [1, 1, 1]
    out = []

    def add(conv: nn.Conv3d) -> None:
        for d in range(3):
            rf[d] += (conv.kernel_size[d] - 1) * jump[d]
            jump[d] *= conv.stride[d]

    stem, *layers = list(encoder.children())
    add(stem[0])
    out.append({"stage": "stem", "rf": list(rf), "jump": list(jump)})
    for name, layer in zip(["layer1", "layer2", "layer3", "layer4"], layers):
        for block in layer:
            add(block.conv1[0][0] if isinstance(block.conv1[0], nn.Sequential) else block.conv1[0])
            add(block.conv2[0][0] if isinstance(block.conv2[0], nn.Sequential) else block.conv2[0])
        out.append({"stage": name, "rf": list(rf), "jump": list(jump)})
    return out


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default="217203_T2")
    ap.add_argument("--keep-dicoms", action="store_true")
    ap.add_argument("--reuse", action="store_true",
                    help="reuse the saved forward-pass state of a previous run (no model passes)")
    args = ap.parse_args()

    import pydicom
    import torch
    import torchio as tio
    from pydicom.pixel_data_handlers.util import apply_modality_lut
    from sybil import Serie
    from sybil.datasets.utils import VOXEL_SPACING
    from sybil.loaders.image_loaders import apply_windowing

    from app.runner import get_model

    say = RunLog()
    out = OUT_ROOT / args.case
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    case: Dict[str, Any] = {"case": args.case}

    # --- 0. who --------------------------------------------------------------
    candidate = data.get_candidate(args.case)
    if candidate is None:
        print(f"unknown case {args.case}", file=sys.stderr)
        return 1
    card = data.person_card(candidate)
    case["person"] = {k: card.get(k) for k in (
        "age", "sex", "smoking_status", "screening_round", "manufacturer", "scanner_model",
        "kernel", "n_slices", "thickness_mm")}
    case["person"]["nlst_pid"] = candidate["nlst_pid"]
    cached = json.loads((settings.patients_dir / args.case / "outcome.json").read_text()) \
        if (settings.patients_dir / args.case / "outcome.json").exists() else None
    case["outcome"] = cached
    say("person", f"NLST participant {candidate['nlst_pid']}, round {card.get('screening_round')}",
        series=candidate["series_uid"])

    # --- 1. download -----------------------------------------------------------
    tmp = settings.tmp_dir / f"visualiser_{args.case}"
    say("download", "fetching one series from NCI Imaging Data Commons",
        expected_mb=r(candidate.get("series_size_mb"), 1))
    state_file = tmp.parent / f"visualiser_{args.case}_state.pt"
    fetched = fetch_series(candidate["series_uid"], tmp, expected_mb=candidate.get("series_size_mb"))
    say("download", "done", files=len(fetched.paths), mb=r(fetched.bytes_downloaded / 1e6, 1),
        seconds=r(fetched.seconds, 1))

    # --- 2. read + sort -----------------------------------------------------
    serie = Serie(list(fetched.paths))
    meta = serie._meta  # no public accessor; the Sybil commit is pinned
    n_raw = len(meta.paths)
    first = pydicom.dcmread(meta.paths[0], stop_before_pixels=True)
    rows_px, cols_px = int(first.Rows), int(first.Columns)
    positions = [float(p) for p in meta.slice_positions]
    case["dicom"] = {
        "n_slices": n_raw, "rows": rows_px, "cols": cols_px,
        "pixel_spacing_mm": r(meta.pixel_spacing), "thickness_mm": r(meta.thickness),
        "z_first_mm": r(positions[0], 2), "z_last_mm": r(positions[-1], 2),
        "extent_mm": [r(rows_px * meta.pixel_spacing[0], 1), r(cols_px * meta.pixel_spacing[1], 1),
                      r(positions[-1] - positions[0] + meta.thickness, 1)],
        "manufacturer": str(meta.manufacturer),
    }
    say("read", "sorted slices by ImagePositionPatient (z)", slices=n_raw,
        size=f"{rows_px}x{cols_px}", spacing=r(meta.pixel_spacing, 3), thickness=meta.thickness)

    # --- 3. HU + window (one slice in detail, all slices for the stack) -----------
    W_CENTER, W_WIDTH = -600, 1500
    windowed = []
    hu_mid = None
    hot_raw = int(json.loads((settings.patients_dir / args.case / "result.json").read_text())
                  .get("hotspot_slice", n_raw // 2)) \
        if (settings.patients_dir / args.case / "result.json").exists() else n_raw // 2
    for i, path in enumerate(meta.paths):
        dcm = pydicom.dcmread(path)
        hu = apply_modality_lut(dcm.pixel_array, dcm).astype(np.float64)
        if i == hot_raw:
            hu_mid = hu.copy()
        arr = apply_windowing(hu.copy(), W_CENTER, W_WIDTH) // 256
        windowed.append(arr.astype(np.float32))
    windowed = np.stack(windowed)  # (N, 512, 512) 0..255
    hist, edges = np.histogram(np.clip(hu_mid, -1200, 1200), bins=96, range=(-1200, 1200))
    case["window"] = {
        "center": W_CENTER, "width": W_WIDTH,
        "lo_hu": W_CENTER - 0.5 - (W_WIDTH - 1) / 2, "hi_hu": W_CENTER - 0.5 + (W_WIDTH - 1) / 2,
        "slice": hot_raw,
        "hist": hist.tolist(), "hist_edges": r(edges, 1),
        "hu_range": [r(hu_mid.min(), 0), r(hu_mid.max(), 0)],
        "hu_image": picture(hu_mid, -1024, 1500, out / "hu_slice.webp", 256),
        "windowed_image": picture(windowed[hot_raw], 0, 255, out / "windowed_slice.webp", 256),
    }
    say("window", "Hounsfield units -> lung window, 16-bit, then //256 to 8-bit",
        center=W_CENTER, width=W_WIDTH, hu_min=r(hu_mid.min(), 0), hu_max=r(hu_mid.max(), 0))
    case["raw_atlas"] = atlas(windowed, 0, 255, 128, out / "raw_atlas.webp")
    say("window", "raw stack atlas written", **{k: case["raw_atlas"][k] for k in ("count", "tile", "bytes")})

    # --- 4. resize + normalise + 3 channels, then resample + crop/pad ------------
    # The same calls as Serie.get_volume(), one at a time, so each can be shown.
    t = time.time()
    dicts = [serie._loader.get_image(p) for p in meta.paths]
    x2d = torch.cat([d["input"].unsqueeze(0) for d in dicts], dim=0)   # (T, 3, 256, 256)
    say("resize", "each slice resized 512->256 (bilinear), normalised (x-128.17)/87.18, "
        "copied into 3 identical channels", shape=list(x2d.shape),
        mean=r(float(x2d.mean()), 3), std=r(float(x2d.std()), 3), seconds=r(time.time() - t, 2))
    x = x2d.permute(1, 0, 2, 3)                                          # (3, T, 256, 256)
    img = tio.ScalarImage(affine=torch.diag(meta.voxel_spacing), tensor=x.permute(0, 2, 3, 1))
    t = time.time()
    resampled = serie.resample_transform(img)
    rs_shape = list(resampled.data.shape)  # (3, H, W, T)
    say("resample", f"torchio Resample to {VOXEL_SPACING} mm "
        "(spacing taken from the DICOM, applied to the 256 grid)",
        shape=rs_shape, seconds=r(time.time() - t, 2))
    padded = serie.padding_transform(resampled)
    vol = padded.data.permute(0, 3, 1, 2).unsqueeze(0)                   # (1, 3, 200, 256, 256)
    reference = serie.get_volume()
    same = bool(torch.equal(vol, reference))
    say("pad", "CropOrPad to 256x256x200 with zeros (= the mean grey after normalising)",
        shape=list(vol.shape), identical_to_serie_get_volume=same)
    if not same:
        raise SystemExit("step-by-step preprocessing does not match Serie.get_volume()")

    v = vol[0, 0].numpy()                                                # (200, 256, 256)
    zero_slices = [i for i in range(v.shape[0]) if np.all(v[i] == 0)]
    content = [i for i in range(v.shape[0]) if i not in set(zero_slices)]
    rs = resampled.data[0].permute(2, 0, 1).numpy()                      # (T', H', W')
    pad_hw = [(256 - rs_shape[1]) // 2, (256 - rs_shape[2]) // 2]
    mid_in = int(round(content[0] + (hot_raw / max(1, n_raw - 1)) * (len(content) - 1)))
    case["preprocess"] = {
        "img_mean": 128.1722, "img_std": 87.1849,
        "voxel_spacing_target": list(VOXEL_SPACING),
        "resized": [int(x2d.shape[0]), 256, 256],
        "resampled": [rs_shape[3], rs_shape[1], rs_shape[2]],
        "input": [200, 256, 256],
        "pad_slices_before": content[0], "pad_slices_after": 199 - content[-1],
        "pad_pixels": pad_hw,
        "value_range": [r(float(v.min()), 3), r(float(v.max()), 3)],
        "example_slice_in": mid_in,
        "images": {
            "resized": picture(x2d[hot_raw, 0].numpy(), -1.47, 1.46, out / "pre_resized.webp"),
            "resampled": picture(rs[int(round(hot_raw * meta.thickness / VOXEL_SPACING[2]))],
                                 -1.47, 1.46, out / "pre_resampled.webp"),
            "padded": picture(v[mid_in], -1.47, 1.46, out / "pre_padded.webp"),
        },
    }
    case["input_atlas"] = atlas(v, -1.47, 1.46, 128, out / "input_atlas.webp")
    say("pad", "model input atlas written", padded_before=content[0],
        padded_after=199 - content[-1], **{k: case["input_atlas"][k] for k in ("count", "bytes")})

    # --- 5. the model ------------------------------------------------------------
    t = time.time()
    sybil = get_model()
    say("model", "loaded the 5-model ensemble", seconds=r(time.time() - t, 1),
        threads=settings.threads, device=settings.device)
    net0 = sybil.ensemble[0]
    enc = net0.image_encoder
    case["receptive_field"] = receptive_field(enc)
    stem_conv, stem_bn = enc[0][0], enc[0][1]
    case["architecture"] = {
        "stem": {"kernel": list(stem_conv.kernel_size), "stride": list(stem_conv.stride),
                 "padding": list(stem_conv.padding), "out_channels": stem_conv.out_channels},
        "stages": [{"name": n, "blocks": len(enc[i])}
                   for i, n in [(1, "layer1"), (2, "layer2"), (3, "layer3"), (4, "layer4")]],
        "params_per_model": int(sum(p.numel() for p in net0.parameters())),
        "dropout": float(net0.dropout.p),
        "pool": {"conv1d_kernel": 11, "hidden_in": 1536, "hidden": 512},
    }

    # The hotspot of the cached run tells the hooks which slab to keep channels for.
    cached_grid = None
    cached_result = settings.patients_dir / args.case / "result.json"
    if cached_result.exists():
        g = json.loads(cached_result.read_text()).get("attention_grid")
        if g is not None:
            cached_grid = np.asarray(g, dtype=np.float32).reshape(25, 16, 16)
    hz = int(np.unravel_index(np.argmax(cached_grid), cached_grid.shape)[0]) if cached_grid is not None else 12
    z_in = hz * 8 + 4                                   # centre of that slab in the 200 input slices
    say("model", "keeping full channels around the cached hotspot slab", slab=hz, input_slice=z_in)

    stages: Dict[str, Dict[str, Any]] = {}
    stem_out_voxel = {}

    def stage_hook(name: str, z_factor: int):
        def hook(_m, _i, o):
            a = o[0].float()                              # (C, T, H, W)
            C, T, H, W = a.shape
            z = min(T - 1, z_in // z_factor)
            mean = a.mean(0).numpy()                      # (T, H, W)
            at_z = a[:, z].numpy()                        # (C, H, W)
            order = np.argsort(-at_z.reshape(C, -1).mean(1))
            stages[name] = {"shape": [C, T, H, W], "z": z, "mean": mean,
                            "channels": at_z[order[:16]], "channel_ids": order[:16].tolist(),
                            "per_slice": a.mean((0, 2, 3)).numpy(),
                            "frac_zero": float((a == 0).sum()) / a.numel()}
            if name == "stem":
                # clone: a view would keep (and torch.save would write) the whole 838 MB tensor
                stem_out_voxel["tensor"] = a[:, z_in].clone()   # (64, 128, 128)
        return hook

    pool_out: List[Dict[str, Any]] = []
    head_out: List[Dict[str, Any]] = []

    def pool_hook(_m, _i, o):
        pool_out.append({k: val.detach().clone() for k, val in o.items()})

    def head_hook(m, i, o):
        x_ = i[0]
        head_out.append({"hidden": x_.detach().clone(), "raw_hazard": m.hazard_fc(x_).detach(),
                         "base_hazard": m.base_hazard_fc(x_).detach(), "cum_logit": o.detach().clone()})

    handles = []
    for i, (name, zf) in enumerate([("stem", 1), ("layer1", 1), ("layer2", 2), ("layer3", 4), ("layer4", 8)]):
        handles.append(enc[i].register_forward_hook(stage_hook(name, zf)))
    for net in sybil.ensemble:
        handles.append(net.pool.register_forward_hook(pool_hook))
        handles.append(net.prob_of_failure_layer.register_forward_hook(head_hook))

    probs_per_model = []
    forward_start = time.time() - say.t0
    if args.reuse and state_file.exists():
        state = torch.load(state_file)
        stages, pool_out, head_out = state["stages"], state["pool_out"], state["head_out"]
        stem_out_voxel["tensor"], probs_per_model = state["stem_voxel"], state["probs"]
        for h in handles:
            h.remove()
        handles = []
        # replay the original run's log lines for the forward passes, on this run's clock
        now = time.time() - say.t0
        lines = state.get("log", [])
        for line in lines:
            say.lines.append({**line, "t": round(now + line["t"] - state.get("forward_start", 0), 2)})
        say.t0 -= state.get("forward_seconds", 0)
    for k, net in enumerate(sybil.ensemble if not probs_per_model else []):
        t = time.time()
        with torch.no_grad():
            o = net(vol)
        probs_per_model.append(o["prob"][0].numpy().astype(np.float64))
        say("model", f"model {k + 1}/5 forward pass", seconds=r(time.time() - t, 1),
            activ=list(o["activ"].shape), risk_6y=r(float(o["prob"][0, -1]), 4))
        if k == 0:
            for h in handles[:5]:
                h.remove()
            for name in ("stem", "layer1", "layer2", "layer3", "layer4"):
                s = stages[name]
                say("encoder", f"{name} output", shape=s["shape"],
                    zeroed_by_relu=r(s["frac_zero"], 3))
    for h in handles[5:]:
        h.remove()
    if not (args.reuse and state_file.exists()):
        torch.save({"stages": stages, "pool_out": pool_out, "head_out": head_out,
                    "stem_voxel": stem_out_voxel["tensor"], "probs": probs_per_model,
                    "log": [l for l in say.lines if l["t"] >= forward_start - 1e-6],
                    "forward_start": forward_start,
                    "forward_seconds": time.time() - say.t0 - forward_start}, state_file)

    # --- 6. one real output voxel of the first convolution, by hand -------------
    W_ = stem_conv.weight.detach()[:, :, :, :, :]               # (64, 3, 3, 7, 7)
    yy, xx = int(np.argmax(cached_grid[hz]) // 16 * 16 + 8) if cached_grid is not None else 128, \
        int(np.argmax(cached_grid[hz]) % 16 * 16 + 8) if cached_grid is not None else 128
    oy, ox = yy // 2, xx // 2                                   # stem output grid is stride 2
    act = stem_out_voxel["tensor"][:, oy, ox].numpy()
    f = int(np.argmax(act))                                     # the most excited filter there
    padded_in = torch.nn.functional.pad(vol[0], (3, 3, 3, 3, 1, 1))
    patch = padded_in[:, z_in: z_in + 3, oy * 2: oy * 2 + 7, ox * 2: ox * 2 + 7]  # (3, 3, 7, 7)
    dot = float((patch * W_[f]).sum()) + (float(stem_conv.bias[f]) if stem_conv.bias is not None else 0.0)
    g_, b_ = float(stem_bn.weight[f]), float(stem_bn.bias[f])
    mu, var = float(stem_bn.running_mean[f]), float(stem_bn.running_var[f])
    bn = (dot - mu) / math.sqrt(var + stem_bn.eps) * g_ + b_
    case["stem_voxel"] = {
        "filter": f, "input_slice": z_in, "out_yx": [oy, ox], "in_yx": [oy * 2, ox * 2],
        "patch": r(patch[0].numpy(), 3),                         # channels are identical copies
        "weights": r(W_[f].numpy(), 4),                           # (3 in-channels, 3, 7, 7)
        "weights_summed": r(W_[f].sum(0).numpy(), 4),             # what one grey channel sees
        "dot": r(dot, 4), "bn": {"gamma": r(g_), "beta": r(b_), "mean": r(mu), "var": r(var),
                                 "eps": stem_bn.eps},
        "after_bn": r(bn, 4), "after_relu": r(max(0.0, bn), 4),
        "hooked_value": r(float(act[f]), 4),
        "all_filters_here": r(act, 3),
    }
    say("stem", "recomputed one output voxel of the first conv by hand", filter=f,
        dot=r(dot, 3), after_relu=r(max(0.0, bn), 4), hooked=r(float(act[f]), 4))
    # all 64 stem filters, summed over the 3 identical input channels: (64, 3, 7, 7)
    case["stem_filters"] = r(W_.sum(1).numpy(), 3)
    # ...and what each of them produced on that input slice (64 maps of 128x128)
    maps = stem_out_voxel["tensor"].numpy()
    case["stem_maps"] = atlas(maps, 0.0, float(np.percentile(maps, 99.5)) or 1.0, 64,
                              out / "stem_maps.webp")
    case["stem_voxel"]["map"] = picture(maps[f], 0.0, float(np.percentile(maps[f], 99.7)) or 1.0,
                                        out / "stem_filter_map.webp")
    case["stem_voxel"]["input_slice_image"] = picture(v[z_in], -1.47, 1.46, out / "stem_input_slice.webp")

    # --- 7. stage summaries -> atlases -------------------------------------------
    case["stages"] = []
    for name, size in (("stem", 64), ("layer1", 64), ("layer2", 64), ("layer3", 32), ("layer4", 16)):
        s = stages[name]
        hi = float(np.percentile(s["mean"], 99.5))
        mean_atlas = atlas(s["mean"], 0.0, hi, size, out / f"{name}_mean.webp")
        ch = s["channels"]
        ch_hi = float(np.percentile(ch, 99.5)) or 1.0
        ch_atlas = atlas(ch, 0.0, ch_hi, 96, out / f"{name}_channels.webp")
        case["stages"].append({
            "name": name, "shape": s["shape"], "z": s["z"], "mean_atlas": mean_atlas,
            "channel_atlas": ch_atlas, "channel_ids": s["channel_ids"],
            "per_slice": r(s["per_slice"], 4), "zeroed_by_relu": r(s["frac_zero"], 3),
        })

    # --- 8. pooling + head, every model -----------------------------------------
    models = []
    for k in range(5):
        p, h = pool_out[k], head_out[k]
        img_att = p["image_attention_1"][0].exp().numpy()       # (25, 256)
        vol_att = p["volume_attention_1"][0].exp().numpy()      # (25,)
        vol_att2 = p["volume_attention_2"][0].exp().numpy()     # (25,)
        entry = {
            "image_attention": r(img_att, 5), "volume_attention": r(vol_att, 5),
            "volume_attention_2": r(vol_att2, 5),
            "hidden_1": r(p["hidden_1"][0].numpy(), 4),          # attention branch (512)
            "hidden_2": r(p["hidden_2"][0].numpy(), 4),          # max + conv1d + attention (512)
            "maxpool_hidden": r(p["maxpool_hidden"][0].numpy(), 4),
            "hidden_pre_relu": r(p["hidden"][0].numpy(), 4),
            "hidden": r(h["hidden"][0].numpy(), 4),              # after ReLU (dropout is off in eval)
            "raw_hazard": r(h["raw_hazard"][0].numpy(), 5),
            "base_hazard": r(float(h["base_hazard"][0, 0]), 5),
            "cum_logit": r(h["cum_logit"][0].numpy(), 5),
            "prob": r(probs_per_model[k], 6),
        }
        if k == 0:
            entry["per_frame_max"] = r(p["multi_image_hidden_2"][0].numpy(), 3)   # (512, 25)
            entry["slab_features"] = r(p["multi_image_hidden_1"][0].numpy(), 3) \
                if "multi_image_hidden_1" in p else None                            # (512, 25)
            hz_fc = sybil.ensemble[0].prob_of_failure_layer.hazard_fc
            contrib = (hz_fc.weight.detach() * h["hidden"][0]).numpy()             # (6, 512)
            top = np.argsort(-np.abs(contrib).sum(0))[:24]
            entry["hazard_top_units"] = top.tolist()
            entry["hazard_contrib_top"] = r(contrib[:, top], 4)
            entry["hazard_bias"] = r(hz_fc.bias.detach().numpy(), 4)
        models.append(entry)
    case["models"] = models

    # --- 9. ensemble + calibration -------------------------------------------------
    raw = np.mean(np.stack(probs_per_model), axis=0)
    calibrated = sybil._calibrate(raw.reshape(1, -1))[0]
    xs = np.linspace(0, 1, 201)
    curves = []
    for year in range(6):
        cal = sybil.calibrator[f"Year{year + 1}"]
        curves.append(r(cal.predict_proba(xs.reshape(-1, 1)), 4))
    case["ensemble"] = {"raw_mean": r(raw, 6), "calibrated": r(calibrated, 6),
                        "calibration_x": r(xs, 3), "calibration_curves": curves}
    grid = np.mean([np.asarray(m["image_attention"]) * np.asarray(m["volume_attention"])[:, None]
                    for m in models], axis=0).reshape(25, 16, 16)
    hot = np.unravel_index(np.argmax(grid), grid.shape)
    case["attention_grid"] = r(grid, 6)
    case["hotspot"] = {"slab": int(hot[0]), "y": int(hot[1]), "x": int(hot[2]),
                       "input_slices": [int(hot[0]) * 8, int(hot[0]) * 8 + 7],
                       "input_pixels": [int(hot[1]) * 16, int(hot[2]) * 16, 16]}
    say("ensemble", "mean of 5 sigmoid outputs, then per-year isotonic calibration",
        raw_6y=r(raw[-1], 4), calibrated=r(calibrated, 4))
    if cached_result.exists():
        prev = json.loads(cached_result.read_text())["risk_by_year"]
        diff = float(np.max(np.abs(np.asarray(prev) - calibrated)))
        say("check", "compared with the app's cached run of the same scan", max_abs_diff=r(diff, 8))
        case["matches_cached_run"] = diff < 1e-4

    case["log"] = say.lines
    (out / "case.json").write_text(json.dumps(case, separators=(",", ":")), encoding="utf-8")
    total = sum(p.stat().st_size for p in out.iterdir())
    say("done", f"wrote {out.relative_to(ROOT)}", files=len(list(out.iterdir())),
        kb=round(total / 1024))
    (out / "case.json").write_text(json.dumps({**case, "log": say.lines}, separators=(",", ":")),
                                   encoding="utf-8")
    if not args.keep_dicoms:
        shutil.rmtree(tmp, ignore_errors=True)
        state_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
