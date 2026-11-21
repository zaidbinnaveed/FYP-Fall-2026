# Datasheet: primary benchmark dataset (Kaggle/Rahman, `oscc-unified-v1`)

The full datasheet (composition, collection, preprocessing, uses, audit counts) is part of the remaining R1 work. This file starts with the limitations that are already known.

## Known limitations

### L1. No patient or slide identifiers: same-patient images may fall in different splits

**What we checked (18 Nov 2026).** The original release by Rahman et al. on GitHub (`Tabassum2019/A-histopathological-image-repository-of-normal-epithelium-of-Oral-Cavity-and-OSCC`, last commit `a8ed534`, 6 Dec 2019) was read through the GitHub API. It contains **only a `README.md`**: no images, no CSV, no metadata, no releases. The README points to Mendeley Data (`data.mendeley.com/datasets/ftmp4cvtmb/1`) and states:
- 1,224 images: 89 Normal + 439 OSCC at 100x, and 201 Normal + 495 OSCC at 400x (these match the Kaggle originals: 290 Normal, 934 OSCC);
- the slides came from **230 patients**.

Neither the GitHub release nor the Kaggle copy maps an image (for example `Normal_100x_12.jpg`) to a patient or slide. The Mendeley release was not inspected in this check.

**Consequence.** With 1,224 images from 230 patients, most patients contribute several images. The split is grouped by pHash similarity clusters (a documented deviation from patient grouping, CLAUDE.md §4). This removes exact and near-duplicate copies, but it cannot detect:
- the same patient imaged at both 100x and 400x (different fields and scales look different to pHash);
- different fields of the same slide at the same magnification.

Images of one patient can therefore appear in both training and test. Test metrics may be **optimistic** compared with performance on unseen patients. The effect is the same for all four models, so the CNN-vs-ViT comparison is less affected than the absolute numbers.

**Mitigations.**
- The limitation is stated in every report that uses this split.
- The Multi-OSCC external test set (positives only) gives a check on data from other patients.
- If patient or slide identifiers are found later (for example in the Mendeley release): when they are part of the file path, `prepare --group-regex` groups by them without code changes; a separate mapping file would need a small addition to `prepare`.
