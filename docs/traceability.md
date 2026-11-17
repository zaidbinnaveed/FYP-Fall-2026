# Traceability: requirement → code → test

This file extends SRS Appendix A down to code. Each FR, NFR, use case and design rule gets one row once code implements it. A row lists the code path and the test(s) that prove it.

**Status values**
- **Done:** implemented and tested.
- **Partial:** only the part needed by the current phase exists; the "Notes" column says what is left.
- **Planned:** the phase is named and nothing has been built yet.

## Cross-cutting design rules (SDS global error handling, NFR-SEC)

| Requirement | Code | Tests | Status |
| --- | --- | --- | --- |
| SDS error envelope `{error_code, message, details, request_id}` | `api/app/core/errors.py`, `inference/inference_service/observability.py` | `api/tests/test_errors.py::*`, `inference/tests/test_service.py::test_unknown_route_uses_envelope`, `::test_unhandled_error_hides_internals` | Done (D0) |
| Generic error codes (ADR-0001 G-a) | `api/app/core/errors.py::GenericErrorCode` | `api/tests/test_errors.py::test_http_errors_are_mapped`, `::test_method_not_allowed`, `::test_validation_error_lists_fields` | Done (D0) |
| Request IDs in every response and log line (SDS global error handling) | `api/app/core/request_id.py`, `api/app/core/logging.py` | `api/tests/test_request_id.py::*`, `api/tests/test_logging.py::*` | Done (D0) |
| Structured JSON logs (SDS) | `api/app/core/logging.py`, `inference/inference_service/observability.py` | `api/tests/test_logging.py::test_formatter_emits_json_with_request_id`, `inference/tests/test_service.py::test_access_log_is_json` | Done (D0) |
| Timestamps in UTC ISO 8601, displayed in PKT (CLAUDE.md) | `api/app/core/time.py` | `api/tests/test_time.py::*` | Done (D0) |
| NFR-SEC-09: secrets only from environment variables | `api/app/core/config.py`, `infrastructure/.env.example`, `.gitignore`, `.pre-commit-config.yaml` (gitleaks, forbid-env-files) | `api/tests/test_config.py::test_missing_required_variable_fails_fast`, `::test_secrets_are_masked_in_repr`, `::test_every_setting_is_documented_in_env_example`; CI job `secrets` (gitleaks over full history) | Done (D0) |
| NFR-SEC-06: private storage, signed URLs ≤ 10 min | `api/app/adapters/storage.py`, `api/app/core/config.py` | `api/tests/test_storage.py::test_default_expiry_is_at_most_600_seconds`, `::test_out_of_range_expiry_is_refused`, `::test_live_signed_url_works_then_expires`, `::test_live_unsigned_and_tampered_urls_rejected`; `api/tests/test_config.py::test_signed_url_ttl_above_ten_minutes_rejected` | Partial (D0: adapter; image use in D2) |
| Architecture: `api` never imports torch | `api/pyproject.toml` (import-linter contract) | `api/tests/test_architecture.py::test_importing_the_app_never_loads_torch`; CI step `lint-imports` | Done (D0) |
| Architecture: only repositories touch SQL; providers only via adapters | `api/pyproject.toml` (import-linter contracts) | CI step `lint-imports` | Done (D0) |
| Architecture: inference is stateless, no DB access | `inference/pyproject.toml` (import-linter contract) | `inference/tests/test_service.py::test_service_has_no_database_driver_loaded`; CI step `lint-imports` | Done (D0) |
| Liveness/readiness probes (ADR-0001 G-b) | `api/app/routers/health.py`, `inference/inference_service/main.py`, `api/app/worker/heartbeat.py` | `api/tests/test_health.py::*`, `api/tests/test_worker.py::*`, `inference/tests/test_service.py::test_healthz`; CI job `compose` | Done (D0) |

## Functional requirements

