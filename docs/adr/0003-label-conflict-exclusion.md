# ADR-0003: Exclude duplicate clusters that carry both labels

- **Status:** Accepted by the team lead on 21 Nov 2026, before the university run.
- **Amends:** `oscc-ml prepare` (plan R1, deduplication step). Tiling, normalisation, the split rule, the leakage test, `protocol.yaml` and `PREPROCESS_VERSION` (pp-0.3.0) are unchanged.
- **Precedence:** SDS > SRS > Proposal. Neither the SDS nor the SRS says what to do with an image that is published under both classes, so this ADR fills a gap and overrides nothing.

## Context

`prepare` groups originals into duplicate clusters. Two images fall in the same cluster when they are byte-identical (SHA-256) or close in pHash (minimum over the 8 dihedral transforms ≤ `duplicate_threshold`, 6), and each cluster keeps one representative.

Until now, a cluster whose members carry both labels stopped `prepare` with "duplicate cluster(s) contain both labels". The 60-image development sample never contained both members of such a pair, so neither the sample nor CI ever reached this check.

The original Rahman release contains such pairs. The Mendeley Data listing for `ftmp4cvtmb` (version 2, 1,224 JPEGs) gives a SHA-256 for every file. It shows 16 groups of byte-identical files, and 14 of those groups are the same image filed once as Normal and once as OSCC, for example `Normal_400x_181.jpg` = `OSCC_400x_116.jpg`. All 28 files are in the Kaggle copy, byte-identical (checked by SHA-256 on 21 Nov 2026).

With the previous code the university run would have failed at its first step.

## Decision

Every duplicate cluster whose members carry both labels is **excluded as a whole**, because the correct label cannot be known. This applies to byte-identical clusters (SHA-256) and to pHash near-duplicate clusters alike.

- `manifest.csv`: each member keeps its `duplicate_cluster` and gets `status = label_conflict` and `split = excluded`. No column was added.
- `dataset.json` gains three keys:
  - `n_label_conflict_clusters`, as `{byte_identical, near_duplicate}`. A cluster counts as byte-identical when two of its members with different labels share a SHA-256.
  - `n_label_conflict_images_excluded`.
  - `label_conflicts`, listing each cluster with its paths.
- `n_unreadable` now counts only unreadable images. Before this change it counted every status other than `ok`, which was the same thing until now.
- `prepare` logs `N duplicate cluster(s) carry both labels (...)` as a warning and continues.
- New: `oscc-ml prepare --manifest-only --out <new folder>` is a dry run of everything up to the split and the leakage test. It streams one image at a time and writes no patches. It writes `manifest_only.json` instead of `dataset.json`, so its output can never be used as a training dataset, and it refuses to write into an existing prepared dataset.

## Evidence: full dataset dry run (laptop, 21 Nov 2026)

Command: `oscc-ml prepare --raw data/raw/kaggle_kebede --out data/processed/full-dryrun-manifest --manifest-only`. The input is the extracted Kaggle copy: 5,192 files, 1,224 of them originals. The patch pass was not run.

| Quantity | Value |
| --- | --- |
| Source images | 5,192 (0 unreadable) |
| Publisher `aug_` copies excluded by name | 3,968 (1,016 of them pHash-match an original) |
| Same-label duplicates removed | 11 |
| Label-conflict clusters | 18: **14 byte-identical**, **4 near-duplicate** |
| Images excluded for label conflict | 41 |
| Kept images | 1,172 (1,224 − 11 − 41) |
| Groups (pHash similarity, no patient IDs) | 1,066; largest group 34 images |
| Split train / val / test | 824 / 175 / 173 images (70.3% / 14.9% / 14.8%) |
| Non-OSCC / OSCC per split | train 191 / 633 · val 40 / 135 · test 39 / 134 |
| Leakage test | passed |

These counts come from a dry run. The reportable numbers are the ones the university run writes to `dataset.json`.

A visual check of the four near-duplicate conflict clusters found:

- `OSCC_100x_350` / `Normal_100x_69` and `OSCC_100x_348` / `Normal_100x_71`: pHash distance 0. The same image, re-encoded.
- `Normal_100x_70` / `OSCC_100x_349`: the same image rotated 90°.
- `dup-00052`: **a false match.** Five different fields (`OSCC_100x_256`, `Normal_400x_188`, `OSCC_100x_64`, `OSCC_100x_66`, `OSCC_400x_489`) at different magnifications. They are chained together by single linkage, with every link at exactly the threshold distance of 6.

The genuine near-duplicate conflicts sit in the same numbering block as the byte-identical ones (`Normal_100x_69`–`74` ↔ `OSCC_100x_345`–`350`). That pattern suggests a systematic filing error in the release, not chance.

## Consequences

- The full run no longer aborts. 41 of 1,224 originals (3.3%) are excluded for label conflicts. Five of these come from the false-match cluster `dup-00052` and would be usable under a stricter pHash threshold. That is an open question for the team: `duplicate_threshold` is unchanged here.
- The same edge effect exists in same-label deduplication. One of the 11 removals (`OSCC_100x_153` ↔ `OSCC_100x_108`) is a false match at distance 6. Leakage is not affected, because grouping at distance 10 still keeps similar images in one split.
- The regression lock (`tests/test_prepare_regression.py`) proves that the development sample and a synthetic uncompressed BMP set give byte-identical manifests and patches before and after this change. The three new `dataset.json` keys are checked separately.
- CI covers the case on every run: `make-test-zip --label-conflicts 2` adds one byte-identical pair and one near-duplicate pair, and the `uni_run` jobs on Ubuntu and Windows check that the run reports and excludes them.
