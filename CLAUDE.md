# CLAUDE.md — OSCC Health Intelligence

Research & Development Final Year Project, FAST-NU Karachi (Sep 2026 – May 2027).
Team: Muhammad Mudassir Bhatti (lead: hospital module, integration, testing), Shahryar (dataset, CNN track, comparative analysis), Zaid (ViT track, chatbot). Supervisor: Miss Rubab Manzar.

The project has **two deliverables of equal weight**:
- **R (research):** a reproducible CNN-vs-ViT benchmark for binary OSCC classification of H&E histopathology images (`ml_research/`).
- **D (development):** a web system with screening, nearest-hospital recommendation, a guarded patient-support chatbot, medication reminders and administration (`frontend/`, `api/`, `inference/`, `infrastructure/`).

They meet at the **model registry**: research exports weights + metrics → admin registers/validates/activates them → the inference service serves them → compare mode shows all models side by side.

---

## FYP-I non-negotiable requirements (evaluation 6 Dec 2026)

Supervisor's requirements, verbatim (record and mapping: `docs/SCOPE_CHANGE_FYP1.md`):

> "Classification models 3nu. CNN ViT LLMs. And a working mock UI.
>  1. Complete dataset (tabular and images). 2. Working classification models. 3. UI: Accepted with minor changes.
>  Student must have a clear concept of using tabulated data and computer vision based image classification for their project."

- **Images + CNN/ViT:** pipeline done; training runs on the university GPU (`docs/UNI_RUNBOOK.md`).
- **Tabular dataset + classical classifiers:** approved (proposed FR-7.11, errata E16). Same images and the existing split; scikit-learn only; τ from validation; test used once.
- **LLM: on hold.** Build nothing LLM-related until the team says otherwise (errata E18).
- **Working mock UI:** React + TypeScript, fixture data in separate files, "Demo mode" banner, fictional hospitals only; supervisor's minor changes applied when received (errata E17).

---

## 1. Source documents (read before writing code)

| File | What it is | Use it for |
| --- | --- | --- |
| `docs/IMPLEMENTATION_PLAN.md` | Phases, decisions, acceptance checks | **What to build next and when it is done** |
| `docs/SDS.md` (+ `docs/figures/SDS/`) | Supervisor-approved design | Data dictionary (20 tables), sequence diagrams (exact endpoints, parameters, error codes), state diagrams, Appendix A training protocol, Appendix B endpoint catalog, Appendix C hospital CSV format |
| `docs/SRS.md` (+ `docs/figures/SRS/`) | Supervisor-approved requirements | FR-x.y hierarchy, 21 use cases with alternate scenarios, NFRs, Appendix B outcome wording |
| `docs/proposal.pdf` / `proposal.txt` | Original proposal | Research motivation and expected results |

**Precedence when they disagree:** SDS > SRS > Proposal. The plan never overrides them.
If something is missing or contradictory, **stop and ask** — do not guess. Known gaps and their agreed fixes are in plan §10; open decisions and their defaults are in plan §4.2.

Figures are PNGs; open them (ERDs, sequence and state diagrams) when implementing the matching part.

---

## 2. How to work in this repo

- Work **only on the phase named in the prompt**. Finish it, run its acceptance checks (plan §6/§7), then stop and report.
- Before a non-trivial phase, write a short plan (files to create, order, tests) and wait for approval.
- Every use-case **alternate scenario becomes a test**. Add one row per FR/UC to `docs/traceability.md` (FR/UC → code path → test name).
- Small, focused commits with Conventional Commit messages (`feat(api): …`, `test(ml): …`). One branch per phase: `phase/d1-accounts`, `phase/r1-dataset`.
- Run lint, type checks and tests before saying anything is done. Report which acceptance checks pass and which do not.
- Long GPU jobs: write the code and give the exact command to run on the lab GPU / Colab / Kaggle. Do not try full training here.

---

## 3. Non-negotiable rules

**Integrity (research)**
- Never invent data, metrics, counts, results, citations, hospital records, helpline numbers or knowledge-base content. Every number in a report is produced by a script from a saved run directory.
- If a run has not been executed, the report says "not yet run" — never a placeholder number.

**Design fidelity**
- Table, column, enum value, status, endpoint, query/body field and `error_code` names match the SDS **exactly**.
- Error responses always use `{error_code, message, details, request_id}`.
- Timestamps stored in UTC (ISO 8601), displayed in PKT.

**Safety (medical-adjacent product)**
- Outcome mapping and user-facing text exactly as SRS Appendix B:
  `oscc_suspected` if p ≥ τ + m · `inconclusive` if τ − m ≤ p < τ + m · `non_oscc` if p < τ − m.
