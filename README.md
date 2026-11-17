# OSCC Health Intelligence (FYP-Fall-2026)

This is a Research & Development Final Year Project at FAST-NU Karachi (Project ID AI FYP 1015). It has two deliverables of equal weight.

- **R: research.** A reproducible CNN-vs-ViT benchmark for binary OSCC classification of H&E histopathology images (`ml_research/`).
- **D: development.** A web system with screening, nearest-hospital recommendation, a guarded patient-support chatbot, medication reminders and administration (`frontend/`, `api/`, `inference/`, `infrastructure/`).

> **Not a diagnostic tool.** Every result is a screening aid and needs review by a qualified clinician.

Start here:
- [`CLAUDE.md`](CLAUDE.md): the working rules.
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md): the phases.
- `docs/SRS.md` and `docs/SDS.md`: the approved requirements and design.
- [`docs/traceability.md`](docs/traceability.md): which requirement is built where, and which test proves it.

## Repository layout

```
api/             FastAPI public API (/api/v1), background worker, admin CLI
inference/       Internal FastAPI inference service (stateless, no database)
frontend/        React + TypeScript SPA (Vite)
ml_research/     Research package `oscc_ml` and the `oscc-ml` CLI
infrastructure/  Docker Compose, .env.example, storage entrypoint, helper scripts
docs/            Plan, SRS, SDS, proposal, ADRs, traceability
```

## Local setup

Everything used here is free. These steps are written for Windows 10/11; macOS and Linux need the same tools.

### 1. Docker Desktop with WSL2

1. Run `wsl --install` in an administrator PowerShell, then reboot. This installs WSL2 and Ubuntu.
2. Install **Docker Desktop** from <https://www.docker.com/products/docker-desktop/>. It is free for education and personal use. During setup, choose **Use WSL 2 based engine**.
3. Give the WSL2 VM enough resources. Docker Desktop → *Settings → Resources → WSL integration* turns on your distro. Memory is configured in `%UserProfile%\.wslconfig`, for example:
   ```ini
   [wsl2]
   memory=6GB
   ```
4. Check the installation: `docker version` and `docker compose version`.

Docker is needed for the dev stack and, from Phase D1, for the Testcontainers integration tests.

### 2. Python tooling: uv

1. Install uv: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
2. Install the pinned Python: `uv python install 3.11`.
3. Each Python package has its own locked environment. Inside `api/`, `inference/` or `ml_research/`, run `uv sync`.

### 3. Node.js

1. Install Node.js **24 LTS** (see `frontend/.nvmrc`) from <https://nodejs.org/>, or use `nvm-windows` / `fnm`.
2. Inside `frontend/`, run `npm ci`.

### 4. pre-commit

```bash
uv tool install pre-commit
pre-commit install          # run in the repository root
pre-commit run --all-files  # optional: check everything once
```

The hooks run:
- ruff (lint and format)
- eslint and prettier
- gitleaks
- a large-file guard
- a block on committing `.env` files

### 5. Environment variables

```bash
cp infrastructure/.env.example infrastructure/.env
```

The example values are for development only. Never commit `.env`.

## Commands

| What | Command |
| --- | --- |
| Full dev stack (all services healthy) | `docker compose -f infrastructure/docker-compose.dev.yml up --build --wait` |
| Check stack health | `bash infrastructure/scripts/compose_check.sh` |
| Stop and remove dev data | `docker compose -f infrastructure/docker-compose.dev.yml down --volumes` |
| API tests | `cd api && uv run pytest` |
| API lint / types / architecture | `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports` |
| API migrations | `cd api && uv run alembic upgrade head` (the first revision arrives in Phase D1) |
| Inference tests | `cd inference && uv run pytest` |
| Frontend dev server | `cd frontend && npm run dev` |
| Frontend checks | `cd frontend && npm run lint && npm run typecheck && npm test && npm run build` |

Dev URLs (bound to `127.0.0.1` only):

| Service | URL |
| --- | --- |
| SPA | http://localhost:5173 |
| API docs | http://localhost:8000/api/v1/docs |
| Mailpit | http://localhost:8025 |
| S3 storage | http://localhost:8333 |

## Workflow

- One branch per phase (`phase/d0-foundations`, `phase/r0-environment`, …). Pull requests target `main`, and a team member reviews and merges them.
- Conventional Commit messages (`feat(api): …`, `test(ml): …`).
- CI must be green before merging. It runs:
  - lint, type checks, unit and integration tests for each package, with path filters;
  - a gitleaks secret scan;
  - on pull requests only, a full Docker Compose health check.
