# Datasheet: OSCC histopathology benchmark (`oscc-unified-v1`)

Plan R1 step 9 (SRS user-documentation item). Precedence: SDS > SRS > Proposal.

> **Status (21 Nov 2026).** The university run has not happened yet, so no reportable composition numbers exist. This datasheet uses two clearly marked sources:
> - **Dry run (full dataset, manifest only).** `oscc-ml prepare --manifest-only` on the complete extracted Kaggle copy, on the team laptop. It covers hashing, deduplication, label-conflict exclusion, grouping, the split and the leakage test, but no patches. The evidence is in ADR-0003.
> - **SAMPLE ONLY.** The generated audit of the 60-image development sample, `docs/results/dataset_audit.md`.
>
> After the university run, regenerate the audit with `oscc-ml audit --prepared runs/dataset/oscc-unified-v1` (after `import-results`), then replace the marked numbers here with the audit's.

## 1. Purpose

Binary classification of H&E histopathology images into `oscc` and `non_oscc` (normal oral epithelium), for the reproducible CNN-vs-ViT benchmark (research deliverable R). The same images, with their patient groups unknown (see L1), feed training, validation and testing of all four models under one protocol (`ml_research/configs/protocol.yaml`).

**Not for clinical use.** The data and every model trained on it are for research and for a screening aid with a non-diagnostic disclaimer (SRS Appendix B). They are not for diagnosis.

## 2. Sources, citations and licences

Licences were taken only from the dataset pages and APIs, read on 21 Nov 2026.

| Ref | What it is | Role here | Licence (as stated by the source) |
| --- | --- | --- | --- |
| **Rahman original release** | T. Y. Rahman, L. B. Mahanta, A. K. Das, J. D. Sarma, "Histopathological imaging database for Oral Cancer analysis", Mendeley Data, v1 (7 Nov 2019, DOI 10.17632/ftmp4cvtmb.1) and v2 (9 Jan 2023, DOI 10.17632/ftmp4cvtmb.2). Mendeley lists two related articles: doi:10.1111/jmi.12611 and doi:10.1016/j.tice.2019.101322. A pointer README is on GitHub: `Tabassum2019/A-histopathological-image-repository-of-normal-epithelium-of-Oral-Cavity-and-OSCC`. | Origin of every image in [12] | **CC BY 4.0** (Mendeley `data_licence`) |
| **[12]** | A. F. Kebede, "Histopathological Imaging Dataset for Oral Cancer", Kaggle, `ashenafifasilkebede/dataset`, version 1 (updated 21 Jul 2021), 3.19 GB. | Primary benchmark; the copy we actually use | **CC0: Public Domain** (Kaggle page). The images are a repackaging of the CC BY 4.0 Rahman release, so we follow the stricter terms and always credit Rahman et al. |
| **[10]** | J. Guan, J. Guo, Q. Chen, J. Chen, Y. Cai, Y. He, Z. Huang, Y. Wang, Y. Xie, "Multi-OSCC", Zenodo, 13 Aug 2025, DOI 10.5281/zenodo.16842637. | External, positive-only test set (pending, §7) | **CC-BY-SA-4.0** (Zenodo record metadata) |
| **[11]** | J. Guan, "OSCC-PathologyImageDataset", GitHub, commit `8e71e79`. Companion paper: arXiv:2507.16360, as cited in the repository README. | Labels, split file and clinical table for [10] | **GPL-3.0** (GitHub repository licence; it covers the repository contents, the images are on Zenodo) |

Not used here (decision O9, needs supervisor approval): any other external dataset.

## 3. How the data was obtained

- **[12]:** downloaded from Kaggle by the team and extracted to `ml_research/data/raw/kaggle_kebede/`, which is read-only. It holds 5,192 JPEG files in `{train,val,test}/{Normal,OSCC}`:

  | Folder | Normal | OSCC |
  | --- | --- | --- |
  | train | 2,435 | 2,511 |
  | val | 28 | 92 |
  | test | 31 | 95 |

- **Link to the Rahman release.** Checked without downloading any image: the Mendeley file listing (1,224 JPEGs with per-file SHA-256) was compared with the Kaggle copy.
  - All 1,224 Kaggle original file names appear in the Mendeley listing.
  - The 60 development-sample originals are byte-identical to their Mendeley counterparts.
  - Mendeley v1 and v2 hold the same 1,224 files.
- **[11]:** six metadata files only, about 0.7 MB, in `ml_research/data/raw/multi_oscc_github/`: README, LICENSE, `Data/all_metadata.json`, `Data/split_seed=2024.json` and two clinical CSVs. No images.
- **[10]:** the file list was read through the Zenodo API. Nothing was downloaded (§7).

## 4. Composition

