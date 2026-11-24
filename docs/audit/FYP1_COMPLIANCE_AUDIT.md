# FYP-I compliance and data-integrity audit

> **Update (Phase 2A, 22 Nov 2026):** finding M2 was fixed in Phase 2A PR (B): training never opens the test split; `oscc-ml evaluate` predicts it from `best.pt` (test renamed to `test_training_and_the_sweep_never_build_the_test_split`; see also `tests/test_observe.py`). Finding B1 was resolved by
> [ADR-0005](../adr/0005-phash-thresholds-and-reviewed-duplicates.md): duplicate threshold 4, group
> threshold 10, and a reviewed same-field list. The dataset counts in this Phase 1 record are at
> threshold 6. The current counts are in ADR-0005: 1,179 kept, split 829 / 174 / 176, 35 conflict
> exclusions; the verifier passed 46/46 checks.

Phase 1 of the FYP-I audit, run 22 Nov 2026 on branch `audit/fyp1-compliance` (from `main` at
`567a935`). **Read-only:** no code, configuration or data was changed. Only this document,
`docs/FYP1_DELIVERABLES.md`, the independent verifier `ml_research/scripts/audit/verify_dataset_independent.py`
and the tests in `ml_research/tests/audit/` were added.

The university GPU run has **not** happened. Every training or evaluation result is therefore
"not yet run". The data numbers below come from the full dataset, processed on the team laptop
(streamed, one image at a time) with the user's approval for this audit only.

