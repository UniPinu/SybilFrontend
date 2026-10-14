# Visualiser: plan

Goal: anyone can open one page and follow **one real CT scan** through **every step Sybil actually
performs**, using the numbers that scan really produced, not a schematic. Things that would clutter
the screen are summarised (channel means, a handful of channels), never invented.

## The case

NLST participant **217203**, third screening scan (T2), Siemens Sensation 64, B30f kernel,
186 slices of 512×512 at 0.645 mm, 2.0 mm thick. Diagnosed with stage IA lung cancer 0.2 years
after this scan; the ensemble gives a calibrated 6-year risk of 71.5%. The same person anchors the
research page (T0 → T1 → T2 risk 40% → 65% → 72%), so both pages tell one story. Attention peaks on
a spiculated lesion in the left lower lobe.

## How the data is captured (`backend/scripts/capture_visualiser.py`)

One run on this Mac (~25 min, CPU), every step logged with timings and kept in `case.json`:

| Step | What the code really does | What is recorded |
|---|---|---|
| download | `idc-index` fetches one series (98 MB, 186 DICOMs) | size, time |
| read | `Serie` sorts slices by `ImagePositionPatient` | spacing, thickness, z range |
| window | HU via modality LUT; window centre −600, width 1500; 16-bit then `//256` | HU histogram of the hotspot slice, before/after images, 186-slice atlas |
| resize | `cv2.resize` 512→256 bilinear; `(x−128.1722)/87.1849`; grey copied to 3 channels | tensor stats, example slice |
| resample | `torchio.Resample` to 0.703×0.703×2.5 mm, using the DICOM spacing on the 256 grid | 235×235×149 shape, example slice |
| pad | `CropOrPad` to 256×256×200 with zeros (the mean grey after normalising) | pad counts (26 before, 25 after, 11 px), 200-slice atlas; asserted equal to `Serie.get_volume()` |
| stem | `Conv3d(3→64, k=3×7×7, s=1×2×2)` + BatchNorm + ReLU | one output voxel recomputed by hand (patch · weights → BN → ReLU) and checked against the hooked value; all 64 filters; all 64 response maps on the hotspot slice |
| layer1–4 | r3d_18 residual stages | per stage: shape, channel-mean volume atlas, top-16 channels at the hotspot slab, fraction zeroed by ReLU, receptive field |
| attention 1 | `Simple_AttentionPool_MultiImg`: softmax over the 16×16 positions of each of 25 slabs, then `Simple_AttentionPool` over the 25 slabs | 25×256 and 25 weights, every model |
| attention 2 | per-slab max → `Conv1d(512,512,k=11)` → attention over slabs | 512×25 per-slab max, 25 weights |
| global max | max over all 25×16×16 positions | 512 values |
| hidden | concat 3×512 → `Linear(1536,512)` → ReLU (dropout off in eval) | pre- and post-ReLU vectors |
| hazards | `hazard_fc` 512→6, ReLU; `base_hazard_fc` 512→1; upper-triangular sum; sigmoid | raw hazards, base, cumulative logits, probabilities, top contributing hidden units |
| ensemble | 5 models, mean of sigmoids, per-year isotonic calibrator | every model's curve, mean, calibrator curves, final; checked against the app's cached run |

Output: `frontend/public/visualiser/217203_T2/` (`case.json` + WebP atlases, a few MB), shipped with
the frontend so the page needs neither the model nor a backend and always replays the same run.

## The page (`?view=visualiser`)

Layout: step rail on the left, a three.js stage in the middle (dark scan panel), the explanation and
the real numbers for the current step beside it, and the run log underneath with the lines for the
current step highlighted. Play steps through automatically; every step has its own camera preset
and can be orbited.

1. **The scan is a stack.** 186 textured planes at true physical spacing (330×330×372 mm). Air is
   transparent, tissue opaque, so the stack reads as a volume. A scrubber lifts one slice out.
2. **Hounsfield units → grey.** Histogram of the hotspot slice in HU with the lung window band, the
   slice before and after (2D panel).
3. **Resize, resample, pad.** The stack morphs from 186 slices at 2 mm to 149 at 2.5 mm, then gains
   26 + 25 grey padding slices and an 11-pixel border: the exact 200×256×256 the network sees.
4. **The input tensor.** Three identical channels fan out and merge: 1×3×200×256×256 = 39.3 M numbers.
5. **Sliding window.** A 3×7×7 box rolls over input slice 92 with stride 2 in-plane; the output map
   for the most active filter fills in behind it. Side panel: that filter's real weights, the real
   patch under it, the dot product, BatchNorm, ReLU, and the hooked value it must equal. A gallery
   shows all 64 filters and their responses.
6. **Deeper and coarser.** Six blocks side by side, same anatomy, coarser grids, more channels
   (200×256² → 25×16²×512), each textured with its real channel-mean activations. One layer4 voxel
   at the hotspot lights up its receptive field on the input stack.
7. **Where to look inside each slab.** 25 16×16 attention maps, each summing to 1, stacked over the
   slabs they summarise; the hotspot slab drawn over its CT slice.
8. **Which slabs matter.** Both slab-attention branches as bars along the stack, and their product
   with the in-slab maps: the heatmap the app overlays.
9. **Three summaries → 512 numbers.** Attention-pooled, max+conv1d-pooled and globally max-pooled
   vectors as 512-cell strips, concatenated, projected, ReLU'd.
10. **Six output neurons.** Raw hazards, ReLU, base hazard, cumulative sum, sigmoid: the stacked bars
    become the risk curve; the hidden units that drive each year.
11. **Five models and calibration.** Five curves, their mean, each year's isotonic map, the final
    curve, and what happened to the person.

Out of scope: gradients, training, and claims about what individual channels "mean".
