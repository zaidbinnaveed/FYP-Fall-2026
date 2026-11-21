# ADR-0002: O5 amendment — capped tissue threshold

- **Status:** Accepted by the team on 18 Nov 2026, after the Phase B review.
- **Amends:** decision O5 (plan §4.2, tiling rule). Everything else in O5 is unchanged.
- **Precedence:** SDS > SRS > Proposal. The SDS fixes the 224×224 patch size but does not define the tissue filter, so this ADR fills a gap and overrides nothing in those documents.

## Context

O5 keeps a 224×224 grid tile when at least 50% of its pixels are tissue, where tissue means HSV saturation above the image's **Otsu threshold**.

The Kaggle/Rahman images are microscope frames, and most of them are almost entirely tissue with little or no glass. On such frames Otsu has no glass/tissue split to find. It separates pale eosin-stained tissue from dense haematoxylin-stained tissue instead, and pale tissue is then treated as background.

## Evidence

Measured on the local 60-image development sample of the real dataset (`oscc-ml make-sample --per-class 30`, seed 42; 15 or more images from each class and magnification except Normal 100x, which has 5). This is a development check, not a reported result.

| Rule | Grid tiles kept (≥ 50% tissue) | Images reduced to one fallback tile |
| --- | --- | --- |
| Plain Otsu (original O5) | 1,003 / 3,240 = **31%** | **11 / 60** |
| Otsu capped at 40 (this ADR) | 2,641 / 3,240 = **82%** | **0 / 60** |

The visual check is `docs/results/tissue_filter_check.png`. It shows 24 kept and 24 dropped patches under the capped rule. The kept tiles come from 20 different images and the dropped tiles from 22, covering both classes and both magnifications. Kept tiles that plain Otsu would have dropped have a blue frame.

## Decision

Tissue = saturation **> min(Otsu threshold, 40)** (0–255 scale). Everything else in O5 stays the same: resize below 448 px, 50% minimum tissue fraction, at most 64 evenly spaced patches, and the single-tile fallback.

- `ml_research/configs/protocol.yaml`: `data.tiling.max_tissue_threshold: 40`. It is the default, so `uni_run` needs no extra flag.
- `oscc_ml.preprocess.TilingParams` defaults to the same value, so the inference service (Phase D2) uses the same rule as training. A test checks that the module defaults equal the protocol.
- `PREPROCESS_VERSION` is now `pp-0.3.0`. Every prepared dataset records the value in `dataset.json`.
- `--max-tissue-threshold` on `prepare` / `uni-run` (`-MaxTissueThreshold` in `uni_run.ps1`) remains as an **ablation override only**. `255` gives plain Otsu.

## Consequences

- More patches per image (82% instead of 31% of grid tiles), so `prepare` writes more files and each epoch takes longer. The 64-patch cap still bounds both.
- A capped threshold also keeps some tiles with visible white space (lumen, fat, tears). The 50% fraction still drops tiles that are mostly glass.
- Pale stroma can still fall below 40 and be dropped; a few such tiles are visible in the contact sheet. Every image still keeps several tiles.
- The rule is fixed for the whole benchmark: all four models see the same patches.