**Source files ([12], full copy).**
- 1,224 originals: 290 Normal and 934 OSCC.
  - 100x: 89 Normal and 439 OSCC.
  - 400x: 201 Normal and 495 OSCC.
  - These match the Rahman description of 230 patients.
- 3,968 publisher augmented copies (`aug_<n>_<n>.jpg`, 224×224, train folder only).
- Originals are mostly 2048×1536 or 1536×2048.

**After preparation — dry run, full dataset, manifest only (21 Nov 2026; see ADR-0003).**

| Quantity | Value |
| --- | --- |
| `aug_` copies excluded by name | 3,968 |
| Same-label duplicates removed | 11 |
| Images excluded for label conflict (18 clusters: 14 byte-identical, 4 near-duplicate) | 41 |
| Kept images | **1,172** |
| Groups | 1,066 (largest 34) |
| train | 824 images (191 non-OSCC / 633 OSCC) |
| val | 175 images (40 / 135) |
| test | 173 images (39 / 134) |
| Leakage test | passed |

Patch counts, the tissue-filter statistics and the per-magnification table come only from the university run.

**SAMPLE ONLY: the 60-image development sample** (`docs/results/dataset_audit.md`). 60 kept images give 2,641 patches of 224×224. The tissue filter keeps 81.5% of grid tiles, and no image is reduced to one tile. Patches per image range from 13 to 54, with a median of about 54 at 400x and about 30 at 100x.

**Labels.** `oscc` = 1 and `non_oscc` = 0, taken from the class folder name and never guessed (`prepare` stops on a path with no class folder). Magnification comes from the file name (`100x` / `400x`).

**Class balance.** About 23% of the kept images are non-OSCC (dry run). Training uses `pos_weight` from the training class ratio (protocol), and evaluation reports AUC with CIs plus metrics at τ.

## 5. Preprocessing (`oscc-ml prepare`)

1. **Hash pass.** One image at a time: SHA-256, the pHash of each of the 8 rotations/flips, width/height, label, magnification and publisher folder.
2. **Publisher augmented copies.** `aug_*` files are excluded **by name**. pHash alone cannot link a 224 px crop to its 2048 px original. The manifest records each copy's nearest original.
3. **Deduplication.** Originals within pHash Hamming distance **6** (minimum over the 8 transforms), or with the same SHA-256, form one duplicate cluster. Each cluster keeps one image: from the publisher's val/test folders if possible, then the largest.
4. **Label conflicts (ADR-0003).** A cluster whose members carry both labels is excluded as a whole. Each member gets `status = label_conflict`, and the counts go into `dataset.json`.
5. **Grouping.** No patient IDs exist (L1), so images are grouped by pHash similarity (single linkage at distance 10). This is a documented deviation from patient grouping (CLAUDE.md §4).
6. **Split.** Grouped, stratified 70:15:15 with seed 42. `prepare` stops if any split is more than 10 points off target.
7. **Leakage test.** It fails loudly if any SHA-256, duplicate cluster, group, or cross-split pair within pHash distance 10 spans two splits. `oscc-ml check-leakage` and `oscc-ml audit` re-check it from the manifest.
8. **Tiling (O5 + ADR-0002).**
   - Images below 448 px on both sides are resized to 224×224.
   - Otherwise a non-overlapping 224 px grid is used, keeping tiles with at least 50% tissue, where tissue means HSV saturation > min(Otsu, 40).
   - At most 64 evenly spaced tiles are kept per image.
   - When no tile qualifies, the one with the most tissue is kept (single-tile fallback).
   - `PREPROCESS_VERSION` is `pp-0.3.0`. The same module serves inference (D2).
9. **Normalization.** ImageNet mean/std at training time (SDS Appendix A). The baseline uses no stain normalization; decision O4 (Macenko) waits for the R3 ablation.

A regression lock (`ml_research/tests/test_prepare_regression.py`) keeps `prepare`'s output byte-identical on the development sample.

## 6. Split method

- 70:15:15, grouped and stratified by label, seed 42 (`StratifiedGroupKFold`-based), over **pHash similarity groups**.
- **No patient or slide identifiers exist**, either in the Kaggle copy or in the original release (L1). The Mendeley listing was checked on 21 Nov 2026: it has 1,224 JPEGs named `<Class>_<mag>_<n>.jpg` in four folders and no metadata file.
- The split is never changed by hand.

## 7. Multi-OSCC ([10]/[11]) — external positive-only test set (pending)

- **Role (plan §3, decision 3).** Test only, positives only, never used for training or threshold selection. It measures recall at τ on OSCC from an unseen source, per magnification (×400 is the closest match to [12]).
- **What the metadata holds** ([11], `all_metadata.json`):
  - 1,325 patients, all OSCC, one record per patient: `pid`, six within-OSCC task labels and a `path` to `./Data/NpyData/<pid>.npy`.
  - The six labels: TD 0/1/2 = 450/692/183, CE 112 positive, TI 618, PI 244, LNM 497, REC 275.
  - `split_seed=2024.json` splits the patients 925 / 200 / 200 (train / valid / test). All 1,325 IDs are unique and all appear in the metadata.
  - `clinical_data_2024.csv` has 1,325 rows of clinical variables. It is not used here.
  - There is no normal tissue, so it cannot test specificity.
