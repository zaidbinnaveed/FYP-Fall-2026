# FYP-I scope change (23 Nov 2026)

FYP-I evaluation: **6 Dec 2026**. This file records the supervisor's FYP-I requirements as given
to the team and maps each one to a deliverable. It changes the FYP-I/FYP-II split of SRS §2.2; the
SRS/SDS v1.1 errata are E16–E18 in [`traceability.md`](traceability.md). Sign-off:
[`audit/SUPERVISOR_SIGNOFF.md`](audit/SUPERVISOR_SIGNOFF.md) item 11.

## Requirements (verbatim)

> "Classification models 3nu. CNN ViT LLMs. And a working mock UI.
>  1. Complete dataset (tabular and images). 2. Working classification models. 3. UI: Accepted with minor changes.
>  Student must have a clear concept of using tabulated data and computer vision based image classification for their project."

Team decisions on these requirements (23 Nov 2026):

- Images + CNN/ViT: the pipeline is done; the training run happens on the university GPU.
- Tabular dataset + classical classifiers: **approved** (proposed FR-7.11, errata E16).
- LLM: **on hold.** Nothing LLM-related is built for FYP-I (errata E18).
- Mock UI: built with sensible defaults; the supervisor's "minor changes" are applied when received
  (errata E17).

## Mapping to deliverables

| Requirement | Deliverable | Where | Status |
| --- | --- | --- | --- |
| "Classification models … CNN" | ResNet50, EfficientNet-B0, DenseNet121 (one protocol, seed 42) | `ml_research/src/oscc_ml/models/`, `docs/UNI_RUNBOOK.md` | code done; results **pending the university run** |
| "… ViT" | ViT-B/16 under the same protocol | same | code done; results **pending the university run** |
| "… LLMs" | Patient-support chatbot (SRS FR-4.x, FR-6.7, FR-6.8) | — | **on hold** (E18); placeholder screen in the mock UI |
| "Complete dataset (… images)" | Cleaned, deduplicated, leak-free split: 1,179 kept images, 829 / 174 / 176 | `oscc-ml prepare`, `docs/datasheet.md`, ADR-0003/0005 | done (manifest); patches are cut at the university |
| "Complete dataset (tabular …)" | Per-image feature table (colour, H&E stain, texture, nuclei-density proxies) on the same split | `ml_research/src/oscc_ml/tabular/`, `data/processed/tabular/oscc_features_v1.csv`, `docs/results/TABULAR_DATA_DICTIONARY.md` | Phase T |
| "Working classification models" (tabular) | Logistic regression, random forest, gradient boosting; τ from validation, test used once, 95% CIs | `oscc_ml.tabular`, run folders in the image-run format | Phase T |
| "clear concept of using tabulated data and computer vision based image classification" | Viva explainer and a comparison of tabular vs CNN vs ViT from run folders | `docs/TABULAR_VS_CV_EXPLAINER.md`, `docs/results/MODEL_SELECTION.md`, `docs/DATA_DOSSIER.md` | Phase T / 2B |
| "working mock UI" / "UI: Accepted with minor changes" | React + TypeScript mock UI with fixture data and a "Demo mode" banner | `frontend/`, `docs/UI_DEMO.md` | Phase U |

## What does not change

- The SRS/SDS design, the research protocol (SDS Appendix A) and the safety rules (CLAUDE.md §3).
- The CNN-vs-ViT benchmark remains the primary research deliverable; the tabular models are an
  additional, interpretable baseline on the **same** images and split.
- Everything in FYP-II (hospital module, integration, the full chatbot if it resumes) stays there.
