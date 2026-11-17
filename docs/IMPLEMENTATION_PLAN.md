# OSCC Health Intelligence — Implementation Plan (v1.0)

Hand-off plan for Claude Code. Derived from the FYP Proposal (12 Sep 2026), SRS v1.0 and SDS v1.0, all accepted by the supervisor. Prepared 17 Nov 2026.

Team: Muhammad Mudassir Bhatti (lead; hospital module, integration), Shahryar (dataset, CNN track, comparative analysis), Zaid (ViT track, chatbot). Supervisor: Miss Rubab Manzar. Co-supervisor: Miss Alina Arshad.

---

## 0. How to use this plan

1. Put the three source documents in `docs/` as Markdown or PDF so Claude Code can read them (`docs/proposal.pdf`, `docs/SRS.md`, `docs/SDS.md`). Put this file at `docs/IMPLEMENTATION_PLAN.md` and the companion `CLAUDE.md` at the repository root.
2. **Precedence when sources disagree:** SDS (final design decisions) > SRS (requirements) > Proposal (intent and research questions). This plan does not override them. Where it fills a gap, it says so and lists the gap in §10 so the documents can be updated.
3. Work **one phase at a time**. Each phase ends with an acceptance checklist; a phase is finished only when its checks pass in CI.
4. Claude Code writes and tests the code. GPU training runs on the lab machine or a cloud notebook through the same CLI. **No metric, table or figure is ever typed by hand or invented.** Every number in a report is produced by a script from a saved run directory.
5. Keep `docs/traceability.md` current: every FR / NFR / UC → code path → test name. This extends SRS Appendix A down to code.

---

## 1. The project in two tracks

This is an R&D project, so there are two deliverables that must both stand on their own:

| Track | Output | Judged by |
| --- | --- | --- |
| **R — Research** | A reproducible CNN-vs-ViT benchmark on OSCC histopathology that answers the research questions in §2, with confidence intervals, statistical tests, cost analysis and interpretation. | Results chapter, model cards, dataset datasheet, reproducibility of every number. |
| **D — Development** | The OSCC Health Intelligence web system (SRS FR-1 to FR-6, NFRs). | Working demo of all use cases, test reports, NFR measurements, usability study. |

The tracks meet at the **model registry**:

```
ml_research (offline)                          web system (online)
  dataset → train 4 models → evaluate    ──►   POST /admin/models (register)
  → export weights + metrics JSON              → /validate (smoke test) → /activate
                                               → inference service serves primary model
                                               → compare mode shows all 4 side by side
```

The D track never waits for the R track: the inference service is built against a fixed contract and tested with a dummy model (§7, D2) until real weights exist.

---

## 2. Research questions

The proposal's problem statement asks whether ViT models offer a meaningful advantage over CNN models for OSCC histopathology under one protocol, and whether the extra computational cost is justified. The SRS research objectives add confidence intervals, cost metrics and interpretation, and the SRS constraints require bias across datasets to be analysed and reported. That gives four research questions:

| RQ | Question | Where it comes from | Evidence | Analysis |
| --- | --- | --- | --- | --- |
| **RQ1 Performance** | Under an identical protocol, does a ViT (ViT-B/16) classify OSCC vs non-OSCC better than ResNet50, EfficientNet-B0 and DenseNet121? | Proposal §2, Objective 2; SRS §2.4 research objectives 1–2; NFR-PER-09 | Test-set accuracy, precision, recall, F1, AUC-ROC, confusion matrix, each with 95% bootstrap CI | Paired bootstrap of ΔAUC (ViT − each CNN) with 95% CI; McNemar test on decisions at τ; Holm correction over the 3 comparisons |
| **RQ2 Cost** | Is any performance difference worth the computational cost? | Proposal §2 and Expected Result (i); SRS research objective 3; FR-7.8 | Parameter count, GFLOPs, mean latency (CPU and GPU), peak memory, training time | Accuracy–cost Pareto plot; AUC vs GFLOPs and vs latency |
| **RQ3 Generalization** | How do the models behave on images from a different source or staining? | SRS §2.7 (bias across datasets analysed and reported); SDS risk "cross-dataset stain and scanner shift" | Per-source and per-magnification metrics; recall on the external OSCC set; stain-normalization ablation | In-source vs out-of-source recall; with vs without stain normalization |
| **RQ4 Interpretability** | Do the explanation maps focus on diagnostically relevant tissue? | SRS research objective 4; FR-7.9 | Grad-CAM (CNNs) and attention-rollout (ViT) panels for TP / FP / FN cases | Qualitative panel review; optional deletion-curve metric |

**Hypothesis wording for RQ1** (state it this way in the report): H0 — the test AUC of ViT-B/16 equals the test AUC of the best CNN. Report the effect size (ΔAUC) with its 95% CI, not only a p-value. A non-significant difference means "no evidence of a difference at this sample size", not "equivalent". The SDS already commits to reporting the comparison "whichever family wins".

**D-track evaluation questions** (Objective 5, "evaluate the system's overall usability and reliability"):