- **Images.** They are not in the GitHub repository. Zenodo [10] holds one file, `Multi-OSCCPI-Dataset.zip`, of 34,597,662,319 bytes (≈ 34.6 GB, md5 `46e9df38e6a406b3952134b3be973bf4`). From the README and the metadata paths, it contains six images per patient (two each at ×200, ×400 and ×1000) stored as per-patient `.npy` arrays. That layout has not been checked against the actual files, because nothing was downloaded.
- **Status.** The Zenodo API answered from the team laptop on 21 Nov 2026, but the archive is too large for the laptop's connection. **Images pending:** download on the university network, then an import step that reads only the ×400 (or all) images of the 200 test-split patients, or of all patients. That step is not written yet.

## 8. Uses

- Intended: the CNN-vs-ViT benchmark and the screening demo, always with the non-diagnostic disclaimer.
- Out of scope: clinical diagnosis, prognosis, any claim about patients outside these sources, and redistribution without the credits in §2.

## 9. Known limitations

### L1. No patient or slide identifiers: images of one patient may fall in different splits

- **GitHub check (18 Nov 2026).** The Rahman GitHub repository (`Tabassum2019/...`, last commit `a8ed534`) contains only a README. It points to Mendeley and states 230 patients.
- **Mendeley check (21 Nov 2026).** Dataset page and file listing only, no image downloads. Both versions hold just the 1,224 JPEGs (`<Class>_<mag>_<n>.jpg`). There is no metadata file and no patient or slide field, so no patient-to-image mapping exists.

**Consequence.** With 1,224 images from 230 patients, most patients contribute several images. pHash grouping removes copies and near-copies but cannot detect:
- the same patient at 100x and 400x;
- different fields of one slide.

Test metrics may therefore be **optimistic** compared with unseen patients. The bias is the same for all four models, so the comparison suffers less than the absolute numbers.

**Mitigations.**
- The limitation is stated in every report that uses the split.
- The Multi-OSCC external test (§7) gives a check on unseen patients.
- If identifiers ever appear in file paths, `prepare --group-regex` uses them without code changes.

### L2. The source files some images under both classes

The Rahman release, and therefore [12], contains 14 byte-identical Normal/OSCC pairs, for example `Normal_400x_181.jpg` = `OSCC_400x_116.jpg`. Visual checks found 3 more genuine near-duplicate pairs: re-encodes and one rotated copy. These sit in consecutive numbering blocks (for example `Normal_100x_69`–`74` ↔ `OSCC_100x_345`–`350`), which suggests a filing error in the release.

The correct label is unknown, so all members are excluded (ADR-0003). Other mislabelled images that are not duplicates cannot be detected this way.

### L3. pHash threshold at its edge

At distance 6, a few unrelated images are matched:
- one false near-duplicate label-conflict cluster (`dup-00052`: 5 different fields, so 5 usable images excluded);
- one false same-label duplicate (`OSCC_100x_153` ↔ `OSCC_100x_108`, 1 image dropped).

Leakage is unaffected, because grouping at distance 10 keeps similar images in one split. The threshold is unchanged pending a team decision.

### L4. Imbalance and acquisition

- About 23% of kept images are non-OSCC, and Normal at 100x is the smallest cell (89 originals).
- All images come from one source, captured on a Leica ICC50 HD microscope according to the Mendeley description. Results may not transfer to other microscopes or scanners. This is what RQ3 and Multi-OSCC address.

### L5. Multi-OSCC images not yet available

Only the metadata is local (§7). Until the archive is obtained, there is no external-test result. Reports must say "not yet run".

## 10. Notes for model cards (threats to validity, not dataset limitations)

- **ViT normalization.** The protocol normalizes every model with ImageNet mean/std, as the SDS fixes. The HuggingFace `google/vit-base-patch16-224` checkpoint was trained with mean = std = 0.5, so the ViT sees inputs shifted from its pretraining statistics while the CNNs do not. This is kept for protocol fidelity and must be stated in the ViT model card.
- **Pretraining data differ.**
  - The three CNNs use torchvision `IMAGENET1K_V1` weights (ImageNet-1k).
  - `google/vit-base-patch16-224` was pretrained on ImageNet-21k and fine-tuned on ImageNet-1k, according to its model card.
  - A CNN-vs-ViT difference therefore mixes architecture with pretraining data volume. State this in every model card and in the comparative analysis.
- **Same patches for every model.** All four models see identical patches (tiling fixed by ADR-0002) and the same split, so data differences do not explain model differences.