Contents: [1 Summary of findings](#1-findings-ranked) · [2 Scope check](#2-scope-check) ·
[3 Deviation register](#3-deviation-register) · [4 Data integrity](#4-data-integrity-verified-independently) ·
[5 Evaluation hygiene](#5-evaluation-hygiene) · [6 Thresholds](#6-every-threshold-where-it-is-defined-and-whether-it-is-used-consistently) ·
[7 Numbers check](#7-numbers-in-the-docs) · [8 How to reproduce](#8-how-to-reproduce-this-audit)

---

## 1. Findings, ranked

**BLOCKER** = decide or fix before the university run, because fixing it afterwards would mean
re-running training or would make the record post hoc. **MAJOR** = must be fixed or signed off
before the FYP-I evaluation. **MINOR** = documentation accuracy.

No finding affects data integrity: all 45 independent checks passed (section 4).

### BLOCKER

| ID | Finding | Evidence | Proposed fix |
| --- | --- | --- | --- |
| B1 | **The pHash thresholds have not been decided, and both produce questionable groupings.** The duplicate threshold of 6 merges different fields: `dup-00052` links `Normal_400x_188` with `OSCC_100x_256`, two images of different magnifications, at distance 6, and excludes 5 images. `OSCC_100x_153` is removed as a "copy" of `OSCC_100x_108` at distance 6 (ADR-0003 calls both false matches). The group threshold of 10 chains unrelated images: **15 of the 1,066 split groups contain both Normal and OSCC images**, the largest (34 images) mixes both classes and both magnifications. The groups therefore are not patient proxies. They still prevent leakage, because they only make the split more conservative. The plan asks to "tune by visual inspection" (`IMPLEMENTATION_PLAN.md:185`). That has not been recorded. Changing either threshold after the uni run changes the split and invalidates every run. | §4.3, §4.4, §4.6 (what-if numbers), `verify_results.json` → `mixed_label_groups_at_group_threshold` | Team decision **before** the uni run: keep 6/10 (and record why) or change them. Record it in an ADR. Any change → re-run `prepare --manifest-only` + this verifier + update the regression lock (Phase 2A). |
| B2 | **Gate G1 not recorded.** Plan R1 acceptance: "supervisor shown the audit (gate G1)" (`IMPLEMENTATION_PLAN.md:193`); timeline "Gate G1: dataset audit reviewed with supervisor" (17–30 Nov, `:330`). No record exists in the repo. The uni run is R2, which follows R1. | `git grep G1` finds only the plan and a code comment | Show the supervisor this audit and the dry-run counts before the uni run. Record the date and outcome in the datasheet (or report the decision not to). |
| B3 | **The protocol defaults used by the baseline run have no decision record, and one code comment overstates their status.** These values are in no source document and no ADR: <br>• colour jitter 0.1/0.1/0.1/0.02 (`protocol.yaml:30-34`); <br>• 2 warm-up epochs (`:49`); <br>• torchvision `IMAGENET1K_V1` for all CNNs (`factory.py:10`); <br>• 5-epoch sweep trials (`sweep.py:26`); <br>• the sweep rule "highest mean over models of the best validation image-level AUC" (`sweep.py:28`). <br>`factory.py:10` says "confirmed at gate G2", and `protocol.yaml:6` says "confirmed or changed at gate G2". In the plan, gate G2 is **Feb 2027** ("protocol frozen, O1–O5 confirmed", `IMPLEMENTATION_PLAN.md:333`). | §3 items 4, 5, 14 | ADR-0004 "FYP-I baseline protocol defaults" listing each value, its basis and who decided. Reword the two comments to "team default (18 Nov 2026), to be confirmed at gate G2 (Feb 2027)". Comments only, so training behaviour does not change. |

### MAJOR

| ID | Finding | Evidence | Proposed fix |
| --- | --- | --- | --- |
| M1 | **Patient-level split is not met.** The SRS and SDS require "patient-level" splitting: SRS FR-7.2 heading "Patient-level splitting and deduplication" (`SRS.md:695`), NFR-PER-09 "on the patient-level held-out test set" (`:2821`), SDS Appendix A "Patient-level 70:15:15 … no patient appears in more than one split" (`SDS.md:4008`). No patient IDs exist in the Kaggle, GitHub or Mendeley releases (§4.1). The pHash-group split is the documented fallback (plan §3 consequence 2, `IMPLEMENTATION_PLAN.md:75`; datasheet L1). It is not in the SDS v1.1 errata list (`traceability.md:63-74`) and has no supervisor sign-off. Rahman et al. report 230 patients for 1,224 images (datasheet), so several images per patient may sit in different splits. **This is the main threat to validity.** | §3 item 9; B1 | Add errata E7 and get supervisor sign-off. State in the results chapter that test metrics may be optimistic because of possible patient overlap. |
| M2 | **Test data is read before `evaluate`.** At the end of every training run (not sweep runs), `runner._train_and_predict` predicts the test split with the best checkpoint and writes `predictions/test_*.csv` plus test metrics at a fixed, uncalibrated 0.5 in `metrics.json` (`train/runner.py:338-362`). Verified harmless for model selection: the test split is built only **after** `train()` returns, the checkpoint is chosen on validation AUC, and the sweep never builds the test split (`tests/audit/test_evaluation_hygiene.py::test_test_split_is_built_only_after_training_and_never_by_the_sweep`). Two consequences: the requirement "test data is touched only by evaluate" is not literally true, and `metrics.json` holds test numbers at 0.5 that must never be reported (`report` uses `evaluation.json` only, `report/__init__.py:138`). | §5 | Either (a) document it in ADR-0004 and rename the field to `test_uncalibrated_not_for_reporting`, or (b) move test prediction into `evaluate`. Both change pipeline outputs, so they need approval (Phase 2A). |
| M3 | **The train/inference preprocessing parity test does not exist yet.** CLAUDE.md §4 says "A parity test … must stay green". The plan schedules it in D2 (`IMPLEMENTATION_PLAN.md:272`, FYP-II), and the inference service does not use `oscc_ml.preprocess` yet (`inference/pyproject.toml:6`). This audit adds the training-side half: stored patches equal the shared rule applied to the raw image, and dataset tensors equal direct normalization (`test_stored_patches_equal_the_shared_preprocessing_rule`). | §5 | Keep the new test. Write the full parity test in D2 as planned. Add one line to CLAUDE.md saying it starts in D2. |
| M4 | **ViT input statistics and pretraining.** Every model, ViT included, uses ImageNet mean/std (`protocol.yaml:15-16`), as SDS Appendix A requires (`SDS.md:4000`). The `google/vit-base-patch16-224` checkpoint was trained with mean = std = 0.5 (stated only in the open PR #21 datasheet, line 164; **not re-verified in this audit**). The ViT was pretrained on ImageNet-21k and fine-tuned on 1k, while the CNNs use 1k only (`IMPLEMENTATION_PLAN.md:92`, `factory.py:41`). Both confound the CNN-vs-ViT comparison. | §3 items 2–3 | Supervisor sign-off. Add to ADR-0004 and the ViT model card. Optionally, an FYP-II ablation with the checkpoint's own statistics. |
| M5 | **The minority-class augmentation in the SDS risk table is not implemented.** SDS risk table, class imbalance: "Augmentation of the minority class, class-weighted loss, threshold calibration on validation data" (`SDS.md:438`). The pipeline has class-weighted loss (`pos_weight`) and τ calibration, but no minority-specific augmentation or oversampling. | `grep` over `ml_research/src` | Record it as a deviation (class weighting is the chosen mitigation), or implement it after approval. Implementing it changes training. |
| M6 | **The Multi-OSCC external positive set is not built** (plan R1 step 6, "Multi-OSCC → `external_positive` split", `IMPLEMENTATION_PLAN.md:188`). Only the metadata exists (open PR #21). The archive is 34.6 GB and cannot be downloaded on the laptop. | `FYP1_DELIVERABLES.md` row 4e | Not needed for the FYP-I baselines. Record it as deferred to FYP-II (RQ3) in the datasheet and the FYP-I report. |
| M7 | **No supervisor sign-off is recorded for any deviation.** Approvals are by "the team" or "the team lead" only: ADR-0001 line 25, ADR-0002 line 3, ADR-0003 line 3, errata E2–E4. The plan requires the O-decisions to be confirmed "with the supervisor before R3" (`IMPLEMENTATION_PLAN.md:109`). | §3 | One supervisor review covering the deviation register (§3, "sign-off" column). |
| M8 | **There is no standalone literature review.** It exists only as proposal §3 "Related Work" (`proposal.txt:147-345`). Literature review is an FYP-I scope item (proposal §4(b), SRS §2.2). | §2.3 | Team decision: is the proposal's section enough for the FYP-I report, or is a chapter needed? (Writing it is outside Phase 1.) |

### MINOR

| ID | Finding | Evidence | Proposed fix |
| --- | --- | --- | --- |
| m1 | **Stale statements on `main`.** <br>• `datasheet.md:13` "The Mendeley release was not inspected in this check" (it was on 21 Nov; ADR-0003:13 and this audit). <br>• `traceability.md:46` "not yet run on the Kaggle archive" (the dry run ran on 21 Nov; `traceability.md:48`). <br>• `CLAUDE.md:79` "augmented copies removed via pHash" (they are excluded by **name**, `prepare.py:124`) and "duplicate cluster if no patient IDs" (grouping uses similarity at distance **10**, not the duplicate clusters at 6). <br>• `IMPLEMENTATION_PLAN.md:74` "Remove augmented copies (perceptual hash)" (same). <br>• `IMPLEMENTATION_PLAN.md:117` O5 tissue rule (amended by ADR-0002). <br>• `protocol.yaml:63` "threshold calibration is Phase R3" (`evaluate` does it in the FYP-I run). | §7 | One docs PR: update the datasheet line (PR #21 already rewrites it), the traceability row, the CLAUDE.md line and the plan notes. Leave the comment in `protocol.yaml` to the ADR-0004 PR. |
| m2 | **The runbook's "14 pairs" undercounts what the uni log will show.** `UNI_RUNBOOK.md:218` says "The release has 14 such Normal/OSCC pairs". The log reports 18 conflict clusters and 41 images. The 14 byte-identical conflict clusters hold 30 images, because two of them have a third near-duplicate member; the 4 near-duplicate clusters hold 11 (§4.3). | §4.3 | Reword: "18 conflict clusters (14 byte-identical, 4 near-duplicate), 41 images". |
| m3 | **Plan estimates superseded by measured values** (superseded, not errors): <br>• `IMPLEMENTATION_PLAN.md:78` "≈180 images, ≈45 normal" → measured **173** test images, **39** non-OSCC; <br>• `:70` "about 2040×1536 px" → 949 kept images are 2048×1536, 222 are 1536×2048, 1 is 1435×916; <br>• `:70` "≈5,192 images" → exactly 5,192. | §4.3 | Leave the plan as history. Cite the measured values in the datasheet and report. |
| m4 | **Open PR #21 is behind `main`.** Its `UNI_RUNBOOK.md` lacks the Drive route (#22) and says "`archive.zip` (3.15 GB)". That size has no recorded source and matches neither the Kaggle page's 3.19 GB nor the export zip's 3,191,603,059 bytes. Its datasheet omits the 1435×916 image. | §7 | Rebase #21 on `main` before merging. Drop or source the 3.15 GB figure. |
| m5 | **Hand-typed numbers without a saved producing output.** ADR-0002's plain-Otsu numbers (1,003 / 3,240 tiles; 11 / 60 fallbacks) have no saved run. The Multi-OSCC label counts (PR #21 datasheet:109-111) come from an ad-hoc count. All other data counts in the docs are now reproduced by `verify_dataset_independent.py` (§7). | §7 | Re-generate the ADR-0002 numbers with `prepare --max-tissue-threshold 255` on the sample, and add a small script for the Multi-OSCC metadata counts (later phase). |
| m6 | **SDS τ wording is ambiguous.** SDS: "the lowest threshold that reaches the target recall while maximizing F1" (`SDS.md:4010`). The code takes max F1 among thresholds with recall ≥ target, and ties go to the lower threshold (`eval/threshold.py:20-49`). | §3 item 14 | Errata E8 restating the rule as implemented. |
| m7 | **pHash distances are always even.** Each 64-bit pHash has exactly 32 ones: the median split is checked on all 5,192 files. Hence thresholds 6 and 7 behave identically, as do 10 and 11. | §4.3 | One sentence in the datasheet / ADR on the thresholds (B1). |
| m8 | **Kaggle's own split leaks.** 7 byte-identical groups span the publisher's train/val/test folders, 6 of them with opposite labels (§4.3). | §4.3 | Viva point: it partly explains why literature numbers on the Kaggle split are not comparable (plan §3 consequence 7). Add it to the datasheet. |
| m9 | **The same-name check across Mendeley versions is unverified.** The PR #21 datasheet says Mendeley v1 = v2. This audit fetched only the v2 listing. | §4.1 | Mark it "unverified", or fetch the v1 listing (one more metadata GET). |

---

## 2. Scope check

### 2.1 FYP-I scope clauses (verbatim)

- Proposal §4(b), `docs/proposal.txt:374-379`: "The scope of FYP-I covers problem formulation, dataset
  acquisition and preprocessing, literature review, and the design of the system architecture,
  together with initial implementation and training of baseline CNN and ViT classification models."
  FYP-II: "full comparative benchmarking of the classification models, complete development of the
  hospital recommendation module …, development and integration of the patient-support chatbot,
  end-to-end web application integration, and system-level testing."
- SRS §2.2 Phasing, `docs/SRS.md:322`: "FYP-I covers problem formulation, dataset acquisition and
  preprocessing, the literature review, the architecture design and the initial baseline CNN and ViT
  training. FYP-II covers full comparative benchmarking, the hospital module and its database, the
  chatbot, end-to-end integration and system testing."
- SDS, `docs/SDS.md:388`: "FYP-I delivers this design together with the dataset pipeline and the
  baseline CNN and ViT models; FYP-II implements and integrates the remaining modules and tests the
  complete system."
- Proposal individual tasks, Sep–Dec 2026 (`docs/proposal.txt:476-498`):
  - Shahryar: "Dataset acquisition, cleaning, and preprocessing (patch extraction, augmentation)",
    Sep–Oct 2026; "Development of CNN-based classification models (ResNet, EfficientNet, DenseNet)",
    Nov–Dec 2026.
  - Zaid: "Literature review and dataset preparation for the Vision Transformer track", Sep–Oct 2026;
    "Development of the Vision Transformer (ViT) classification model", Nov–Dec 2026.
  - Mudassir: "Design and development of the geolocation-based hospital recommendation module and
    Pakistan oncology-hospital database", Nov 2026 – Jan 2027. This task starts inside FYP-I in the
    proposal's own timetable.
- Plan: R2 is "**FYP-I deliverable**" (`IMPLEMENTATION_PLAN.md:195`); Dec 2026 milestone "**FYP-I
  evaluation:** dataset + baseline CNN and ViT results + running skeleton" (`:331`).

### 2.2 Phases built so far

| PR | Phase | State | What it built | Sanctioning clause |
| --- | --- | --- | --- | --- |
| #1 | D0 foundations | merged 17 Nov | Monorepo, CI, pre-commit; `api/` skeleton (error envelope, request ID, logging, config, `/healthz` `/readyz`, storage adapter with signed URLs, worker heartbeat, CLI); `inference/` and `frontend/` shells; Docker Compose stack; ADR-0001; traceability skeleton | Architecture design: SRS §2.2 "the architecture design". The code skeleton is **outside** the proposal/SRS/SDS FYP-I wording but sanctioned by plan D0 (`IMPLEMENTATION_PLAN.md:249-253`) and the "running skeleton" milestone (`:331`) |
| #2 | R0 environment | merged 17 Nov | `oscc-ml` CLI, `protocol.yaml`, trainer, run folders, CPU smoke training, Colab notebook, pinned installs | Proposal §4(b) "initial implementation and training of baseline CNN and ViT classification models"; plan R0 (`:175-180`) |
| #9 | Phase A (R2 tooling) | merged 18 Nov | Four-model factory, identical-protocol test, `sweep`, `train-all`, `evaluate` (τ, grouped bootstrap CIs, per-magnification metrics, cost), `report`, `pack-results` / `import-results`, `check`, `uni_setup` / `uni_check` | Plan R2 (`:195-217`), SDS `:388` "the baseline CNN and ViT models". τ calibration, bootstrap CIs and cost are listed under **R3** (`:221-225`, Mar 2027), i.e. ahead of schedule (see 2.4) |
| #10 → #11 | Phase B (R1 minimal) | merged 21 Nov (via #11) | Streaming `prepare` (SHA-256 + pHash manifest, dedup, grouped split, leakage test, patches), `make-sample`, `make-test-zip`, `uni_run`, runbook, ADR-0002 | Proposal task "Dataset acquisition, cleaning, and preprocessing (patch extraction, augmentation)"; plan R1 steps 2–5, 7 (`:184-189`) |
| #20 | Hotfix ADR-0003 | merged 21 Nov | Label-conflict exclusion, `prepare --manifest-only`, regression lock | Plan R1 step 4 "Deduplicate"; SDS `:436` "Verify labels in FYP-I before training" |
| #21 | Phase C (R1 completion) | **open** (merge after uni run) | `oscc-ml audit` (sample-only report), H&E colour-profile check (FR-2.2), datasheet L1–L5 | Plan R1 steps 3, 8, 9 (`:185`, `:190`, `:191`) |
| #22 | Runbook Drive route | merged 22 Nov | Google Drive transfer of the dataset zip with SHA-256 / MD5 | Not named in any document; supports running R1/R2 at the university (CLAUDE.md §2 "Long GPU jobs …") |

### 2.3 Outside the FYP-I wording (report, not judgement)

All of these are sanctioned by `IMPLEMENTATION_PLAN.md`, but none appears in the proposal, SRS or
SDS FYP-I clauses:

1. **D0 web skeleton** (`api/`, `inference/`, `frontend/`, `infrastructure/`, CI jobs for them),
   PR #1. Plan D0 (`:249-253`) and timeline "D0, start D1" (`:330`), "running skeleton" (`:331`).
2. **Storage adapter with signed URLs, worker heartbeat, admin CLI** (PR #1). Not in the D0 bullet
   list (`:250-253`); heartbeat and `create-admin` are D1 items (`:261-262`); D1 is timed Nov–Dec
   2026 (`:330-331`).
3. **H&E colour-profile check** (FR-2.2 belongs to the screening module), PR #21. Plan places it in
   R1 (`:190`): "This lives in `preprocess/` so the API's validation uses the same rule."
4. **Evaluation beyond a baseline table**: τ calibration, grouped bootstrap CIs, cost
   (PR #9). Plan lists them under R3 (`:221-225`, Mar 2027). SRS §2.2 puts "full comparative
   benchmarking" in FYP-II. Note: they **report** the baselines; the full benchmark (3 seeds,
   paired tests, ablations) is not built.
5. **Shared LR sweep in the FYP-I run.** Plan timeline "R2 tuning (O1 sweep)" is Jan 2027 (`:332`),
   but the R2 protocol table (`:205`) specifies the sweep, and the proposal's "Training and
   hyperparameter tuning of CNN models" is Jan–Feb 2027 (`proposal.txt:485`).

No hospital-module or chatbot code exists (searched `api/`, `frontend/`).

### 2.4 FYP-I deliverables missing or incomplete

See `docs/FYP1_DELIVERABLES.md` for the full table. In short:
- **pending uni run:** prepared dataset (patch pass), four baseline runs, `docs/results/baseline_fyp1.md`,
  full-data audit report;
- **missing:** Multi-OSCC external set (M6), gate G1 record (B2), standalone literature review
  (M8, team decision), ~200-image real-photo false-accept set for the H&E check (plan `:190`);
- **built but not merged:** PR #21 (audit command, H&E check, datasheet).

---

## 3. Deviation register

"Sign-off" says what the repository records. No supervisor sign-off is recorded for any item (M7).

| # | Clause (source) | What was built | Why (stated rationale) | Evidence | Sign-off recorded? |
| --- | --- | --- | --- | --- | --- |
| 1 | Proposal `proposal.txt:555` "Deep learning frameworks: TensorFlow / Keras and PyTorch"; SRS `:432`, `:476`, `:529` "PyTorch/TensorFlow" | PyTorch only | Plan §4.1 `:93`: "An identical protocol needs one data loader, one augmentation pipeline, one optimizer implementation and one AMP setup; two frameworks would break that." | Plan "Locked decisions"; CLAUDE.md §4 | Team (plan). SRS allows either framework, so this is a narrowing, not a contradiction. Needs supervisor sign-off: **recommended (low risk)** |
| 2 | SDS App. A `:4000` "ImageNet mean and standard deviation"; SRS `:589` | ImageNet mean/std for all four models, ViT included (`protocol.yaml:15-16`; `data/datasets.py`; test `test_protocol.py::test_protocol_matches_sds_appendix_a`) | PR #21 datasheet:164 "kept for protocol fidelity". The checkpoint's 0.5/0.5 statistics are stated there and **not re-verified here** | PR #21 (open) only; no ADR | No. **Needs sign-off** (M4) |
| 3 | SDS `:4002` "ImageNet-pretrained weights for … the ViT"; plan `:92` | HF `google/vit-base-patch16-224`, ImageNet-21k pretrain + 1k fine-tune (`factory.py:35-41`) | Plan `:92`: "a threat to validity to state, not to hide" | Tests `test_models.py::test_vit_uses_eager_attention` | Team (plan). **Needs sign-off** as a stated threat (M4) |
| 4 | SDS `:4002` "ImageNet-pretrained" (no version); plan `:92` "torchvision ImageNet-1k weights" | `IMAGENET1K_V1` for ResNet50, EfficientNet-B0, DenseNet121 (`factory.py:48`, `:55`, `:63`) | `factory.py:10` "classic torchvision V1 recipe (confirmed at gate G2)". Gate G2 is Feb 2027 in the plan (B3) | No ADR; no test pins V1 | No (B3) |
| 5 | SDS `:4001` "mild color jitter"; `:4004` LR "Search range 1e-5 to 1e-3"; plan `:206` "cosine schedule with warm-up (O1)" | Jitter 0.1/0.1/0.1/0.02 (`protocol.yaml:30-34`), `warmup_epochs: 2` (`:49`), placeholder `lr: 1.0e-4` (`:44`), replaced by the sweep result in `train-all` | `protocol.yaml:5-6` "team's working defaults … confirmed or changed at gate G2" | No ADR. `test_protocol_matches_sds_appendix_a` does not assert jitter, warm-up or `lr` | No (B3) |
| 6 | Plan O5 `:117` "drop patches with < 50% tissue (Otsu on saturation)"; SDS `:3999` "224 × 224 pixel patches (tiled or resized)" | Tissue = saturation > min(Otsu, 40) (`protocol.yaml:23`, `preprocess/__init__.py:95`), `PREPROCESS_VERSION pp-0.3.0` | ADR-0002: Otsu finds no glass/tissue split on full-frame tissue; sample: 31% → 82% of tiles kept (sample only) | ADR-0002; `test_preprocess.py::test_threshold_cap_keeps_pale_tissue_on_full_frames`; `docs/results/tissue_filter_check.png` | ADR-0002:3 "Accepted by the team on 18 Nov 2026". No supervisor record |
| 7 | SDS `:4008` "perceptual-hash deduplication across sources"; plan R1 step 4 | Duplicate clusters with both labels: every member excluded (`status = label_conflict`); 18 clusters, 41 images | ADR-0003:5 "Neither the SDS nor the SRS says what to do …"; the true label cannot be known | ADR-0003; `test_prepare.py::test_label_conflicts_are_excluded_not_fatal`; `test_prepare_regression.py`; verified here (§4.3) | ADR-0003:3 "Accepted by the team lead on 21 Nov 2026". No supervisor record |
| 8 | Plan `:74` "Remove augmented copies (perceptual hash)"; CLAUDE.md:79 "removed via pHash" | `aug_*` files excluded **by name** (`prepare.py:124`); pHash dedup at distance 6 among originals; grouping at distance 10 | `prepare.py:121-123`: "pHash alone cannot be trusted to link a 224 px crop to its 2048 px original" | §4.3: 3,968 `aug_` files, all in Kaggle `train/`; 1,016 of them within distance 6 of a kept original | No. Thresholds: see B1 and §6 |
| 9 | SRS FR-7.2 `:695` "Patient-level splitting"; NFR-PER-09 `:2821`; SDS `:4008`, `:439` | Grouped stratified 70:15:15 split over pHash similarity groups (`prepare.py:201`, `split.py`) | Plan §3 consequence 2 `:75`: no patient IDs → "group near-duplicate images (pHash clusters) and split by group; record this as a documented deviation" | Datasheet L1; `test_prepare.py::test_split_is_grouped_stratified_70_15_15`; verified here (§4.4) | No; not in errata (M1) |
| 10 | Plan `:76`, `:188` Multi-OSCC → `external_positive` split; SDS risk `:436` | Not built; metadata only (PR #21) | PR #21 datasheet:114 "the archive is too large for the laptop's connection" (~34.6 GB) | — | No (M6) |
| 11 | SDS `:538` "Private object storage: … S3-compatible bucket" (no product named) | SeaweedFS (`infrastructure/docker-compose.dev.yml:32`) | ADR-0001:40 "MinIO stopped publishing community container images in 2025" | ADR-0001 G-c; errata E4; `api/tests/test_storage.py` | Team (D0 review). The SDS names no product, so this is low risk |
| 12 | SDS `:4016` error envelope; Appendix B lists `GET /api/v1/admin/health` only (`:4069`) | Extra codes `BAD_REQUEST`, `METHOD_NOT_ALLOWED`, `SERVICE_UNAVAILABLE` (`api/app/core/errors.py:32-38`); probes `/healthz`, `/readyz` (`api/app/routers/health.py:21`, `:26`; `inference/inference_service/main.py:38`, `:42`) | ADR-0001:25, :29 | Errata E1–E3 (`traceability.md:69-71`); `api/tests/test_errors.py`, `test_health.py` | ADR-0001:25 "The team approved all three after the D0 review". No supervisor record |
| 13 | SRS/SDS errata | Recorded: E1–E6 (`traceability.md:63-74`); plan §10 gaps 1–8 (`IMPLEMENTATION_PLAN.md:358-369`). Not recorded as errata: ADR-0001 G-e (smoke rules), ADR-0002, ADR-0003, the patient-level deviation (M1), τ wording (m6) | — | — | No |
| 14 | SDS Appendix A, field by field | Matches: 224 input, ImageNet stats, flips/rot90/jitter, AdamW, batch 32, max 50 epochs, patience 7, seed 42, class-weighted loss. Additions not in the SDS: weight decay 0.05 and betas (plan `:205`); AMP (plan `:210`); 5-epoch sweep trials and the mean-over-models selection rule (`sweep.py:26-29`, no document); early stopping on **image-level** validation AUC (plan `:79`); 2,000 bootstrap resamples over `group_id` (plan `:223`); target recall 0.95 and margin 0.05 (plan O2/O3, `protocol.yaml:63-64`) | Plan decisions; O2/O3 accepted as defaults | `test_protocol.py` | O1–O10 "accepted as defaults" by the team; plan `:109` "confirm with the supervisor before R3" |
| 15 | SDS risk table `:438` "Augmentation of the minority class" | Not implemented (M5) | none recorded | `grep` over `ml_research/src` | No |

---

## 4. Data integrity, verified independently

**Method.** `ml_research/scripts/audit/verify_dataset_independent.py` does not import `oscc_ml`,
pandas or `imagehash`; a test enforces this (`test_script_does_not_import_the_pipeline`). It
re-derives every count from the raw files with its own path parser and its own pHash. The pHash uses
a hand-written DCT-II, a byte-table popcount and scipy connected components. The script then
compares the result row by row with prepare's `manifest.csv` / `manifest_only.json`.

Inputs and runs:
- Raw: `ml_research/data/raw/kaggle_kebede` (read-only), 5,192 files.
- Prepare manifest: `prepare --manifest-only` re-run on `main` `567a935` →
  `data/processed/audit-fyp1/prepare-main-567a935/`. Its `manifest.csv` is **row-for-row identical**
  to the 21 Nov dry run (`full-dryrun-manifest`); only `created_at` and `seconds` differ in the JSON.
- **Run 1** and **run 2** of the verifier, about 170 s each, 45/45 checks passed both times. All five
  output files are **byte-identical** between runs; SHA-256 prefixes:
  - `verify_results.json` `3775373d91d03aa3`
  - `kept.csv` `6fe870675fba293d`
  - `label_conflicts.csv` `c73f63c505829111`
  - `duplicates_removed.csv` `260cfc0ef3c424d6`
  - `files.csv` `5ef1631f9940391e`

Three-way check summary (ground rule 2):

| Check | (1) unit tests | (2) independent implementation | (3) re-run identical |
| --- | --- | --- | --- |
| Counts, clusters, conflicts, kept, split | 17 tests in `tests/audit/` (incl. tamper detection) | `verify_dataset_independent.py` vs `prepare`: 45/45 | verifier run 1 = run 2 (byte-identical); prepare re-run = 21 Nov manifest |
| pHash | `test_phash_is_bit_identical_to_imagehash_on_varied_images` | hand-written DCT pHash: the plain hash equals `imagehash` on **all 5,192 files** (manifest `phash` column, 0 mismatches); the 8 dihedral hashes are compared in the unit test, and the identical cluster partitions confirm them indirectly | as above |
| Metrics, τ, bootstrap | `test_metrics_agree_with_scikit_learn`, `test_grouped_bootstrap_matches_an_independent_resampler`, `test_tau_depends_on_validation_only` | scikit-learn; separate resampler | deterministic seeds; checked in the tests |

### 4.1 C1 Provenance (Mendeley Data)

Saved listing (gitignored, `data/processed/audit-fyp1/mendeley/`), retrieved **2026-11-22T09:36:52Z**
from the public API: dataset `ftmp4cvtmb` version 2, DOI `10.17632/ftmp4cvtmb.2`, licence
"CC BY 4.0" (`data_licence.short_name`). Seven metadata GETs in total: the root listing (empty,
`[]`), 1 folder list, 4 folder file lists and 1 dataset record. No images were
downloaded.

| Mendeley folder | Files listed | Folder description says |
| --- | --- | --- |
| 100x Normal Oral Cavity Histopathological Images | 89 | "Contains 89 …" |
| 100x OSCC Histopathological Images | 439 | "Contains 439 …" |
| 400x Normal Oral Cavity Histopathological Images | 201 | "Contains 201 …" |
| 400x OSCC Histopathological Images | 495 | "Contains 495 …" |

Results:
- **1,224 / 1,224** Kaggle originals have their SHA-256 in the Mendeley listing; 0 missing.
- **0** Mendeley files are absent from the Kaggle originals.
- **1,224 / 1,224** match on file name + class folder + SHA-256 + size.
- Magnification agrees with the Mendeley folder for every file.
- Within Mendeley: 16 byte-identical groups, 14 of them with both labels. This matches ADR-0003:13.
- No patient or slide identifier exists in the Mendeley file names or folders (names are
  `<Class>_<mag>_<n>.jpg`).
- Licence for 2B §3c: Mendeley v2 is **CC BY 4.0**, as stated by the API record (the `data_licence`
  field). The PR #21 datasheet says the Kaggle page shows CC0; that was not re-checked here.
  Redistribution with attribution is allowed under CC BY 4.0.

### 4.2 C2 Raw folder untouched

- `raw/kaggle_kebede` holds 5,192 files; `export/oscc_kaggle_kebede_v1.zip` holds 5,192 members
  under `kaggle_kebede/`, with the same paths.
- **5,192 / 5,192** members are byte-identical (SHA-256 and size) to the raw files.
- Zip SHA-256 `f75d25682388c85469995e16c543ebe4f889cbe8d4c521df37e2bbd1be4a6c0d` = the value
  published in `UNI_RUNBOOK.md`; size 3,191,603,059 bytes.

### 4.3 C3 Recount

All counts below were recomputed and **match prepare exactly**: every manifest column per row (0
mismatches in each of 13 columns), the duplicate-cluster partition (1,190 clusters), the group
partition (1,066 groups) and every `manifest_only.json` field.

Files and originals:

| Quantity | Count |
| --- | --- |
| Files / images / unreadable / non-image | 5,192 / 5,192 / 0 / 0 |
| Publisher `aug_` copies (excluded by name) | 3,968: train/Normal 2,204, train/OSCC 1,764; **none** in val/test |
| … of which within pHash distance 6 of a kept original | 1,016 |
| Originals | 1,224: Normal 290, OSCC 934 |
| Originals by class × magnification | Normal 100x 89, Normal 400x 201, OSCC 100x 439, OSCC 400x 495 |
| File-name class disagrees with folder | 0 |

Originals by Kaggle folder:

| Kaggle folder | Normal 100x | Normal 400x | OSCC 100x | OSCC 400x | Total |
| --- | --- | --- | --- | --- | --- |
| train | 71 | 160 | 351 | 396 | 978 |
| val | 8 | 20 | 43 | 49 | 120 |
| test | 10 | 21 | 45 | 50 | 126 |

Duplicates and conflicts (threshold 6):
- **Byte-identical groups among originals: 16** (32 files). **14** carry both labels. The other
  two are same-label: `OSCC_400x_363` = `OSCC_400x_472` and `Normal_100x_7` = `Normal_100x_5`.
- **7** byte-identical groups span the publisher's own train/val/test folders, 6 of them with
  opposite labels (m8).
- **Duplicate clusters: 1,190.** Sizes: 1,161 singletons, 26 of size 2, 2 of size 3, 1 of size 5.
- **Label-conflict clusters: 18** (14 contain a byte-identical opposite-label pair, 4 are pHash
  near-duplicates). They hold **41** excluded images: 30 in the 14 byte-identical clusters, 11 in
  the 4 near-duplicate clusters.
  - Reasons per file (`label_conflicts.csv`): 28 are byte-identical to an opposite-label file.
    11 are within pHash distance ≤ 6 of one: distance 0 for `Normal_100x_69/70/71` ↔
    `OSCC_100x_350/349/348`; 6 and 4 for the third members of `dup-00079` and `dup-00102`; 6 in
    `dup-00052`. 2 are linked only through a same-label chain: `OSCC_100x_64` and `OSCC_400x_489` in
    `dup-00052`, whose nearest opposite-label file is at distance 10 and 8.
- **Same-label duplicates removed: 11** (`duplicates_removed.csv`): 2 byte-identical, 9 at pHash
  distance 0–6. 3 of the 11 sit at exactly distance 6, the threshold (B1).

Kept images:

| Quantity | Value |
| --- | --- |
| Kept | **1,172** = 1,224 − 41 − 11 |
| Kept image sizes | 2048×1536: 949; 1536×2048: 222; 1435×916: 1 (`val/Normal/Normal_400x_196.jpg`) |

**pHash property (m7).** All 5,192 plain pHashes have exactly 32 one-bits, so every distance is even.

### 4.4 C4 Split hygiene

| Check | Result |
| --- | --- |
| SHA-256 in two splits | 0 |
| Duplicate cluster in two splits | 0 |
| Group in two splits | 0 |
| Kept-image pairs across splits at pHash ≤ 10 | 0 |
| Closest cross-split pair | distance **12**: 186 pairs at 12; 1,100 at ≤ 14; 4,768 at ≤ 16 (not visually inspected, so whether any are related fields is **unverified**) |
| Seed-42 split rebuilt twice | identical, and identical to prepare's split for all 1,172 images |
| Groups | 1,066; largest 34 images |
| Mixed-label groups at threshold 10 | **15** (B1) |

| Split | Images | non-OSCC | OSCC | OSCC fraction | Share of kept |
| --- | --- | --- | --- | --- | --- |
| train | 824 | 191 | 633 | 0.7682 | 0.7031 |
| val | 175 | 40 | 135 | 0.7714 | 0.1493 |
| test | 173 | 39 | 134 | 0.7746 | 0.1476 |

Kept by split × class × magnification: train non-OSCC 54 / 137, OSCC 304 / 329; val non-OSCC 14 /
26, OSCC 62 / 73; test non-OSCC 13 / 26, OSCC 60 / 74 (100x / 400x). This equals `summary.csv`.

### 4.5 What-if: other thresholds (for decision B1)

The same verifier, run on the full data with other thresholds. This is read-only: nothing in the
pipeline was changed, and all checks passed in each run. Output folders:
`data/processed/audit-fyp1/whatif-dup4-grp10/` and `whatif-dup6-grp8/`. Distances are even
(m7), so 4, 6, 8 and 10 are the only distinct choices in this range.

| Setting | Conflict clusters (byte-identical + near) / images excluded | Same-label removed | Kept | Split (train / val / test), non-OSCC per split | Groups, largest | Mixed-label groups | Closest cross-split pair |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **current: dup 6, group 10** | 18 (14 + 4) / 41 | 11 | 1,172 | 824 / 175 / 173; 191 / 40 / 39 | 1,066, 34 | 15 | 12 (186 pairs) |
| dup 4, group 10 | 17 (14 + 3) / 35 | 8 | 1,181 | 830 / 175 / 176; 191 / 40 / 40 | 1,056, 37 | 14 | 12 |
| dup 6, group 8 | 18 (14 + 4) / 41 | 11 | 1,172 | 824 / 174 / 174; 192 / 39 / 39 | 1,158, **2** | 6 | **10** (28 pairs at ≤ 10) |

Reading (facts only):
- At duplicate threshold 4, every link at exactly distance 6 disappears:
  - the 5 images of `dup-00052` are no longer excluded;
  - neither is `OSCC_400x_200`, the third member of `dup-00079`, so 6 fewer conflict exclusions;
  - the 3 same-label removals at distance 6 (`OSCC_100x_153`, `OSCC_100x_81`, `OSCC_400x_417`) are kept.
  
  Hence 1,172 + 9 = 1,181 kept.
- At group threshold 8, the 34-image chain disappears (largest group 2). But 28 kept-image pairs at
  distance 10 then cross splits. Whether pairs at distance 8–12 are the same tissue field (true
  near-duplicates) or chance matches is **not verified**. That needs a visual check of a sample of
  pairs, which is the step the plan asks for ("tune by visual inspection", `IMPLEMENTATION_PLAN.md:185`).
- The current setting is the most conservative against leakage (largest groups), at the cost of
  groups that are not patient proxies and the loss of a few distinct images.

---

## 5. Evaluation hygiene

Verified with tests in `ml_research/tests/audit/test_evaluation_hygiene.py`, which call the real
code.

| Requirement | Result | Evidence |
| --- | --- | --- |
| Augmentation on train only | **Pass.** The train split gets `TrainTransform`; val and test get `EvalTransform`, which is deterministic and equals normalization only | `test_eval_transform_is_deterministic_and_train_transform_is_random`, `test_test_split_is_built_only_after_training_and_never_by_the_sweep` |
| LR sweep uses validation only | **Pass.** Sweep runs never build the test split; LR is chosen from `best_val_auc_image` (`sweep.py:90`) | same test (sweep case); existing `test_pipeline.py::test_sweep_writes_the_choice_and_never_reads_test` |
| τ uses validation only | **Pass.** Changing the test predictions leaves τ unchanged; changing validation changes it | `test_tau_depends_on_validation_only`; `evaluate.py:53-54` |
| Test data touched only by `evaluate` | **Not literally true (M2).** The training runner predicts the test split once after training ends, with the val-selected checkpoint; it never influences training, checkpoint choice, LR or τ | `test_test_split_is_built_only_after_training_and_never_by_the_sweep` (test built only after `train()` returns); `runner.py:338-362` |
| `report` rejects smoke/synthetic runs | **Pass** (existing tests) | `test_pipeline.py::test_cli_report_refuses_synthetic_and_noncompliant_runs`, `::test_report_refuses_smoke_only`; `test_uni_run.py::test_all_steps_run_and_the_report_refuses_synthetic_data` |
| Train/inference preprocessing parity | **Training half passes; inference half does not exist yet (M3)** | `test_stored_patches_equal_the_shared_preprocessing_rule` |
| Metrics correct | **Pass.** `point_metrics` and `binary_metrics` equal scikit-learn (20 random cases, 1e-12); the grouped bootstrap CI equals an independent resampler | `test_metrics_agree_with_scikit_learn`, `test_grouped_bootstrap_matches_an_independent_resampler` |

---

## 6. Every threshold, where it is defined, and whether it is used consistently

| Threshold | Value | Defined at | Used at | Consistent? |
| --- | --- | --- | --- | --- |
| pHash duplicate threshold | ≤ 6 (equivalent to ≤ 7, m7) | `prepare.py:118` (`PrepareSettings`), CLI default `cli.py:371`; recorded in `manifest_only.json` / `dataset.json` `settings` | duplicate clusters `prepare.py:282`; label conflicts (same clusters); `aug_` match count `:335`, `:478`, `:554` | Code: yes, one setting. Docs: plan `:185` "≤ 6, tune by visual inspection" (tuning not recorded); ADR-0003 `:9`. **Not in `protocol.yaml`** |
| pHash group threshold | ≤ 10 (equivalent to ≤ 11) | `prepare.py:119`, CLI `cli.py:372`; recorded in `settings` | grouping `prepare.py:201`; leakage near-duplicate check `prepare.py:369` | Code: yes. Docs: **in no source document** (plan, SRS, SDS); CLAUDE.md:79 implies the duplicate cluster instead (m1) |
| Augmented-copy rule | name matches `^aug_` | `prepare.py:124`; `sample.py:43` | exclusion before dedup | Yes; plan / CLAUDE.md say "pHash" (m1) |
| Split fractions | 70:15:15 via 20 folds (14/3/3), tolerance ±0.10 | `split.py:16-21`, `prepare.py:56-57` | `grouped_split`, proportion guard | Yes |
| Tissue threshold | saturation > min(Otsu, **40**); ≥ 50% tissue; ≤ 64 patches; resize if both sides < 448 | `protocol.yaml:19-23`; module defaults `preprocess/__init__.py:93-95` (test `test_module_defaults_match_the_protocol`) | `tile_image` via `protocol_tiling` | Yes in code; plan O5 text is stale (m1) |
| Target recall | 0.95 | `protocol.yaml:63` | `evaluate.py:50` | Yes |
| Inconclusive margin m | 0.05 | `protocol.yaml:64` | `evaluate.py:51` | Yes |
| Uncalibrated threshold | 0.5 | `runner.py:57` | `metrics.json` only (M2) | Yes; not used by `report` |
| Early stopping | patience 7 on image-level val AUC | `protocol.yaml:56` | `trainer.py` | Yes |

---

## 7. Numbers in the docs

Scope: every number in `IMPLEMENTATION_PLAN.md`, the ADRs, `datasheet.md`, `UNI_RUNBOOK.md`,
`traceability.md`, `README.md`, `CLAUDE.md` and the open PR #21 docs. For the SRS, SDS and
proposal, only data and result claims. Most numbers are **design constants or protocol
parameters** copied from the SDS, SRS or plan (ports, token lifetimes, batch 32, …). They are
not data claims and are not listed again here. The SRS, SDS and proposal contain **no** target
accuracy; their only data claims are protocol values and literature figures quoted with citations.

### 7.1 Data and result numbers, with the command that reproduces each

"VERIFIED" = reproduced by `verify_dataset_independent.py` (run 1 = run 2).

| Number | Where | Producing command / source | Status |
| --- | --- | --- | --- |
| 5,192 files | runbook `:9`, `:20`, `:43`; ADR-0003 `:32`, `:36`; PR21 datasheet `:32` | `prepare --manifest-only` → `n_source_images`; verifier `counts.n_files` | VERIFIED |
| 1,224 originals; 290 Normal / 934 OSCC; 89/439 at 100x, 201/495 at 400x | datasheet `:10`; runbook `:30`; ADR-0003 `:32`; plan `:70` | verifier `counts.originals_by_class(_and_magnification)`; Mendeley listing | VERIFIED |
| Per Kaggle folder: 231+2,204 / 747+1,764 (train), 28 / 92 (val), 31 / 95 (test) | runbook `:24-26`; PR21 datasheet `:36-38` | verifier `originals_by_kaggle_folder_class_magnification`, `publisher_augmented_by_folder_and_label` | VERIFIED (previously hand-typed) |
| 3,968 `aug_` copies; 1,016 within distance 6 | ADR-0003 `:37`; PR21 datasheet `:54`, `:61` | `n_publisher_augmented_excluded`, `n_publisher_augmented_matching_an_original` | VERIFIED |
| 11 duplicates removed | ADR-0003 `:38`, `:60` | `n_duplicates_removed` | VERIFIED |
| 18 conflict clusters (14 + 4), 41 images | ADR-0003 `:39-40`; traceability `:48`; runbook `:10` | `n_label_conflict_clusters`, `n_label_conflict_images_excluded` | VERIFIED |
| "14 such Normal/OSCC pairs" | runbook `:218` | Mendeley listing | true for byte-identical pairs, but **misleading as the expected log count** (m2) |
| 16 byte-identical groups / 14 with both labels / 28 files | ADR-0003 `:13` | verifier `n_byte_identical_groups_*`; Mendeley listing | VERIFIED (28 = files in the 14 cross-label groups; 32 in all 16) |
| 1,172 kept; 824 / 175 / 173; 191/633, 40/135, 39/134; 70.3 / 14.9 / 14.8% | ADR-0003 `:41-44`; runbook `:10`; PR21 datasheet `:61-69` | `n_kept_images`, `counts`; verifier `class_ratio_per_split` | VERIFIED (percentages derived from the counts) |
| 1,066 groups, largest 34 | ADR-0003 `:42`; PR21 datasheet | `n_groups`, `largest_group` | VERIFIED |
| ~23% non-OSCC | PR21 datasheet `:77`, `:155` | 270 / 1,172 = 23.0% | VERIFIED (derived) |
| Image sizes: "mostly 2048×1536 (some portrait 1536×2048, one 1435×916)" | runbook `:29` | verifier `kept_dimensions` | VERIFIED; PR21 datasheet `:55` omits the 1435×916 (m4) |
| Zip 3,191,603,059 bytes; SHA-256 `f75d2568…6c0d` | runbook `:7-8`, `:72` | verifier `zip.zip_sha256`, `zip_size_bytes` | VERIFIED (MD5 not re-computed here) |
| "3.15 GB" archive.zip | PR21 runbook `:7` | none recorded | **unsourced** (m4) |
| 230 patients | datasheet `:11`, `:15`; plan `:70` | quoted from the Rahman GitHub README (datasheet `:9`) | quoted, not verifiable from the files (no patient IDs) |
| ≈180 test images, ≈45 normal | plan `:78` | hand estimate | **superseded** by 173 / 39 (m3) |
| "about 2040×1536 px", "≈5,192" | plan `:70` | pre-download facts | **superseded** (m3) |
| Multi-OSCC: 1,325 patients; TD 450/692/183; 925/200/200; 34,597,662,319 bytes | plan `:69`; PR21 datasheet `:108-113` | metadata files, ad-hoc count; Zenodo API | not reproduced here (m5); layout "has not been checked" (PR21 datasheet) |
| ADR-0002 sample: 1,003 / 3,240 = 31%; 2,641 / 3,240 = 82%; 11/60 → 0/60 | ADR-0002 `:19-20` | `prepare` on the 60-image sample; plain-Otsu run not saved | labelled sample-only; 82% reproduced by PR21 `dataset_audit.md` (81.5%); **31% / 11-of-60 have no saved output** (m5) |
| PR21 `dataset_audit.md`, `he_check_sample.md` | PR21 | `oscc-ml audit`, `oscc-ml he-evaluate` | labelled **SAMPLE ONLY** at the top: correct |
| Proposal literature figures (e.g. 97.05%, 98.97%, 99.36%) | proposal `:197-262` | cited papers [4]–[8] | literature, cited; not re-verified |

### 7.2 Contradictions and staleness

All are listed in §1 as m1–m4 and m6. None changes a pipeline output.

---

## 8. How to reproduce this audit

```bash
cd ml_research
# 1. prepare's own dry run on the current code (read-only on raw)
oscc-ml prepare --raw data/raw/kaggle_kebede --manifest-only --out data/processed/audit-fyp1/prepare-main-567a935
# 2. Mendeley listing (metadata only): GET https://data.mendeley.com/public-api/datasets/ftmp4cvtmb/folders/2,
#    then .../files?folder_id=<id>&version=2 for each of the 4 leaf folders; save as folders_v2.json and files_<id>.json
# 3. independent verification (run it twice and compare the outputs byte for byte)
python -I scripts/audit/verify_dataset_independent.py --raw data/raw/kaggle_kebede \
  --manifest-dir data/processed/audit-fyp1/prepare-main-567a935 \
  --zip data/export/oscc_kaggle_kebede_v1.zip --zip-root kaggle_kebede \
  --expected-zip-sha256 f75d25682388c85469995e16c543ebe4f889cbe8d4c521df37e2bbd1be4a6c0d \
  --mendeley-dir data/processed/audit-fyp1/mendeley --out data/processed/audit-fyp1/verify-run1
# 4. tests (CI runs them too)
uv run pytest tests/audit
```

All outputs go to gitignored `ml_research/data/processed/audit-fyp1/` (about 3 MB). The raw folder
is never written to.
