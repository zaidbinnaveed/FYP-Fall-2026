# ADR-0006: Tabular dataset and classical classifiers (proposed FR-7.11)

- **Status:** Accepted by the team on 23 Nov 2026 to meet the supervisor's FYP-I requirement
  "Complete dataset (tabular and images) … clear concept of using tabulated data and computer vision
  based image classification" ([`SCOPE_CHANGE_FYP1.md`](../SCOPE_CHANGE_FYP1.md); errata E16).
  Supervisor sign-off: [`SUPERVISOR_SIGNOFF.md`](../audit/SUPERVISOR_SIGNOFF.md) item 11.
- **Adds:** package `oscc_ml.tabular`, CLI `tabular-extract`, `tabular-check`, `tabular-train`,
  `tabular-shortcut`, `tabular-report`. **Changes nothing** in `prepare`, the split, the image
  protocol, `PREPROCESS_VERSION` or the image models.
- **Precedence:** SDS > SRS > Proposal. The SDS has no tabular track; this ADR adds one alongside
  the CNN-vs-ViT benchmark without altering it.

## Decision

1. **Same images, same split.** Input is the manifest written by `prepare` (current settings:
   ADR-0003 + ADR-0005) and the raw folder. The kept images (status `ok`, split train/val/test)
   are measured; split, label, magnification and group come only from the manifest. No new split.
2. **Features** (69 columns incl. 2 mask diagnostics; dictionary:
   [`TABULAR_DATA_DICTIONARY.md`](../results/TABULAR_DATA_DICTIONARY.md)): RGB/HSV/L\*a\*b\*
   colour statistics; H&E colour deconvolution (Ruifrok-Johnston vectors, optical density);
   GLCM at distances 1/2/4 averaged over four angles; uniform rotation-invariant LBP; nuclei-density
   proxies (dark hematoxylin blobs). Measured on a 4x4 box-downsized copy
   (`PIL.Image.reduce(4)`) inside the **same tissue rule as training** (ADR-0002, saturation >
   min(Otsu, 40)). NumPy/SciPy/Pillow only, so no new dependency and an unchanged lockfile.
3. **Magnification and image size are metadata**, never model inputs. A separate ablation adds
   `is_400x`; its runs have `purpose: ablation` and never enter the main table.
4. **Models:** logistic regression (standardised inputs), random forest, histogram gradient boosting
   (scikit-learn), all with balanced class weights, inside a `Pipeline` fitted on train only.
5. **Tuning:** small grids, grouped 5-fold CV on train (`StratifiedGroupKFold` over the manifest
   `group_id`, ROC AUC); refit on all of train. Validation is used only for tau and permutation
   importance; **test is used once**, after tau is fixed.
6. **Evaluation identical to the image models:** tau from validation (target recall 0.95, max F1),
   95% grouped-bootstrap CIs (2,000 resamples over `group_id`), per-magnification metrics, ECE,
   confusion matrix with FP/FN lists, outcome bands with margin 0.05. Run folders use the image-run
   format, so `report` and the paired comparisons (`comparisons.json`) treat all models alike.
7. **Shortcut check:** gradient boosting (defaults, no tuning) on non-pathology cues only (file and
   JPEG properties, image size, whole-frame colour histogram), plus a magnification-only baseline.
   The rule was fixed before the run: test AUC ≥ 0.80 = MAJOR finding, ≥ 0.65 = moderate. The result
   is published whatever it is.

## Verification (Phase T)

- Known-answer tests on synthetic images (uniform colours, Lab reference colours, pure H and E
  stains, GLCM of stripes, LBP of a flat image, a drawn set of 12 "nuclei"):
  `ml_research/tests/test_tabular.py`.
- An independent second implementation of key features on a subset (different algorithms):
  `ml_research/scripts/audit/verify_tabular_independent.py`.
- Two full extractions compared byte for byte; rows = kept images; no missing values; split, label,
  magnification and group equal to the manifest (checked inside `tabular-extract` and by
  `tabular-check`).

## Consequences

- The FYP-I deliverable "tabular dataset" is a reproducible file with a recorded SHA-256, rebuilt by
  one command from the manifest.
- Handcrafted features are a transparent, cheap baseline; they are expected to trail the CNN/ViT if
  the image models learn richer patterns, and that comparison is itself a finding.
- The nuclei features are proxies at reduced resolution (1 downsized pixel = 16 original pixels), not
  a nucleus segmentation; the stain vectors are generic. Both limitations are stated in the
  dictionary and the datasheet.
