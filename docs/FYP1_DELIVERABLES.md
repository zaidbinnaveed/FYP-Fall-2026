# FYP-I deliverables: evidence and status

Status as of 23 Nov 2026 (Phase 2A PR (C); `main` at `567a935`, Phase 2A PRs #23–#25 open). The
university GPU run has **not** happened yet, so no trained CNN/ViT result exists anywhere in this
repository. Audit details: [`docs/audit/FYP1_COMPLIANCE_AUDIT.md`](audit/FYP1_COMPLIANCE_AUDIT.md).
**Scope change (23 Nov 2026):** the supervisor's FYP-I requirements add a tabular dataset with
classical classifiers and a working mock UI, and put the LLM on hold
([`SCOPE_CHANGE_FYP1.md`](SCOPE_CHANGE_FYP1.md), rows 7–9 below).

## What FYP-I is

- Proposal §4(b) (`docs/proposal.txt:374-379`): "The scope of FYP-I covers problem formulation, dataset
  acquisition and preprocessing, literature review, and the design of the system architecture,
  together with initial implementation and training of baseline CNN and ViT classification models."
- SRS §2.2 (`docs/SRS.md:322`): "FYP-I covers problem formulation, dataset acquisition and
  preprocessing, the literature review, the architecture design and the initial baseline CNN and ViT
  training. FYP-II covers full comparative benchmarking, the hospital module and its database, the
  chatbot, end-to-end integration and system testing."
- SDS (`docs/SDS.md:388`): "FYP-I delivers this design together with the dataset pipeline and the
  baseline CNN and ViT models".
- Plan timeline (`docs/IMPLEMENTATION_PLAN.md:331`): "**FYP-I evaluation:** dataset + baseline CNN
  and ViT results + running skeleton".

Status values: **done** · **done (open PR)** = built and CI-green but not merged ·
**pending uni run** = code ready, needs the GPU run · **on hold** = paused by the supervisor ·
**missing** = not built.

| # | Deliverable | Evidence (files, PRs, commands) | Status |
| --- | --- | --- | --- |
| 1 | Problem formulation | `docs/proposal.pdf` / `proposal.txt`, `docs/SRS.md` §1–2, plan §2 research questions | done |
| 2 | Literature review | Proposal §3 "Related Work" (`docs/proposal.txt:147-345`, refs [1]–[12]). No separate literature-review document in the repo | done in the proposal only; a standalone chapter is **missing** (audit M8) |
| 3 | System architecture design | `docs/SDS.md` + `docs/figures/SDS/` (supervisor-approved); ADR-0001; D0 running skeleton (PR #1: `api/`, `inference/`, `frontend/`, `infrastructure/docker-compose.dev.yml`, CI) | done |
| 4a | Dataset acquisition | Kaggle copy `ml_research/data/raw/kaggle_kebede` (5,192 files, gitignored); export zip `oscc_kaggle_kebede_v1.zip` on Google Drive, SHA-256 `f75d2568…6c0d` (`docs/UNI_RUNBOOK.md`, PR #22). Provenance: all 1,224 originals byte-identical to the Mendeley Data release `ftmp4cvtmb` v2 (this audit, C1) | done |
| 4b | Dataset cleaning (augmented-copy exclusion, dedup, label conflicts, grouped split, leakage test) | `oscc-ml prepare` (PR #11), ADR-0003 hotfix (PR #20). `prepare --manifest-only` on the full data with ADR-0005 (duplicate threshold 4 + reviewed same-field list): 1,179 kept, 829/174/176, leakage test passed; reproduced independently by `scripts/audit/verify_dataset_independent.py` (46/46 checks, 2 identical runs) | done; final `dataset.json` is **pending uni run** (patch pass) |
| 4c | Preprocessing (patch extraction, tissue filter, augmentation) | `oscc_ml.preprocess` (tiling, O5 + ADR-0002), `data/datasets.py` (train-only augmentation, verified in `tests/audit/test_evaluation_hygiene.py`), `docs/results/tissue_filter_check.png` (sample) | done; full patch extraction **pending uni run** |
| 4d | Dataset audit report + datasheet (plan R1 steps 3 and 9) | PR #21 (open): `oscc-ml audit` → `docs/results/dataset_audit.md` (**SAMPLE ONLY**), expanded `docs/datasheet.md` (L1–L5). On `main`: datasheet with L1 only | done (open PR) for code; full-data audit report **pending uni run** |
| 4e | Multi-OSCC external positive set (plan R1 step 6) | Metadata only (`ml_research/data/raw/multi_oscc_github`, PR #21 datasheet). No import code, no `external_positive` split | **deferred to FYP-II** (audit M6, errata E11) |
| 4f | H&E colour-profile validator (plan R1 step 8, FR-2.2) | PR #21 (open): `preprocess/he_check.py`, `he-calibrate`, `he-evaluate`, `docs/results/he_check_sample.md` (SAMPLE ONLY) | done (open PR); test-split false-reject **pending uni run**; ~200 real-photo false-accept set **missing** |
| 5a | Baseline models implemented (ResNet50, EfficientNet-B0, DenseNet121, ViT-B/16) | `oscc_ml.models.factory` (PR #9), identical-protocol test `tests/test_protocol.py` | done |
| 5b | Baseline training (seed 42, all four) | `oscc-ml sweep`, `train-all`, `evaluate`, `report` (PR #9); `uni_run.{ps1,sh}` + `docs/UNI_RUNBOOK.md` (PRs #11, #22) | **pending uni run** |
| 5c | Baseline results table (`docs/results/baseline_fyp1.md`, plan R2 acceptance) | `oscc-ml report --copy-to ../docs/results/baseline_fyp1.md` after `import-results` | **pending uni run** (file does not exist) |
| 6 | Supervisor gate G1 (plan R1 acceptance: "supervisor shown the audit") and deviation sign-off | [`audit/SUPERVISOR_SIGNOFF.md`](audit/SUPERVISOR_SIGNOFF.md): G1 line + 11 deviations with tick boxes | sheet ready; **awaiting the supervisor** (audit B2, M7) |
| 7 | Tabular dataset + classical classifiers (supervisor requirement; proposed FR-7.11) | Phase T (PR #27): `oscc_ml.tabular`; `data/processed/tabular/oscc_features_v1.csv` (gitignored, SHA-256 in `docs/results/TABULAR_RESULTS.md`); [`results/TABULAR_DATA_DICTIONARY.md`](results/TABULAR_DATA_DICTIONARY.md); [`results/TABULAR_RESULTS.md`](results/TABULAR_RESULTS.md); [`TABULAR_VS_CV_EXPLAINER.md`](TABULAR_VS_CV_EXPLAINER.md) | **done (open PR)** |
| 8 | Working mock UI (supervisor requirement; errata E17) | Phase U: `frontend/`, [`UI_DEMO.md`](UI_DEMO.md) (screens, how to run, screenshots) | **done (open PR)**; supervisor's minor changes pending |
| 9 | LLM / patient-support chatbot | — | **on hold** (errata E18) |
| 10 | Model selection framework + FYP-I results package | Phase 2B: `oscc-ml report` → `results/MODEL_SELECTION.md`, `results/FYP1_RESULTS_TEMPLATE.md`, cost/dataset tables, figures; [`DATA_DOSSIER.md`](DATA_DOSSIER.md); README "For evaluators" | **done (open PR)** for the framework and the tabular rows; CNN/ViT rows **pending uni run** |

## How to reproduce what exists today

```bash
cd ml_research
oscc-ml prepare --raw data/raw/kaggle_kebede --manifest-only --out data/processed/<new folder>
python -I scripts/audit/verify_dataset_independent.py --raw data/raw/kaggle_kebede \
    --manifest-dir data/processed/<that folder> --out data/processed/<another folder> \
    --zip data/export/oscc_kaggle_kebede_v1.zip --zip-root kaggle_kebede \
    --expected-zip-sha256 f75d25682388c85469995e16c543ebe4f889cbe8d4c521df37e2bbd1be4a6c0d \
    --mendeley-dir <folder with the saved Mendeley listing JSON>
uv run pytest tests/audit
```

The training results are produced at the university (`docs/UNI_RUNBOOK.md`) and imported with
`oscc-ml import-results results_small.zip` followed by `oscc-ml report`.
