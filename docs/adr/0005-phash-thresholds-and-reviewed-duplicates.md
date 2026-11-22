# ADR-0005: pHash duplicate threshold 4, group threshold 10, and a reviewed same-field list

- **Status:** Decided by Zaid on 22 Nov 2026, before the university run (decision B1 of the FYP-I
  audit, option (b)). The two reviewed pairs await Zaid's own visual confirmation
  (`reviewer: Claude Code, pending Zaid confirmation` in the list). Supervisor sign-off: see
  `docs/audit/SUPERVISOR_SIGNOFF.md`.
- **Amends:** `oscc-ml prepare` deduplication (plan R1 step 3: "pHash Hamming ≤ 6, tune by visual
  inspection of a sample"). Tiling, normalisation, the split rule, the leakage test, `protocol.yaml`
  and `PREPROCESS_VERSION` (pp-0.3.0) are unchanged.
- **Supersedes** the threshold-6 counts in ADR-0003 (its rule, excluding mixed-label duplicate
  clusters, is unchanged).
- **Precedence:** SDS > SRS > Proposal. The SDS says "perceptual-hash deduplication" without a
  threshold; the plan's ≤ 6 was a starting value to be tuned. This ADR fills a gap.

## Decision

1. **Duplicate threshold 4** (was 6): two originals are copies if their transform-invariant pHash
   distance is ≤ 4 (`PrepareSettings.duplicate_threshold`, CLI `--duplicate-threshold`).
2. **Group threshold 10** (unchanged): kept images within distance 10 are grouped and always go to
   the same split. This is the conservative, leak-safe choice: the split is never decided by a pair
   that pHash considers similar.
3. **Reviewed same-field list** `ml_research/configs/data/reviewed_duplicates.yaml`: pairs above the
   threshold that a reviewer confirmed show the same tissue field. `prepare` adds each pair as a link
   in the duplicate graph, so the ordinary duplicate rules apply (one representative kept; a cluster
   carrying both labels is a label conflict, ADR-0003). The list belongs to the release with 1,224
   readable originals. For that release every listed file (name + SHA-256) must be present and both
   files of a pair must have the same label, otherwise `prepare` stops. For other sources (synthetic
   data, the local sample) it is recorded as "not applicable". The status is written to
   `manifest_only.json` / `dataset.json` (`reviewed_duplicates_status`).

**Even-distance note.** Every 64-bit pHash has exactly 32 one-bits (each bit says whether a DCT
coefficient is above the median of the 64; checked on all 5,192 files), so every distance is even.
Thresholds 4 and 5, 6 and 7, 10 and 11 behave identically.

## Evidence

Contact sheets (downsized, CC BY 4.0 credit printed on each), made by
`ml_research/scripts/audit/make_pair_sheets.py` from the full dataset:

- [`docs/audit/figures/pairs_at_5-6.jpg`](../audit/figures/pairs_at_5-6.jpg) (+ `.csv`): all 9 pairs
  of originals at distance 5–6 (none is at 5). These are duplicates at threshold 6 but not at 4.
- [`docs/audit/figures/cross_split_d12.jpg`](../audit/figures/cross_split_d12.jpg) (+ `.csv`): 20
  randomly chosen (seed 42) pairs of kept images in different splits at distance 12, the closest
  cross-split distance, under this ADR's settings.

Visual check of the 9 pairs at distance 6 (at about 760 px per image):

| # | Pair | Labels / magnification | Finding |
| --- | --- | --- | --- |
| 1 | OSCC_100x_256 – Normal_400x_188 | different labels, 100x vs 400x (`dup-00052`) | Different fields |
| 2 | OSCC_100x_256 – OSCC_100x_64 | same | Different fields |
| 3 | OSCC_400x_112 – OSCC_400x_200 | same | Different tissue; only the layout (tissue lower left, glass upper right) is alike |
| 4 | Normal_400x_188 – OSCC_100x_66 | different labels, 400x vs 100x (`dup-00052`) | Different fields |
| 5 | OSCC_100x_108 – OSCC_100x_153 | same | Different fields |
| 6 | OSCC_100x_66 – OSCC_400x_489 | same label, 100x vs 400x | No visible overlap; **unconfirmed** (a higher-magnification view of the same slide cannot be ruled out). Leak-safe: the two are within distance 10 and are in one group, so in one split (verified: both in train) |
| **7** | **OSCC_100x_81 – OSCC_100x_82** | same | **Same field**, slightly shifted: the same keratin pearl and the same two holes → reviewed list |
| 8 | OSCC_400x_200 – Normal_400x_177 | different labels | Different tissue (177 is byte-identical to 112, so this is pair 3 again) |
| **9** | **OSCC_400x_417 – OSCC_400x_423** | same | **Same field**, the same cells with a different colour balance → reviewed list |

Spot check of the 20 cross-split pairs at distance 12 on the sheet: none looked like the same field
at thumbnail size (about 360 px). An earlier random 20 (drawn with threshold 4 before the reviewed
list existed) gave the same finding. This is a thumbnail-level check, **not proof** that no related
fields cross splits.

## Why option (b)

Distance 6 holds both kinds of pair: 2 genuine same-field duplicates (7, 9) and 7 false matches.
Neither threshold separates them:

- (a) threshold 6 removes the 2 true duplicates but also discards 8 distinct images (the 5 of
  `dup-00052`, `OSCC_400x_200`, and the false same-label match `OSCC_100x_153`; pair 6 unconfirmed);
- (c) threshold 4 alone keeps those 8 but also keeps both images of pairs 7 and 9 (one field counted
  twice within a split; never across splits, because the group threshold puts them in one split);
- (b) threshold 4 plus the reviewed list keeps the distinct images and removes the true duplicates.
  Every exclusion and removal at distance > 4 then rests on a visual check that is recorded and
  versioned.

## Result: full dataset, manifest-only dry run (22 Nov 2026)

Commands (from `ml_research/`):

```bash
oscc-ml prepare --raw data/raw/kaggle_kebede --manifest-only --out data/processed/audit-fyp1/prepare-adr0005
python -I scripts/audit/verify_dataset_independent.py --raw data/raw/kaggle_kebede \
  --manifest-dir data/processed/audit-fyp1/prepare-adr0005 --out data/processed/audit-fyp1/verify-adr0005-run1 \
  --zip data/export/oscc_kaggle_kebede_v1.zip --zip-root kaggle_kebede \
  --expected-zip-sha256 f75d25682388c85469995e16c543ebe4f889cbe8d4c521df37e2bbd1be4a6c0d \
  --mendeley-dir data/processed/audit-fyp1/mendeley
```

The independent verifier (no `oscc_ml` import; it parses the reviewed list itself) passed 46/46
checks, and a second run gave byte-identical outputs.

| Quantity | Threshold 6 (ADR-0003, 21 Nov) | **This ADR** |
| --- | --- | --- |
| Source images / unreadable | 5,192 / 0 | 5,192 / 0 |
| Publisher `aug_` copies excluded by name | 3,968 | 3,968 |
| … within the duplicate threshold of a kept original | 1,016 (≤ 6) | 960 (≤ 4) |
| Duplicate clusters | 1,190 | 1,196 |
| Same-label duplicates removed | 11 | **10** (2 of them by the reviewed list) |
| Label-conflict clusters (byte-identical + near-duplicate) | 18 (14 + 4) | **17 (14 + 3)** |
| Images excluded for label conflict | 41 | **35** |
| Kept images | 1,172 | **1,179** (1,224 − 10 − 35) |
| Groups; largest | 1,066; 34 | 1,056; 36 |
| Mixed-label groups (distance ≤ 10) | 15 | 14 |
| Split train / val / test | 824 / 175 / 173 | **829 / 174 / 176** |
| non-OSCC / OSCC per split | 191/633 · 40/135 · 39/134 | **191/638 · 39/135 · 41/135** |
| Cross-split SHA-256 / cluster / group / pair ≤ 10 | 0 / 0 / 0 / 0 | **0 / 0 / 0 / 0** |
| Closest cross-split pair | 12 (186 pairs) | 12 (178 pairs) |
| Reviewed list | – | applied: 2 pair(s) |
| Leakage test | passed | passed |

The 35 conflict exclusions: 29 images in the 14 clusters that contain a byte-identical Normal/OSCC
pair (28 of them byte-identical to an opposite-label file, plus `OSCC_400x_490` at distance 4 to
one), and 6 images in 3 near-duplicate clusters (`Normal_100x_69/70/71` ↔ `OSCC_100x_350/349/348`,
distance 0). `dup-00052` and `OSCC_400x_200` are no longer excluded. The reviewed pairs keep
`OSCC_100x_82` and `OSCC_400x_423` (the val-folder member, by the representative rule) and remove
`OSCC_100x_81` and `OSCC_400x_417`.

These are dry-run counts. The reportable numbers are the ones the university run writes to
`dataset.json`.

## Consequences

- The dataset changes by +7 kept images. The university run has not happened, so no result is
  invalidated.
- `tests/test_prepare_regression.py`: the synthetic BMP set and the 60-image sample give
  byte-identical manifests and patches before and after. Only `dataset.json` of the sample changed
  (`settings.duplicate_threshold`, `settings.reviewed_duplicates`, `reviewed_duplicates_status`;
  shown by a key-by-key diff). Its hash was re-recorded with that note.
- Tests: `tests/test_reviewed_duplicates.py` (loading, not-applicable case, merge with the duplicate
  rules, missing file and conflicting labels fail loudly, malformed lists rejected) and
  `tests/audit/test_verify_independent.py::test_reviewed_pairs_are_reproduced_independently`.
- Open: Zaid confirms pairs 7 and 9 from the sheet; pair 6 stays unconfirmed (leak-safe).