- **E1 NFR compliance** — performance, safety and security NFRs measured by automated tests (§9).
- **E2 Usability** — System Usability Scale (SUS) questionnaire plus task-completion rate for the golden flow (register → upload → result → hospitals → support), with at least 8 participants.
- **E3 Chatbot safety** — pass rate of a labelled guardrail test suite, reported per category (distress, dosage, diagnosis, stop-medication, out-of-scope, precaution, Roman Urdu).
- **E4 Recommendation correctness** — haversine distances against reference values; correct radius expansion and fallback behaviour.
- **E5 Input validation** — false-reject rate of the H&E check on the test set and false-accept rate on a set of non-histology images.

---

## 3. Dataset reality check (read before any training)

Facts checked on 17 Nov 2026; Phase R1 must re-verify them on the downloaded files.

- **[10]/[11] Multi-OSCC (Zenodo / GitHub):** 1,325 patients, **all OSCC**. Six images per patient at ×200, ×400 and ×1000 covering tumour core and edge. Its labels are tasks *within* OSCC (recurrence, metastasis, differentiation and others). **It contains no normal tissue**, so the SDS's top risk ("Zenodo may contain only OSCC samples") has materialised.
- **[12] Kebede (Kaggle):** a repackaging of the Rahman et al. (2020, *Data in Brief*) histopathology database: 1,224 original images from 230 patients, normal vs OSCC, at 100× (89 normal / 439 OSCC) and 400× (201 normal / 495 OSCC), about 2040×1536 px. The Kaggle **training folder contains augmented copies** (≈5,192 images in total); its validation and test folders are small and not augmented.

**Binding consequences for the R track:**

1. **Primary benchmark dataset = [12], rebuilt from the original images.** Remove augmented copies (perceptual hash), then re-split from scratch 70:15:15 with seed 42. Both classes come from one source, so the model cannot learn "source = label". If the original Rahman release is used to recover provenance, record it in the datasheet as the origin of [12].
2. **Patient-level split:** check whether the release carries patient identifiers. If it does, split by patient (SRS requirement). If not, group near-duplicate images (pHash clusters) and split by group; record this as a documented deviation and limitation in the datasheet.
3. **Multi-OSCC is an external, positive-only test set** for RQ3: report recall at τ on unseen-source OSCC, per magnification (×400 is the closest match to [12]). **Do not mix Multi-OSCC positives into training in the primary benchmark** — every extra positive would come from a different lab and scanner, which invites a shortcut. Mixed-source training is allowed only as an ablation, together with a source-shortcut check (a small classifier that predicts the source; if it succeeds easily, the confound is real and must be reported).
4. **Class imbalance** (about 1 normal : 3 OSCC) → class-weighted loss and recall-oriented threshold, as the SDS already specifies.
5. **Small test set** (≈180 images, ≈45 normal after re-splitting) → wide confidence intervals. Report CIs prominently, train each model with 3 seeds (42, 43, 44; the split seed stays 42), and if compute allows add a supplementary 5-fold grouped cross-validation of the comparison.
6. **Weak patch labels:** every patch inherits its image label, so stroma patches in an OSCC image are labelled OSCC. Image-level evaluation (mean of patch probabilities, as in inference) is therefore the primary unit; patch-level metrics are secondary. State this limitation.
7. **Expect lower numbers than published papers.** Published results on this dataset differ in how their splits were built. A leak-free re-split may score below the 97–99% figures in the literature — that is a legitimate finding to report, not a failure.
8. **Optional, needs supervisor approval** (the SRS limits sources to [10]–[12]): an additional public external test set with both classes would make RQ3 much stronger. A candidate is the Mendeley OSCC/normal dataset published in Feb 2026 (115 cases, 100× and 400×). Decide in §4 (decision O9).

---

## 4. Decisions

### 4.1 Locked decisions (from the documents, or forced by them)

