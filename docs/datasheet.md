# Datasheet: primary benchmark dataset (Kaggle/Rahman, `oscc-unified-v1`)

The full datasheet (composition, collection, preprocessing, uses, audit counts) is part of the remaining R1 work (open PR #21 extends it). This file records the sources, the verified counts and the limitations that are already known. Every number below comes from a saved script output named next to it.

## Sources and licences

| Source | What it is | Licence (as stated by the source) | Evidence |
| --- | --- | --- | --- |
| Rahman et al., Mendeley Data `ftmp4cvtmb`, **v1** (DOI `10.17632/ftmp4cvtmb.1`, published 2019-11-07) and **v2** (DOI `10.17632/ftmp4cvtmb.2`) | Original release: 1,224 JPEGs in 4 folders (Normal/OSCC × 100x/400x) | **CC BY 4.0** in both versions (`data_licence.short_name` of the Mendeley API record) | API listings saved 22 Nov 2026 (`retrieved_at_utc` 13:48:35Z for v1). **v1 = v2:** the same 1,224 files with the same names, sizes and SHA-256 (compared from the two saved listings). |
| Kebede, Kaggle copy (SRS [12]) | Repackaging of the same 1,224 originals into train/val/test folders, plus 3,968 publisher augmented copies (`aug_*.jpg`, train only) | **"CC0: Public Domain"** as stated on the Kaggle dataset page (JSON-LD `license` field, page retrieved 2026-11-22T13:49:44Z). Because the images are Rahman et al.'s, we credit them under CC BY 4.0 as well. | All 1,224 Kaggle originals are byte-identical (SHA-256) to the Mendeley v2 files: 0 missing on either side (audit §4.1). |
| Rahman et al. GitHub repository | README only (no images) | — | Read on 18 Nov 2026 (L1 below) |

## Composition after cleaning (`prepare`, ADR-0003 + ADR-0005)

Produced by `oscc-ml prepare --manifest-only` and reproduced independently by
`ml_research/scripts/audit/verify_dataset_independent.py` (46/46 checks, two byte-identical runs,
22 Nov 2026):

- 5,192 files = 1,224 originals (290 Normal, 934 OSCC; 89/439 at 100x, 201/495 at 400x) + 3,968
  publisher augmented copies, excluded by name.
- 17 label-conflict clusters (14 byte-identical, 3 near-duplicate): **35 images excluded** (ADR-0003).
- 10 duplicates removed (threshold 4 plus the 2 reviewed same-field pairs, ADR-0005).
- **1,179 images kept**; split **829 / 174 / 176** (train / val / test); non-OSCC/OSCC per split
  191/638, 39/135, 41/135.
- Kept image sizes: 956 are 2048×1536, 222 are 1536×2048, 1 is 1435×916 (supersedes the plan's
  "about 2040×1536", audit m3).
- No two kept images in different splits are within pHash distance 10; the closest cross-split pair
  is at 12. pHash distances are always even (each 64-bit pHash has exactly 32 one-bits, checked on
  all 5,192 files), so thresholds 4/5, 6/7 and 10/11 behave identically (audit m7, ADR-0005).

## The publisher's Kaggle split leaks (audit m8)

Among the 1,224 originals, 16 groups of byte-identical files exist. **7 of them span the
publisher's own train/val/test folders, and 6 of those carry opposite labels** (the same file is
published as Normal in one folder and OSCC in another). Recomputed from the verifier's `files.csv`
(22 Nov 2026): 16 / 7 / 6. Any result reported on the publisher's split is therefore partly
measured on images seen in training, sometimes with the opposite label. This is one reason why
published accuracies on this dataset are not comparable with our leak-free re-split (plan §3
consequence 7). Our `prepare` ignores the publisher's split and excludes conflicting clusters.

## Multi-OSCC (deferred, audit M6)

The Multi-OSCC external positive test set (plan R1 step 6) is **deferred to FYP-II** (RQ3). Its
archive is a single 34.6 GB file, which cannot be downloaded over the team laptop's connection.
It is not needed for the FYP-I baselines and is never used for training in the primary benchmark.

## Known limitations

### L1. No patient or slide identifiers: same-patient images may fall in different splits

**What we checked (18 Nov 2026).** The original release by Rahman et al. on GitHub (`Tabassum2019/A-histopathological-image-repository-of-normal-epithelium-of-Oral-Cavity-and-OSCC`, last commit `a8ed534`, 6 Dec 2019) was read through the GitHub API. It contains **only a `README.md`**: no images, no CSV, no metadata, no releases. The README points to Mendeley Data (`data.mendeley.com/datasets/ftmp4cvtmb/1`) and states:
- 1,224 images: 89 Normal + 439 OSCC at 100x, and 201 Normal + 495 OSCC at 400x (these match the Kaggle originals: 290 Normal, 934 OSCC);
- the slides came from **230 patients**.

Neither the GitHub release nor the Kaggle copy maps an image (for example `Normal_100x_12.jpg`) to a patient or slide. The Mendeley release was inspected on 21–22 Nov 2026 (see "Sources and licences" below): it has no patient or slide identifier either.

**Consequence.** With 1,224 images from 230 patients, most patients contribute several images. The split is grouped by pHash similarity clusters (a documented deviation from patient grouping, CLAUDE.md §4). This removes exact and near-duplicate copies, but it cannot detect:
- the same patient imaged at both 100x and 400x (different fields and scales look different to pHash);
- different fields of the same slide at the same magnification.

Images of one patient can therefore appear in both training and test. Test metrics may be **optimistic** compared with performance on unseen patients. The effect is the same for all four models, so the CNN-vs-ViT comparison is less affected than the absolute numbers.

**Mitigations.**
- The limitation is stated in every report that uses this split.
- The Multi-OSCC external test set (positives only) gives a check on data from other patients.
- If patient or slide identifiers are found later (for example in the Mendeley release): when they are part of the file path, `prepare --group-regex` groups by them without code changes; a separate mapping file would need a small addition to `prepare`.
