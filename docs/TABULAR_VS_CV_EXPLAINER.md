# Tabular vs computer-vision classification in this project (viva explainer)

Supervisor requirement (FYP-I, verbatim): "Student must have a clear concept of using tabulated data
and computer vision based image classification for their project." This page explains both routes
on **our** data and where the evidence is in the repository. Numbers are not repeated here; they are
generated into [`results/TABULAR_RESULTS.md`](results/TABULAR_RESULTS.md) (tabular) and, after the
university run, `results/baseline_fyp1.md` / `results/MODEL_SELECTION.md` (all models).

## 1. The same question, two representations

Both routes answer one question: *is this H&E image of oral tissue OSCC or non-OSCC?* Both use the
**same 1,179 images and the same grouped 70:15:15 split** (829 / 174 / 176), produced once by
`oscc-ml prepare` (ADR-0003, ADR-0005). Only the representation of an image differs.

| | Tabular (classical machine learning) | Computer vision (deep learning) |
| --- | --- | --- |
| What one image becomes | One **row** of 67 numbers chosen by us (colour, stain, texture, nuclei-density proxies) | A grid of 224×224 **pixel patches** (3 colour channels each) |
| Who decides what matters | The team, through feature design (domain knowledge) | The network learns its own features from pixels |
| Models | Logistic regression, random forest, gradient boosting (scikit-learn) | ResNet50, EfficientNet-B0, DenseNet121 (CNNs), ViT-B/16 (transformer), PyTorch |
| Data needed / compute | Small; trains in minutes on a laptop CPU | Pretrained on ImageNet, fine-tuned on a GPU for hours |
| Explanation | Coefficients and permutation importance per named feature | Heat maps (Grad-CAM, attention rollout) over the image |
| Typical weakness | Cannot see tissue architecture beyond what the features encode | Can pick up shortcuts invisible to people; needs more data and compute |

## 2. How an image becomes a table row (our pipeline)

`oscc-ml tabular-extract` ([ADR-0006](adr/0006-tabular-dataset-and-classifiers.md),
[data dictionary](results/TABULAR_DATA_DICTIONARY.md)):

1. read the image, check its SHA-256 against the manifest;
2. downsize 4×4 (box average) so measurements are fast and stable;
3. keep only **tissue pixels** with the same rule the CNN/ViT tiling uses (ADR-0002);
4. measure:
   - **colour** (RGB, HSV, CIE L\*a\*b\*): overall staining and brightness;
   - **H&E stain** by colour deconvolution: how much hematoxylin (binds nuclei, blue-purple) and
     eosin (cytoplasm and stroma, pink) each pixel holds;
   - **texture**: GLCM (how grey levels co-occur at 1, 2 and 4 pixels apart: contrast, homogeneity,
     correlation, …) and LBP (share of flat areas, edges, spots);
   - **nuclei-density proxies**: dark hematoxylin "blobs" per tissue area and their size spread,
     a rough stand-in for crowded, enlarged, irregular nuclei;
5. write one row per image; split and label are copied from the manifest.

Magnification and image size are kept as **metadata**, not features: the classes are not equally
frequent at 100x and 400x, so a model could otherwise learn "magnification → label".

## 3. How the computer-vision route works (our pipeline)

`oscc-ml prepare` cuts each kept image into up to 64 tissue patches of 224×224 px; every patch
inherits its image's label. A pretrained network is fine-tuned on training patches with one shared
protocol (SDS Appendix A; ADR-0004): flips/rotations and mild colour jitter, AdamW, class-weighted
loss, early stopping on validation AUC. At test time the **image probability is the mean of its patch
probabilities**, so both routes are scored per image.

## 4. Evaluated the same way

Both routes share one evaluation (`oscc_ml.eval`):

- the threshold τ is chosen on **validation** (target recall 0.95, highest F1), never on test;
- **test is used once**; 95% confidence intervals by a bootstrap that resamples similarity groups;
- per-magnification metrics, calibration (ECE), confusion matrix, false-positive/false-negative lists;
- the three-band outcome (`oscc_suspected` / `inconclusive` / `non_oscc`) with margin 0.05;
- paired tests between any two models on the same test images (ΔAUC bootstrap, McNemar, Holm).

Run folders have the same format for both, so one report compares tabular, CNN and ViT side by side.

## 5. The shortcut check: why we test the data, not just the models

`oscc-ml tabular-shortcut` trains a classifier on cues that are **not pathology**: file size, JPEG
settings, image size, the whole-frame colour histogram, and magnification alone. If these predict the
label well, any model (tabular or CNN) might be using them. The rule was fixed before the run
(test AUC ≥ 0.80 = major finding) and the result is published whatever it is, in
`results/TABULAR_RESULTS.md`.

## 6. Likely viva questions

- **Why have a tabular route at all if CNNs are stronger?** It is transparent (named features,
  permutation importance), cheap (laptop CPU) and gives a baseline that shows how much the deep models
  add beyond colour, texture and nuclear density.
- **Is the comparison fair?** Same images, same split, same τ rule, same CIs and test-once rule; the
  tabular models are tuned only on training folds grouped like the split.
- **What can the tabular features not capture?** Architecture: invasion through the basement
  membrane, keratin pearls, loss of stratification. These need spatial context that a CNN/ViT sees in
  a patch but a per-image average does not.
- **Why per-image rather than per-patch features?** One row per image matches the outcome unit and
  keeps rows independent within a group; patch rows of one image would be highly correlated.
- **Could the models be learning the scanner instead of the disease?** That is exactly what the
  shortcut check measures; see its numbers in the results file.

## 7. Source on the dataset

Rahman TY, Mahanta LB, Das AK, Sarma JD. *Histopathological imaging database for oral cancer
analysis.* Data in Brief 2020;29:105114. doi:10.1016/j.dib.2020.105114 (open access, PMC6994517;
opened and checked 23 Nov 2026). The paper states that the repository holds 1,224 images (89 normal
and 439 OSCC at 100x; 201 normal and 495 OSCC at 400x) of H&E-stained biopsy slides from 230
patients, captured with a Leica DM 750 microscope and ICC50 HD camera, and that the patients'
pathology reports were used to label the images. It gives no patient identifier per image, which
is why our split is grouped by image similarity rather than by patient (errata E7). The paper gives
the image size as 2048×1536; our measurement of the kept images also found 222 portrait
(1536×2048) images and one of 1435×916 (`docs/datasheet.md`).