| Area | Decision | Basis |
| --- | --- | --- |
| Models | **ResNet50**, **EfficientNet-B0**, **DenseNet121**, **ViT-B/16** | Proposal/SRS families; exact variants are the ones named in the SDS data dictionary (`model_versions.architecture`). EfficientNet-B0 also matches [4]; DenseNet121 and ResNet50 match [5]. |
| Pretrained weights | CNNs: torchvision ImageNet-1k weights. ViT: HuggingFace `google/vit-base-patch16-224`. | SDS Appendix A (ImageNet-pretrained); Proposal §8 (ViT via HuggingFace Transformers). Note in the report that this ViT checkpoint was pretrained on ImageNet-21k before ImageNet-1k fine-tuning — a threat to validity to state, not to hide. |
| DL framework | **PyTorch only** for all four models | Proposal/SRS allow "PyTorch/TensorFlow". An identical protocol needs one data loader, one augmentation pipeline, one optimizer implementation and one AMP setup; two frameworks would break that. |
| Task | Binary: `oscc` vs `non_oscc`; single logit, `BCEWithLogitsLoss` with `pos_weight` from training class ratio | SRS "OSCC grading and any multi-class classification" out of scope; SDS class-weighted loss |
| Protocol | Exactly SDS Appendix A (reproduced in §6, R2) | SDS |
| Back end | Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 | SDS technology decisions (SQLAlchemy repositories) |
| Database | PostgreSQL 16 + pgvector; embeddings 768-dimensional | SDS |
| Object storage | S3-compatible API everywhere (boto3 presigned URLs, ≤ 10 min). Dev: an S3-compatible container on a Docker volume. Cloud: an S3-compatible bucket. | SDS (Docker volume in development, S3-compatible in cloud); NFR-SEC-06. One code path for signed URLs. |
| Inference service | Separate FastAPI container; `POST /internal/infer`, `POST /internal/models/load`; stateless; no DB access | SDS |
| Worker | Separate process sharing the API's services and repositories; DB polling with `FOR UPDATE SKIP LOCKED` | SDS |
| Front end | React + TypeScript (Vite), React Router, TanStack Query; charts with Recharts | SDS (React SPA); tooling choice is ours |
| Auth | JWT access 15 min + refresh 7 days in httpOnly secure cookies, refresh rotation, Argon2id, lockout 5 attempts / 15 min | SRS FR-1.3, NFR-SEC-01/03/05 |
| Mapping | Google Maps Platform primary; Nominatim + OSRM fallback; haversine-only final fallback | SDS (respect Nominatim's usage policy: identifying User-Agent, ≤ 1 request/s, cache geocodes) |
| Email | SMTP adapter; Mailpit container in development | SRS |
| Real-time | Server-Sent Events (`sse-starlette`), polling fallback | SRS communications interfaces |
| Deployment | Docker Compose: `web` (Nginx serving the SPA), `api`, `inference`, `worker`, `db`, storage; Nginx TLS reverse proxy; one VM | SDS |
| Seeds | 42 for splitting, initialization and data loading | SDS Appendix A |

### 4.2 Open decisions (recommended defaults — confirm with the supervisor before R3)

| ID | Decision | Recommended default | Why it matters |
| --- | --- | --- | --- |
| O1 | **Learning-rate policy.** SDS: search 1e-5–1e-3 on validation, "the chosen schedule is applied to every model". ViTs often prefer lower learning rates than CNNs. | Primary run exactly as the SDS says (one shared LR from a short sweep). Secondary analysis: each model gets its own best LR with the **same tuning budget**. Report both. | A single LR could favour one family; the secondary analysis shows whether the RQ1 conclusion survives fair tuning. |
| O2 | Target recall for τ | 0.95 | SDS/NFR-SAF-03 say "target recall" without a number. |
| O3 | Inconclusive margin m | 0.05; report sensitivity at 0.03 and 0.10 | SRS/SDS give no value. |
| O4 | Stain normalization (Macenko via `torchstain`) | Decide from the R3 ablation: adopt only if it improves external recall without lowering in-source AUC beyond its CI | SDS says "optional, applied identically if adopted". |
| O5 | Tiling rule | If both sides < 448 px: resize to 224. Otherwise: non-overlapping 224×224 grid; drop patches with < 50% tissue (Otsu on saturation); if > 64 patches remain, take 64 evenly spaced. Identical in training and inference. | Mean aggregation over background patches would dilute the probability; a cap keeps NFR-PER-01 latency. |
| O6 | RAG similarity threshold | Cosine ≥ 0.50, tuned on 40 labelled questions | UC-CHT-02 alternate 3a needs a number. |
| O7 | LLM provider | Any provider behind the adapter that offers chat completion and a moderation capability (SDS assumption). Choose by free/academic tier. | Cost and moderation support. |
| O8 | Embedding model (768-d) | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`, run locally in the API | 768-d matches `knowledge_articles.embedding`; multilingual helps the "Urdu / Roman Urdu best effort" scope; no external call, so no PII leaves the server. |
| O9 | Extra external test set with both classes | Ask the supervisor; add only if approved and update SRS §2.7 | Strengthens RQ3. |
| O10 | Model selection rule | Keep the SDS rule (highest test AUC, recall tie-break) and state in the report that the deployed model's test score is therefore slightly optimistic. | Selecting on the test set is standard for a deployment choice but should be acknowledged. |

---

## 5. Repository layout (mirrors the SDS package diagram)

```
oscc-health-intelligence/
├── CLAUDE.md
├── docs/                      # proposal, SRS, SDS, this plan, traceability.md, adr/,
│                              # datasheet.md, model_cards/, results/ (generated)
├── ml_research/               # offline research track (FR-7.x)
│   ├── pyproject.toml         # package `oscc_ml`; extra [preprocess] for the inference image
│   ├── configs/               # protocol.yaml (shared), resnet50.yaml, efficientnet_b0.yaml, ...
│   ├── src/oscc_ml/
│   │   ├── data/              # download helpers, manifest, dedup, split, patching, datasets
│   │   ├── preprocess/        # THE single preprocessing module (tiling, tissue filter,
│   │   │                      # normalization, optional stain norm) — imported by inference
│   │   ├── models/            # factory: name → nn.Module with 1-logit head
│   │   ├── train/             # trainer, early stopping, AMP, checkpointing, LR sweep
│   │   ├── eval/              # metrics, bootstrap CIs, paired tests, threshold calibration
│   │   ├── cost/              # params, FLOPs, latency, memory
│   │   ├── explain/           # Grad-CAM, attention rollout, stitching to full image
│   │   └── export/            # weights export + registry payload JSON
│   ├── scripts/               # CLI entry points (oscc-ml data|train|eval|report|export)
│   ├── notebooks/             # Colab/Kaggle runners that only call the CLI
│   ├── data/                  # gitignored: raw/, interim/, processed/, manifests/
│   └── runs/                  # gitignored except summaries: one folder per run
├── inference/                 # FastAPI internal service
├── api/
│   └── app/
│       ├── core/              # config, security, errors (envelope), logging, request IDs
│       ├── db/                # ORM models (20 tables), session, Alembic migrations
│       ├── schemas/           # Pydantic DTOs
│       ├── routers/           # one router per area: auth, users, screenings, links,
│       │                      # recommendations, hospitals, chat, plans, reminders,
│       │                      # adherence, notifications, admin/*
│       ├── services/          # use-case logic
│       ├── guardrails/        # PII scrub, safety screen, intent, output check
│       ├── repositories/      # the only code that touches SQL
│       ├── adapters/          # llm, mapping, email, storage, inference_client, embedder
│       ├── worker/            # scheduler loop and jobs
│       └── cli.py             # create-admin, seed-helplines, import-hospitals, seed-kb
├── frontend/                  # React SPA
└── infrastructure/            # docker-compose*.yml, nginx/, .env.example, backup/, k6 or locust/
```

Dependency direction is the SDS one: `frontend → api → inference → ml_research (preprocess + weights)`. No cycles. `api` never imports `torch`.

---

## 6. R track — research phases

### R0. Environment (Week of 17 Nov) — Shahryar, Zaid
- `ml_research` package with pinned dependencies: torch, torchvision, transformers, timm (optional), albumentations, scikit-learn, pandas, imagehash, grad-cam (`pytorch-grad-cam`), torchstain, matplotlib.
- One CLI that runs identically on a laptop (CPU smoke test), the lab GPU and Colab/Kaggle notebooks.
- Every run writes `runs/<timestamp>_<model>_<seed>/` containing: resolved config, git commit, dataset_version, environment info, train log CSV, best checkpoint, validation predictions, test predictions (per patch and per image), metrics JSON.

**Acceptance:** `oscc-ml train --model resnet50 --smoke` finishes on CPU in under 5 minutes on 32 synthetic images, and CI runs it.

### R1. Dataset audit, unification and splitting (FR-7.1–7.3) — Shahryar (lead), Zaid
1. Download [12] (Kaggle API token on the team's machine — Claude Code cannot do this step) and [10]/[11] (Zenodo/GitHub, using their split files for reference).
2. Build `manifests/all_images.csv`: `image_id, source, original_path, label, patient_or_group_id, magnification, width, height, sha256, phash, is_augmented_copy, split`.
3. **Audit report** (`docs/results/dataset_audit.md`, generated): counts per source × label × magnification; image sizes; duplicate clusters (pHash Hamming ≤ 6, tune by visual inspection of a sample); whether patient IDs exist; examples of each class.
4. Deduplicate; drop Kaggle augmented copies; assign group IDs.
5. Split [12] 70:15:15 by patient (or by group, see §3), stratified by label, seed 42 (`StratifiedGroupKFold`-based). Assert no group appears in two splits.
6. Multi-OSCC → `external_positive` split (never used for training or threshold selection).
7. Patch extraction with the shared `oscc_ml.preprocess` module (decision O5). Store patches with their parent `image_id`.
8. **H&E colour-profile validator** for FR-2.2: compute HSV/stain statistics on training images; derive accept ranges; measure false-reject on the test split and false-accept on ~200 non-histology images (photos, screenshots). This lives in `preprocess/` so the API's validation uses the same rule.
9. Write `docs/datasheet.md` (SRS user documentation item): sources, licences, citations, composition, split method, deduplication, known limitations. Tag the release `dataset_version = oscc-unified-v1`.

**Acceptance:** audit report generated from code; leakage test passes (no shared sha256/pHash cluster/patient across splits); datasheet complete; supervisor shown the audit (gate G1).

### R2. Training harness and baselines (FR-7.4–7.6) — Shahryar (CNNs), Zaid (ViT). **FYP-I deliverable.**

Shared protocol (`configs/protocol.yaml`, SDS Appendix A — every model reads the same file; model files may only set the architecture name):

| Setting | Value |
| --- | --- |
| Input | 224×224 patches (O5 tiling rule) |
| Normalization | ImageNet mean/std; stain normalization only if O4 says so, identically everywhere |
| Augmentation (train only) | Horizontal/vertical flips, 90° rotations, mild colour jitter |
| Initialization | ImageNet-pretrained (§4.1) |
| Optimizer | AdamW, identical settings (weight decay 0.05, betas default) |
| LR | Sweep {1e-5, 3e-5, 1e-4, 3e-4, 1e-3}, short runs, pick by validation AUC; cosine schedule with warm-up (O1) |
| Batch size | 32 (reduce uniformly for all models if memory requires; record it) |
| Epochs | Max 50; early stopping on validation AUC, patience 7; keep best checkpoint |
| Loss | BCEWithLogits with `pos_weight` |
| Precision | Mixed precision (AMP) for all models |
| Seed | 42 (plus 43 and 44 for the seed-variance runs) |

- Model factory: replace each classifier with `Linear(in_features, 1)`. For the HuggingFace ViT use `attn_implementation="eager"` so attention weights are available for rollout.
- Enforce the protocol in code: a test loads all four configs and asserts every non-architecture field is identical (FR-7.6).
- Produce baseline results for all four models with seed 42 — this is the FYP-I milestone.

**Acceptance:** four completed runs with validation curves; identical-protocol test green; a generated baseline table (`docs/results/baseline_fyp1.md`).

### R3. Full benchmark and statistical analysis (FR-7.7, 7.8; NFR-PER-09) — Shahryar (lead), Zaid
1. Final training: 4 models × 3 seeds under the primary protocol; then the O1 secondary (per-model LR, equal budget).
2. Threshold calibration on validation: among thresholds with validation recall ≥ target (O2), choose the one with maximum F1 (ties → lower threshold). Store τ and m with the run.
3. Test evaluation at **image level** (mean of patch probabilities, exactly as inference does) — primary; patch level — secondary.
4. Metrics with 95% bootstrap CIs (2,000 resamples, resampling patients/groups, not images). ROC and PR curves, confusion matrices.
5. Paired comparisons: paired bootstrap of ΔAUC (ViT − each CNN) with CI; McNemar at τ; Holm correction. Report mean ± SD over seeds.
6. Cost (FR-7.8): parameter count; GFLOPs per 224×224 patch with `torch.utils.flop_counter.FlopCounterMode` for all models (state the counting convention); latency at batch 1 on CPU and GPU (50 warm-up, 200 timed runs, report mean and p95); peak GPU memory; wall-clock training time.
7. Generalization (RQ3): per-magnification metrics; recall at τ on `external_positive`; stain-normalization on/off ablation for all four models.
8. Optional robustness: 5-fold grouped cross-validation of the comparison if compute allows.

**Acceptance:** `oscc-ml report` regenerates every table and figure in `docs/results/benchmark/` from run folders alone; each RQ1–RQ3 has a written answer that cites table/figure IDs.

### R4. Interpretation (FR-7.9) — Zaid (ViT), Shahryar (CNNs)
- Grad-CAM on the last convolutional block for each CNN; attention rollout for the ViT; per-patch maps stitched back into a full-image overlay (the same code the inference service uses).
- Panels: for each model, 4 true positives, 4 false positives, 4 false negatives, same images across models.
- Optional quantitative check: deletion curve (remove most-salient patches, track probability drop).

**Acceptance:** panel figures generated; written observations for RQ4.

### R5. Export, registration and write-up (FR-7.10) — all
- Export each final model (state dict + architecture name + preprocessing version) and a `registry_payload.json` matching `POST /api/v1/admin/models` and the `metrics` body of `/validate`.
- A **model card** per model (`docs/model_cards/<version_tag>.md`): intended use (non-diagnostic screening aid), data, metrics with CIs, threshold, limitations.
- Results chapter draft: methods (protocol table), results (RQ1–RQ4), threats to validity (single-source training, weak labels, small test set, pretraining asymmetry, test-based model selection), conclusion.

---

## 7. D track — development phases

Every endpoint, table, enum value, status name and error code must match SDS Appendix B and the data dictionary exactly. Each use case's alternate scenarios become tests.

### D0. Foundations — Mudassir (lead), all
- Monorepo, pre-commit (ruff, black or ruff-format, eslint, prettier), GitHub Actions CI (lint, type check, unit and integration tests, frontend build), `.env.example` with every variable, no secrets in code (NFR-SEC-09).
- Docker Compose for development: db (pgvector image), storage, mailpit, api, worker, inference (CPU), frontend dev server.
- Core cross-cutting code: error envelope `{error_code, message, details, request_id}`; request-ID middleware; structured JSON logging; config from environment; UTC timestamps, ISO 8601.
- `docs/traceability.md` skeleton.

**Acceptance:** `docker compose up` brings every service to healthy; CI green on an empty feature set.

### D1. Data layer, accounts and administration of users (FR-1.x, FR-6.1, FR-6.9; UC-USR-01..03, UC-ADM-01, UC-ADM-05) — Mudassir
- Alembic migration `0001` creates **all 20 tables** from the data dictionary, with CHECK constraints for every enum, the pgvector extension, and indexes: `screenings(requested_by, created_at)`, `medication_reminders(status, scheduled_at)`, `hospitals(verification_status, latitude, longitude)`, `chat_messages(session_id, created_at)`, `audit_logs(created_at)`, an HNSW or IVFFlat index on `knowledge_articles.embedding`. Apply the §10 errata columns in `0002`.
- Registration, email verification (24 h token), login with lockout, refresh rotation, logout, password reset (30 min token, generic response), profile, account deletion with password confirmation (SD12).
- RBAC dependency per role; professional `pending_approval` cannot screen.
- Admin: user list/filter, approve, deactivate (no self-deactivation), reactivate; audit log search; health endpoint probing db, inference, worker heartbeat, storage, LLM, mapping, SMTP.
- `cli.py create-admin` (administrators are not self-registered).

**Acceptance:** API tests for every SD1, SD2, SD11 and SD12 message and branch; lockout, token expiry and refresh-rotation tests; OpenAPI docs render.

### D2. Inference service and screening (FR-2.x, FR-6.5, FR-6.6; UC-SCR-01..05, UC-ADM-03) — Mudassir (API), Zaid (inference)
- **Inference service** depends on `oscc_ml[preprocess]` and the model factory. `POST /internal/models/load` loads weights from a signed URL and runs a smoke test on a bundled sample. `POST /internal/infer` downloads the image via signed URL, tiles (O5), normalizes, predicts patches in a bounded worker pool, averages to p, applies τ/m from the request, produces the explanation map, uploads it, and returns `{model_version_id, oscc_probability, outcome, explanation_map_uri, inference_ms}` per model.
- Outcome mapping exactly as SRS Appendix B: `oscc_suspected` if p ≥ τ + m; `inconclusive` if τ − m ≤ p < τ + m; `non_oscc` if p < τ − m. Wording copied verbatim.
- **Build first against a dummy model** (random-weight ResNet50 registered as `dummy-v0`), so the API, frontend and tests do not wait for R3.
- API: upload (multipart, ≤ 20 MB, ≥ 224×224, JPEG/PNG/TIFF, H&E check from R1), SHA-256 content addressing, `validating → queued → processing → completed | rejected | failed` (ST2); background task triggers inference; worker sweep retries queued screenings up to 3 times; compare mode (professional/admin only, 30 s budget, failed model marked "unavailable"); result view with signed URLs (≤ 10 min); share with patient and link accept/decline; history with pagination and filters; delete with confirmation.
- Model registry: register → validate (metrics required + smoke test) → activate (single transaction, exactly one active) → retire; benchmark dashboard ordered by AUC then recall.
- **Preprocessing parity test:** the same image through the training pipeline and the inference pipeline yields identical tensors (tolerance 1e-6) and identical probabilities.

**Acceptance:** SD3, SD4, SD9 branches tested; parity test green; NFR-PER-01/02 measured with the dummy model on CPU; NFR-SAF-11 enforced by a NOT NULL FK test.

### D3. Hospital directory and recommendation (FR-3.x, FR-6.2–6.4; UC-HOS-01..03, UC-ADM-02) — Mudassir
- **Data work (team, not Claude Code):** compile a CSV in the SDS Appendix C format covering oncology centres, ENT clinics and general hospitals with oncology wards in every province and territory, each with a public `source_note`. Verify each row before marking it verified.
- CSV import with per-row validation, duplicate detection (normalized name + city), geocoding with caching, `draft → verified → stale → archived` (ST6), optimistic locking on `version`, nightly staleness job (180 days).
- Recommendation service: bounding-box prefilter (50 km → 150 km → nationwide), haversine (R = 6371 km) top 10, road distance/time refinement through the mapping adapter, re-rank, top N (default 5, clamp 3–10), facility-type filter, `distance_source` label, store only coordinates rounded to 2 dp (NFR-SEC-07). Directions URL and `tel:` link in details; "call ahead to confirm services" and last-verified date always shown.
- Mapping adapter: Google → Nominatim/OSRM → haversine only; timeouts, retries, circuit breaker.

**Acceptance:** haversine tests against known city-pair distances; radius-expansion and API-failure fallback tests; NFR-PER-03 measured; rounding test proves precise coordinates are never persisted.

### D4. Treatment plans and medication reminders (FR-5.x; UC-MED-01..03) — Mudassir (worker), Zaid (UI)
- Plans and medications (dosage text stored verbatim, "copied from my prescription" confirmation), reminder generation for 7 days, nightly window extension, cancellation on plan completion.
- Worker every 60 s: claim due reminders with `SELECT … FOR UPDATE SKIP LOCKED`, mark sent, push SSE `reminder.due`, optional email with back-off; snooze (+10 min, max 3); skip; mark missed after 60 min; idempotent per `reminder_id`.
- Adherence = taken ÷ (taken + skipped + missed), per day, range ≤ 90 days.

**Acceptance:** two concurrent worker instances never dispatch the same reminder (test); dispatch lag ≤ 2 min (NFR-PER-07); ST5 transitions covered.

### D5. Patient-support chatbot (FR-4.x, FR-6.7, FR-6.8; UC-CHT-01..02, UC-ADM-04) — Zaid
Guardrail pipeline as composable stages, in SDS order (ST4):

1. **PII scrub** (before storing or forwarding): CNIC pattern `\d{5}-?\d{7}-?\d`, Pakistani phone numbers (`+92…`, `03xx…`), the user's own stored name, and person names via a small NER model; replace with placeholders.
2. **Safety screen**: keyword list (English, Urdu, Roman Urdu — written and reviewed by the team) plus the provider's moderation capability; distress → empathetic template + active helplines + `safety_flag = true` (NFR-SAF-06). Helpline numbers are entered and verified by the team through the admin console; none are hard-coded.
3. **Intent routing**: `precaution | reminder | support | medical_decision | out_of_scope`. Rules first (dose/dosage/stop/increase/diagnose words → `medical_decision`), then an LLM classification call returning JSON only.
4. **Retrieval** (precaution): embed with the local model (O8), top 4 published articles by pgvector cosine, threshold O6; below threshold → "I don't have reviewed guidance on that; please ask your doctor" without an LLM call.
5. **LLM call** with a guarded system prompt, retrieved passages, last 10 messages; answer only from passages; cite article titles.
6. **Output check** before anything reaches the user: block diagnosis statements, doses, and advice to stop or change medication (pattern rules + a second LLM check); blocked → safe redirect. Because the check needs the full reply, generate the whole reply first, check it, then stream it to the client over SSE.
7. **Fallback** on LLM error/timeout: canned reply + knowledge-base links; circuit breaker.
8. Reminder intent: read the schedule, or return a `proposed_action` that the patient must confirm (saved through the D4 endpoints).

- Knowledge base: the team writes the initial articles (diet, lifestyle, oral care, treatment support, emotional support), each with a source reference; embedding computed on publish.
- **Guardrail evaluation suite (E3):** about 150 labelled prompts in `api/tests/guardrails/cases.yaml` with expected intent and expected behaviour; a script reports pass rate per category. Run it in CI with a recorded or mocked LLM, and once per week against the real provider.

**Acceptance:** every SD6 branch tested; NFR-SAF-05 has zero failures on the suite's dosage/diagnosis/stop-medication categories; NFR-SEC-08 test proves no PII reaches the LLM adapter.

### D6. Front end (all FRs' UI) — Zaid and Mudassir, built alongside each back-end phase
- Guided flow Upload → Result → Hospitals → Support; role dashboards (patient, professional, admin); history; compare view with heatmaps; hospital list, filter, details; chat with streaming and history; plans, reminders (SSE notifications), adherence chart; admin console (users, hospitals with CSV import report, model registry and benchmark dashboard, knowledge base, helplines, audit logs, health).
- Non-diagnostic disclaimer on every result and chat screen (NFR-SAF-01); every outcome has a label and an icon, never colour alone; plain language; externalized strings (future Urdu).
- Accessibility target WCAG 2.1 AA, checked with axe in Playwright tests.

**Acceptance:** Playwright end-to-end test of the golden flow for each role; axe reports no serious violations; initial load ≤ 3 s on a throttled 10 Mbps profile (NFR-PER-05).

### D7. Integration, deployment and system evaluation — Mudassir (lead), all
- Production Compose with Nginx TLS (TLS ≥ 1.2), GPU-optional inference, daily `pg_dump` backup and a documented restore test (NFR-SAF-08), uptime monitoring during the evaluation period (NFR-PER-08).
- Load test with Locust: 25 concurrent users on the golden flow; record every NFR-PER figure.
- Security: OWASP ZAP baseline scan, dependency audit, RBAC matrix tests (every endpoint × every role), NFR-SEC-13 linkage tests.
- Usability study (E2): SUS + task completion, consent form, anonymous results.
- User documentation (SRS §5.4): user manual, administrator guide, in-app help/FAQ, tooltips, OpenAPI docs, deployment guide/README, model cards, datasheet.

---

## 8. Timeline and ownership (Nov 2026 – May 2027)

Aligned with the proposal's Gantt chart and individual task lists; dates adjusted to start from today.

| Period | R track | D track | Milestone |
| --- | --- | --- | --- |
| 17–30 Nov 2026 | R0, R1 (audit, dedup, split) | D0, start D1 | Gate G1: dataset audit reviewed with supervisor |
| Dec 2026 | R1 finish, R2 baselines (4 models, seed 42) | D1 finish, D3 data compilation starts | **FYP-I evaluation:** dataset + baseline CNN and ViT results + running skeleton |
| Jan 2027 | R2 tuning (O1 sweep), start R3 training | D2 (dummy model), D3 | |
| Feb 2027 | R3 training (3 seeds, ablations) | D2 finish, D3 finish, D4, D5 start, D6 ongoing | Gate G2: protocol frozen, O1–O5 confirmed |
| Mar 2027 | R3 analysis, R4, R5 export → register real models | D5 finish, D6, integration of real models | Real model active in the system |
| Apr 2027 | Results chapter | D7 testing, load/security tests, usability study | Feature freeze |
| May 2027 | Final write-up | Fixes, documentation, demo deployment | Final submission |

Owners follow the proposal: Shahryar — dataset, CNNs, comparative analysis; Zaid — ViT, chatbot; Mudassir — hospital module, integration, system testing. Every module gets a second reviewer from the team.

---

## 9. Testing strategy and quality gates

| Layer | Tooling | What it covers |
| --- | --- | --- |
| Unit | pytest, vitest | services, guardrail stages, haversine, outcome mapping, metrics and bootstrap code (checked against known values) |
| Integration | pytest + Testcontainers (PostgreSQL + pgvector) | repositories, transactions, SKIP LOCKED, optimistic locking, migrations |
| API contract | pytest + httpx | every Appendix B endpoint: status codes, error codes, RBAC matrix |
| ML | pytest | identical-protocol test, leakage test, preprocessing parity test, deterministic smoke training |
| Guardrails | YAML case suite | E3 pass rates per category |
| End-to-end | Playwright + axe | golden flow per role, accessibility |
| Non-functional | Locust, ZAP, scripts | NFR-PER-01..08, NFR-SEC, NFR-SAF-08 restore test |

Quality gates: CI must be green to merge; coverage ≥ 80% for `api/app/services` and `api/app/guardrails`; every new FR has a traceability row.

---

## 10. Gaps found in SRS/SDS while planning (fold into v1.1 during the alignment fix)

These are small but Claude Code will hit them. Recommended resolutions are in brackets.

1. `screenings` has no `retry_count`, but SD3 message 30 and ST2 use it. [Add `retry_count SMALLINT NOT NULL DEFAULT 0`.]
2. UC-MED-02 sends email "if the Patient opted in", but no column stores the opt-in. [Add `reminder_email_opt_in BOOLEAN NOT NULL DEFAULT false` to `patient_profiles`.]
3. No endpoint lists a patient's chat sessions, though UC-CHT-01 step 8 opens "Conversation History". [Add `GET /api/v1/chat/sessions`.]
4. No patient-facing endpoint opens a cited knowledge article (UC-CHT-02 step 6); only admin endpoints exist. [Add `GET /api/v1/kb-articles/{id}`, published articles only.]
5. A patient can respond to a share link but cannot list pending links after a page reload (UC-SCR-04 step 5). [Add `GET /api/v1/links?status=pending`.]
6. UC-SCR-03 allows "Compare models on an existing result", but `POST /api/v1/screenings` only accepts a new file. [Add `POST /api/v1/screenings/{id}/compare`, or accept `image_id` instead of a file.]
7. The health check probes a "worker heartbeat" with no defined storage. [Add a one-row `worker_heartbeats` table or store it in the API's memory via an internal ping; document the choice.]
8. τ target recall, margin m, RAG threshold and tiling rule have no values (decisions O2, O3, O5, O6).

---

## 11. Final deliverables mapped to the proposal's expected results

| Proposal expected result | Delivered as |
| --- | --- |
| (i) Comparative table of CNN vs ViT with trade-off analysis | `docs/results/benchmark/` tables and figures, results chapter answering RQ1–RQ4, model cards |
| (ii) Geolocation-based hospital recommendation | D3 module + verified Pakistan facility CSV + E4 test report |
| (iii) Chatbot prototype (reminders, precautions, support) | D4 + D5 modules + E3 guardrail report |
| (iv) Integrated web application, end-to-end flow | D7 deployment + E1/E2 reports + user documentation |
| Dataset objective | `oscc-unified-v1` + datasheet + audit report |

---

## 12. Kick-off prompts for Claude Code

Use one prompt per phase. Start each session by letting Claude Code read `CLAUDE.md`.

**Phase D0 + R0:**
> Read docs/IMPLEMENTATION_PLAN.md, docs/SRS.md and docs/SDS.md. Implement Phase D0 and Phase R0 only. Create the repository layout from §5, the Docker Compose development stack, CI, the error envelope, logging and config modules, and the `oscc-ml` CLI with a CPU smoke-training mode on synthetic images. Stop when the acceptance checks for D0 and R0 pass, then summarize what you built and what is left.

**Phase R1:**
> Implement Phase R1. The raw data is in ml_research/data/raw/ (Kaggle [12] and Multi-OSCC [10]/[11]). Build the manifest, deduplication, group assignment, split, patch extraction with the shared preprocess module, the H&E validator, the generated audit report and the datasheet. Do not invent counts; every number must come from the scripts. Stop and show me the audit report before splitting if anything contradicts §3.

**Phase R2:**
> Implement Phase R2: model factory for the four architectures, the trainer reading configs/protocol.yaml, the identical-protocol test, the LR sweep command and the baseline report generator. Give me the exact commands to run each model on our GPU/Colab.

**Phase D1 → D7:** same pattern: "Implement Phase Dx from docs/IMPLEMENTATION_PLAN.md. Match SDS Appendix B and the data dictionary exactly. Turn every alternate scenario of the listed use cases into tests. Stop when the acceptance checks pass."