- A non-diagnostic disclaimer appears on every result and every chatbot screen.
- The chatbot never gives a diagnosis, a dose, or advice to stop/change medication. The **full** reply passes the output check before anything is streamed to the client.
- Every prediction stores the `model_version_id` that produced it.

**Privacy & security**
- Names, phone numbers and CNIC numbers are scrubbed from chat text before storage and before any external API call.
- Only coordinates rounded to 2 decimal places are persisted.
- Images and explanation maps live in private object storage, served only through signed URLs that expire in ≤ 10 minutes.
- Secrets only from environment variables; add every new variable to `infrastructure/.env.example`. Never commit `.env`, data, weights or run folders.
- Passwords: Argon2id. JWT access 15 min / refresh 7 days, httpOnly secure cookies, refresh rotation. Lockout: 5 failures → 15 min.

**Architecture**
- Dependency direction: `frontend → api → inference → ml_research (preprocess + weights)`. No cycles.
- In `api`, only `repositories/` touch SQL; providers (LLM, mapping, email, storage, inference) are reached only through `adapters/`.
- `api` never imports `torch`. The inference service is stateless and has no database access.

---

## 4. Research track rules (`ml_research/`)

- **Models:** ResNet50, EfficientNet-B0, DenseNet121 (torchvision ImageNet-1k weights) and ViT-B/16 (HuggingFace `google/vit-base-patch16-224`, `attn_implementation="eager"` for attention rollout). **PyTorch only.**
- Binary task, single logit, `BCEWithLogitsLoss` with `pos_weight` from the training class ratio.
- **One protocol file** `configs/protocol.yaml` (SDS Appendix A): 224×224 patches · ImageNet mean/std · train-only aug (h/v flips, 90° rotations, mild colour jitter) · AdamW identical settings · LR from a shared sweep {1e-5, 3e-5, 1e-4, 3e-4, 1e-3} · batch 32 · max 50 epochs, early stopping on val AUC, patience 7 · AMP · seed 42. Per-model configs may set **only** the architecture name; a test enforces this.
- **One preprocessing module** `oscc_ml.preprocess` (tiling, tissue filter, normalization, optional stain normalization, H&E check) used by **both** training and the inference service. A parity test (same image → identical tensor and probability) must stay green.
- **Data (plan §3):** the primary benchmark uses the Kaggle/Rahman dataset rebuilt from original images (publisher augmented copies `aug_*` excluded by name; duplicates removed by SHA-256 + pHash ≤ 4 plus a reviewed list, ADR-0005). Split 70:15:15, seed 42, grouped by patient (or, with no patient IDs, by pHash similarity groups at distance ≤ 10 — documented deviation, errata E7). No sha256, pHash cluster or patient may appear in two splits. **Multi-OSCC is OSCC-only: use it only as an external positive test set, never as training data in the primary benchmark.**
- **Evaluation:** image level (mean of patch probabilities) is primary. 95% bootstrap CIs resampling patients/groups. Paired bootstrap ΔAUC + McNemar at τ, Holm correction. Cost: params, GFLOPs (`torch.utils.flop_counter`), CPU/GPU latency (batch 1, warm-up), peak memory, training time.
- **Threshold τ:** on validation, the threshold with max F1 among those reaching target recall (default 0.95); margin m default 0.05 (plan decisions O2/O3).
- Each run writes `runs/<timestamp>_<model>_<seed>/` with resolved config, git commit, `dataset_version`, logs, best checkpoint, val/test predictions and metrics JSON. Reports are regenerated only from these folders.

---

## 5. Development track rules

- Stack: Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, PostgreSQL 16 + pgvector, S3-compatible object storage (boto3), SSE via `sse-starlette`; React + TypeScript (Vite), React Router, TanStack Query; Docker Compose + Nginx.
- First migration creates **all 20 tables** from the data dictionary with CHECK constraints for every enum; plan §10 errata columns go in the second migration.
- The worker claims due work with `SELECT … FOR UPDATE SKIP LOCKED` (reminders every 60 s, screening retries, nightly jobs) and writes a heartbeat.
- Build the inference service and screening flow **against a dummy model** (`dummy-v0`) first; real weights are registered later through the admin API.
- External providers degrade gracefully: mapping → Google → Nominatim/OSRM → haversine-only (labelled "straight-line distance"); LLM failure → canned reply with knowledge-base links; email failure → retry with back-off.
- Front end: guided flow Upload → Result → Hospitals → Support; outcomes always shown with label + icon (never colour alone); plain language; WCAG 2.1 AA (checked with axe).

---

## 6. Repository map

