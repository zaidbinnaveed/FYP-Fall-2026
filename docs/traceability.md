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
| FR-7.x research track | `ml_research/` | `ml_research/tests/` | Planned (R0 onward) |

## Non-functional requirements

| NFR | Code | Tests | Status |
| --- | --- | --- | --- |
| NFR-PER-01..08 | — | — | Planned (D2–D7) |
| NFR-PER-09 (research benchmark) | `ml_research/` | — | Planned (R3) |
| NFR-SAF-01..11 | — | — | Planned (D2–D7) |
| NFR-SEC-01..13 (except 06 and 09 above) | — | — | Planned (D1–D7) |