| FR / UC | Code | Tests | Status |
| --- | --- | --- | --- |
| FR-1.x / UC-USR-01..03 accounts | — | — | Planned (D1) |
| FR-2.x / UC-SCR-01..05 screening | — | — | Planned (D2) |
| FR-3.x / UC-HOS-01..03 hospitals | — | — | Planned (D3) |
| FR-4.x / UC-CHT-01..02 chatbot | — | — | Planned (D5) |
| FR-5.x / UC-MED-01..03 reminders | — | — | Planned (D4) |
| FR-6.x / UC-ADM-01..05 administration | — | — | Planned (D1–D5) |
| FR-7.4 (7.4.1–7.4.3): CNN training (ResNet50, EfficientNet-B0, DenseNet121) and FR-7.5: ViT training (ViT-B/16, eager attention) | `ml_research/src/oscc_ml/models/factory.py`, `train/trainer.py`, `train/runner.py`, `train/sweep.py`, `train/train_all.py`, `cli.py` (`train`, `sweep`, `train-all --resume`) | `ml_research/tests/test_models.py::*`, `test_pipeline.py::test_sweep_writes_the_choice_and_never_reads_test`, `::test_train_all_uses_the_chosen_lr_and_records_it`, `::test_train_all_resume_skips_completed_runs`, `::test_resume_after_interruption_matches_an_uninterrupted_run`, `test_smoke_run.py::*`; CI steps "R0 acceptance" and "University scripts" | Done for code (R2 scripts); baseline runs not yet run (university GPU) |
| FR-7.6: identical protocol for every model | `ml_research/configs/protocol.yaml`, `src/oscc_ml/config.py` | `ml_research/tests/test_protocol.py::test_every_model_config_sets_only_the_architecture`, `::test_resolved_protocol_is_identical_across_models`, `::test_model_config_with_extra_key_is_rejected`, `::test_protocol_matches_sds_appendix_a` | Done (R0 guard; enforced as models are added in R2) |
| Run provenance (plan R0): resolved config, git commit, dataset_version, environment incl. torch/torchvision/transformers/CUDA versions and GPU name, logs, checkpoint, predictions, metrics | `ml_research/src/oscc_ml/train/runner.py`, `runinfo.py` | `ml_research/tests/test_smoke_run.py::test_run_folder_has_every_artifact`, `::test_run_info_records_provenance`, `::test_environment_records_versions_and_gpu` | Done (R0) |
| Reproducibility: seeded Python, NumPy and torch, deterministic algorithms, seeded DataLoader generator and `worker_init_fn` | `ml_research/src/oscc_ml/utils/seeding.py` | `ml_research/tests/test_smoke_run.py::test_same_seed_runs_are_identical`, `test_units.py::test_seeding_makes_all_rngs_repeatable`, `::test_worker_init_fn_seeds_python_and_numpy_from_torch` | Done (R0) |
| Image-level aggregation = mean of patch probabilities (SDS) | `ml_research/src/oscc_ml/eval/metrics.py::aggregate_to_images` | `ml_research/tests/test_units.py::test_aggregation_is_mean_of_patch_probabilities` | Done (R0) |
| Smoke runs are never reportable (ADR-0001 G-e) | `ml_research/src/oscc_ml/train/runner.py` (`smoke`, `reportable: false`, `dataset_version: synthetic-smoke`) | `ml_research/tests/test_smoke_run.py::test_run_info_records_provenance`, `::test_cli_rejects_real_training_before_r1` | Partial (the report generator's refusal is added in R2) |
| FR-7.7: evaluation (accuracy, precision, recall, F1, AUC-ROC, confusion/outcome counts) with 95% grouped bootstrap CIs; tau from validation (O2), margin m (O3) | `ml_research/src/oscc_ml/eval/{threshold,bootstrap,evaluate}.py`, `report/__init__.py` | `ml_research/tests/test_eval.py::*`, `test_pipeline.py::test_evaluation_has_ci_threshold_and_cost`, `::test_report_from_run_folders`, `::test_cli_report_refuses_synthetic_and_noncompliant_runs`, `::test_report_refuses_smoke_only` | Partial (paired tests, McNemar, Holm and 3 seeds in R3) |
| FR-7.8: computational cost (parameters, GFLOPs, CPU/GPU latency, peak memory, training time) | `ml_research/src/oscc_ml/cost/__init__.py`, `eval/evaluate.py`, `train/trainer.py` | `ml_research/tests/test_eval.py::test_gflops_match_the_published_resnet50_cost`, `::test_latency_measurement_shape`, `test_pipeline.py::test_evaluation_has_ci_threshold_and_cost` | Done for code; measurements not yet run |
| Results transfer between the university GPU and home (no checkpoints in the small archive; SHA-256 manifest; safe import) | `ml_research/src/oscc_ml/results.py` | `ml_research/tests/test_pipeline.py::test_pack_and_import_roundtrip`, `::test_import_refuses_path_traversal`, `::test_import_refuses_corrupt_and_conflicting_files` | Done |
| University machine readiness (Python, GPU/VRAM, disk, write access, weights, GPU smoke of all four models) | `ml_research/src/oscc_ml/check.py`, `scripts/uni_setup.{ps1,sh}`, `scripts/uni_check.{ps1,sh}`, `scripts/install_pinned.py` | `ml_research/tests/test_check.py::*`; CI job "University scripts" on Ubuntu and Windows | Done (CPU mode in CI; GPU path at the university) |
| FR-7.1–7.3 (minimal R1): manifest with SHA-256 + pHash, removal of augmented copies/near-duplicates (dihedral pHash), grouping (patient regex or pHash similarity clusters), grouped stratified 70:15:15 split with seed 42, leakage test, O5 tiling into 224 px patches, count summary | `ml_research/src/oscc_ml/data/{sources,dedup,split,prepare,sample,testzip}.py`, `preprocess/__init__.py`, `cli.py` (`prepare`, `make-sample`, `check-leakage`) | `ml_research/tests/test_prepare.py::*`, `test_preprocess.py::*` | Partial (code done and tested on synthetic data; not yet run on the Kaggle archive; Multi-OSCC external set, H&E validator, audit report and datasheet remain for full R1) |
| Unattended university pipeline (resumable, logged, single instance, background) | `ml_research/src/oscc_ml/pipeline.py`, `scripts/uni_run.{ps1,sh}`, `docs/UNI_RUNBOOK.md` | `ml_research/tests/test_uni_run.py::*`; CI job "University scripts" (uni_run twice on Ubuntu and Windows) | Done (synthetic data); real run pending |
| Report and import need no torch (light install at home) | `ml_research/src/oscc_ml/catalog.py`, `utils/gitinfo.py` | `ml_research/tests/test_protocol.py::test_report_and_import_work_without_torch` | Done |
| FR-7.9 interpretation, FR-7.10 export/registration | `ml_research/` | — | Planned (R4, R5) |

## Non-functional requirements

| NFR | Code | Tests | Status |
| --- | --- | --- | --- |
| NFR-PER-01..08 | — | — | Planned (D2–D7) |
| NFR-PER-09 (research benchmark) | `ml_research/` | — | Planned (R3) |
| NFR-SAF-01..11 | — | — | Planned (D2–D7) |
| NFR-SEC-01..13 (except 06 and 09 above) | — | — | Planned (D1–D7) |

## SDS v1.1 errata

This section lists additions agreed by the team that are not yet in SDS v1.0. Fold each one into the next SDS revision.

| # | Item | Agreed in | Where |
| --- | --- | --- | --- |
| E1 | Generic error codes `VALIDATION_ERROR` (422), `UNAUTHENTICATED` (401), `RATE_LIMITED` (429), `INTERNAL_ERROR` (500) | D0 plan approval | ADR-0001 G-a; `api/app/core/errors.py` |
| E2 | Generic error codes `BAD_REQUEST` (other 4xx), `METHOD_NOT_ALLOWED` (405), `SERVICE_UNAVAILABLE` (503) | D0 review | ADR-0001 G-a; `api/app/core/errors.py` |
| E3 | Unauthenticated `GET /healthz` and `GET /readyz` on `api` and `inference`, internal only | D0 plan approval | ADR-0001 G-b |
| E4 | Development object storage: SeaweedFS (S3-compatible) | D0 plan approval | ADR-0001 G-c |
| E5 | The two meanings of `request_id` (error-envelope trace ID vs `recommendation_requests` key) are kept as they are | D0 plan approval | ADR-0001 G-d |
| E6 | Plan §10 gaps 1–8 resolved as the plan recommends (to be applied in their phases) | D0 plan approval | `docs/IMPLEMENTATION_PLAN.md` §10 |