```
CLAUDE.md
docs/            plan, SRS, SDS, proposal, figures/, traceability.md, datasheet.md, model_cards/, results/
ml_research/     configs/  src/oscc_ml/{data,preprocess,models,train,eval,cost,explain,export}/  scripts/  notebooks/  data/ (gitignored)  runs/ (gitignored)
inference/       FastAPI internal service: /internal/infer, /internal/models/load
api/app/         core/ db/ schemas/ routers/ services/ guardrails/ repositories/ adapters/ worker/ cli.py
frontend/        React SPA
infrastructure/  docker-compose.dev.yml, docker-compose.prod.yml, nginx/, .env.example, backup/, loadtest/
```

---

## 7. Commands

Fill these in as they are created in Phase D0/R0, and keep them accurate.

```bash
cp infrastructure/.env.example infrastructure/.env                         # once
docker compose -f infrastructure/docker-compose.dev.yml up --build --wait   # full dev stack, all healthy
bash infrastructure/scripts/compose_check.sh                               # assert every service healthy
cd api && uv sync && uv run pytest                                         # API unit tests (+ storage integration if STORAGE_INTEGRATION_ENDPOINT_URL is set)
cd api && uv run ruff check . && uv run mypy && uv run lint-imports        # API lint, types, architecture contracts
cd api && uv run alembic upgrade head                                      # migrations (first revision in D1)
cd api && uv run python -m app.cli create-admin                            # first administrator (Phase D1)
cd inference && uv sync && uv run pytest                                   # inference service tests
cd ml_research && uv venv && bash scripts/install_pinned.sh --torch cpu --extra train --dev   # research package, CPU torch (laptop/CI)
#   Colab/Kaggle: --torch platform (notebooks/oscc_ml_runner.ipynb)   |   lab GPU: --torch locked
# University GPU machine (Windows: .ps1 via `powershell -ExecutionPolicy Bypass -File ...`; Linux: .sh):
ml_research/scripts/uni_setup.{ps1,sh}                                     # uv venv, CUDA torch matching nvidia-smi, oscc_ml (no admin)
ml_research/scripts/uni_check.{ps1,sh}                                     # Python, GPU/VRAM, disk, write access, weights, 2-min GPU smoke
ml_research/scripts/uni_run.{ps1,sh} <zip>                                 # background, resumable: prepare -> sweep -> train-all -> evaluate -> report -> pack (docs/UNI_RUNBOOK.md)
oscc-ml prepare --raw <zip or folder>                                      # manifest (SHA-256 + pHash), dedup, grouped 70:15:15 split, leakage test, 224 px patches
oscc-ml make-sample --raw <zip or folder> --per-class 30                   # small local sample in data/sample/ (reads only those files)
oscc-ml prepare --raw <zip or folder> --manifest-only --out <new folder>   # dry run: hashing, dedup, label-conflict exclusion (ADR-0003), split, leakage test; no patches
oscc-ml check-leakage                                                      # re-run the leakage test on a prepared dataset
oscc-ml make-test-zip --out <zip>                                          # synthetic Kaggle-like archive for CI and dry runs
oscc-ml train --model resnet50 --smoke                                     # CPU smoke training (synthetic, not reportable)
oscc-ml sweep                                                              # shared LR sweep -> runs/sweep/chosen_lr.json (resumable)
oscc-ml train-all --resume                                                 # 4 models x seed 42 with the chosen LR (resumable)
oscc-ml evaluate                                                           # ONLY step that reads test: test preds from best.pt, tau from val, CIs, calibration, errors, paired comparisons, cost
oscc-ml report --copy-to ../docs/results/baseline_fyp1.md                  # baseline table from run folders only (refuses smoke/synthetic)
oscc-ml pack-results                                                       # runs/export/results_small.zip + checkpoints.zip (SHA-256 manifest)
oscc-ml import-results results_small.zip                                   # at home: verify + unpack into runs/, then `oscc-ml report`
oscc-ml check / oscc-ml env / oscc-ml make-synthetic-data --out <dir>      # readiness check / environment info / test data
oscc-ml tabular-extract --manifest <prepare manifest.csv> --raw <raw folder>   # tabular dataset (Phase T): data/processed/tabular/oscc_features_v1.csv (+ cues, extraction.json)
oscc-ml tabular-check --manifest <manifest.csv>                            # rows = kept images, no NaNs, split/label/magnification/group = manifest
oscc-ml tabular-train / tabular-shortcut / tabular-report                  # LR, RF, GB runs (image-run format) / shortcut check / TABULAR_RESULTS.md
cd frontend && npm ci && npm run dev                                       # SPA dev server
cd frontend && npm test && npx playwright test                             # unit + e2e (Playwright from D6)
```

## 8. Definition of done (every phase)

1. Acceptance checks in the plan pass in CI.
2. Every listed use case's main and alternate scenarios have tests.
3. `docs/traceability.md` updated.
4. No hard-coded secrets, no invented data, no TODOs left without an issue reference.
5. A short phase report: what was built, how to run it, what is left, any doc gaps found.
