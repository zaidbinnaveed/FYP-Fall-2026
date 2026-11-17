# ADR-0001: Phase D0 foundations — gaps G-a to G-e

- **Status:** Accepted by the team on 17 Nov 2026, in the D0/R0 planning review.
- **Context:** While planning Phases D0 and R0 we found five points that SRS v1.0 and SDS v1.0 leave open. None of them changes a requirement. They should be folded into the next SRS/SDS revision together with plan §10.
- **Precedence:** SDS > SRS > Proposal. This ADR only fills gaps. It overrides nothing in those documents.

## G-a: Generic error codes

**Gap.** The SDS defines the envelope `{error_code, message, details, request_id}` and the use-case codes (`EMAIL_EXISTS`, `TOKEN_INVALID`, `NOT_FOUND`, `NOT_PERMITTED` …). It defines no codes for framework-level failures.

**Decision.** These codes are used when no use-case code applies. Code: `api/app/core/errors.py`.

| HTTP | `error_code` | When |
| --- | --- | --- |
| 400 / other 4xx | `BAD_REQUEST` | A malformed request with no dedicated code |
| 401 | `UNAUTHENTICATED` | Missing or invalid credentials (use-case codes such as `INVALID_CREDENTIALS` and `SESSION_EXPIRED` take precedence) |
| 403 | `NOT_PERMITTED` | Reuses the SDS SD3 code for any plain authorization failure |
| 404 | `NOT_FOUND` | Reuses the SDS code, including for unknown routes |
| 405 | `METHOD_NOT_ALLOWED` | Wrong HTTP method on a known route |
| 422 | `VALIDATION_ERROR` | Request schema validation failed; `details` lists `{loc, msg, type}` |
| 429 | `RATE_LIMITED` | Throttled |
| 503 | `SERVICE_UNAVAILABLE` | A dependency is down (for example `/readyz`) |
| 500 | `INTERNAL_ERROR` | Unhandled error; internals are never sent to the client and are logged with the request ID |

**Added in D0 beyond the four codes approved in planning.** The planning list covered only `VALIDATION_ERROR`, `UNAUTHENTICATED`, `RATE_LIMITED` and `INTERNAL_ERROR`. Three more were added so that every status code maps to an accurate code: `BAD_REQUEST`, `METHOD_NOT_ALLOWED` and `SERVICE_UNAVAILABLE`. **The team approved all three after the D0 review (Nov 2026).** The full table is also listed under "SDS v1.1 errata" in `docs/traceability.md`.

## G-b: Liveness and readiness endpoints

**Gap.** The only health endpoint in Appendix B is `GET /api/v1/admin/health`, which requires an administrator. Docker healthchecks need probes that work without authentication.

**Decision.**
- `api` exposes `GET /healthz` (liveness, always 200) and `GET /readyz` (database `SELECT 1` and storage `HeadBucket`, each with a 2 s timeout; returns 503 inside the envelope when a check fails).
- `inference` exposes the same two endpoints.
- These sit outside `/api/v1`, appear only on the private Docker network and in local development, and will not be routed by Nginx (D7).
- The worker has no HTTP port. Its healthcheck is `python -m app.worker healthcheck`, which passes when the heartbeat file is younger than 30 s.
- Plan §10 gap 7 moves the heartbeat into a `worker_heartbeats` table in migration `0002` (Phase D1) so the admin health report can read it.

## G-c: Development object storage

**Gap.** The SDS requires S3-compatible private storage with a Docker volume in development. MinIO stopped publishing community container images in 2025.

**Decision.**
- Use **SeaweedFS** (Apache-2.0), pinned to `chrislusf/seaweedfs:4.54`, with its S3 gateway on port 8333.
- At start-up, `infrastructure/storage/entrypoint.sh` writes the S3 identity file from environment variables, so no credentials are committed. Anonymous access is therefore disabled.
- The code path is the same as in production: boto3 with SigV4 presigned URLs.
- URLs are signed for `STORAGE_PUBLIC_ENDPOINT_URL`, the host the browser calls, because the signature covers the host.
- Expiry is capped at 600 s (NFR-SEC-06) in two places: in configuration and in `StorageAdapter.presign_get`.
- Integration tests run against a real SeaweedFS in CI. They prove that an expired URL, an unsigned URL and a tampered URL are each rejected with 403.

## G-d: Two meanings of `request_id`

**Gap.** In the error envelope, `request_id` is the per-HTTP-request trace ID; it is also echoed in the `X-Request-ID` header. In the `POST /api/v1/recommendations` response (SDS SD5 / Appendix B), `request_id` is the primary key of the `recommendation_requests` row.

**Decision.** Keep both names exactly as the SDS has them. They never appear in the same JSON object: an error body never carries a recommendation, and a 200 body never carries the envelope. Do not rename either one.

## G-e: Rules for smoke-mode training

**Gap.** Plan R0 requires a CPU smoke run on 32 synthetic images. It does not say how such runs are kept apart from real results.

**Decision.**
- `oscc-ml train --smoke` uses randomly initialised weights, so nothing is downloaded and CI works offline.
- It uses 32 deterministic synthetic images, a small fixed number of epochs and batch size, CPU only, AMP off, and deterministic algorithms with seeded Python, NumPy, torch and DataLoader generators.
- The resolved config records `smoke: true` and `dataset_version: synthetic-smoke`.
- The report generator (R2/R3) must refuse any run with `smoke: true`, so synthetic numbers can never reach a results table.

## Consequences

- `inference` keeps a small copy of the envelope, request-ID and logging code. It may not import `api` (dependency direction), and a shared library for about 150 lines is not worth an extra package. Both copies are covered by tests that assert the same behaviour.
