# Repository Guidelines

## Project Structure & Module Organization

Compass is a tender-intelligence application with two main packages:

- `backend/app/`: FastAPI routes, SQLAlchemy models, crawler adapters, AI extraction, matching, notifications, and Celery tasks.
- `backend/tests/`: pytest suites and offline crawler fixtures in `tests/fixtures/`.
- `backend/scripts/`: development, evaluation, seeding, and backfill utilities.
- `frontend/app/`: Next.js App Router pages; reusable UI lives in `frontend/components/`, with API clients and shared types in `frontend/lib/`.
- `deploy/`: production Compose and deployment scripts. Product and architecture context is in `prd.md` and `tech-design.md`.

Keep public announcement data (`models/public.py`) separate from tenant-owned data (`models/tenant.py`). Every tenant-layer query must enforce `tenant_id`.

## Build, Test, and Development Commands

From `backend/`:

- `uv sync`: install Python 3.12 dependencies.
- `uv run pytest`: run the full backend suite.
- `uv run pytest tests/test_matching.py::test_name`: run one test.
- `uv run ruff check app tests scripts`: lint and validate imports.
- `uv run uvicorn app.api.main:app --port 8300`: start the local API.

From `frontend/`:

- `npm install`: install locked dependencies.
- `npm run dev`: serve the UI on port 3000.
- `npm run build`: run the required production/TypeScript build check.

From the repository root, run `docker compose up -d postgres redis minio` for local infrastructure.

## Coding Style & Naming Conventions

Python uses 4-space indentation, type hints, snake_case functions/modules, and PascalCase classes. Ruff enforces a 100-character line limit and rules `E`, `F`, `I`, `UP`, and `B`; AI prompts are the documented line-length exception. Keep Celery tasks thin and place testable business logic in `run_*` functions.

TypeScript/TSX uses 2-space indentation, PascalCase components, camelCase values, and App Router naming (`app/<route>/page.tsx`). Reuse shared types instead of duplicating API shapes.

## Testing Guidelines

Use pytest and name files/functions `test_*.py`/`test_*`. Add regression tests for API authorization, tenant isolation, matching rules, pipeline state changes, and crawler parsing. Crawler parsers should use committed fixtures rather than live sites. No numeric coverage threshold is configured; new behavior should cover success, failure, and degraded paths.

## Commit & Pull Request Guidelines

History follows Conventional Commit-style subjects, primarily `feat: ...`; use concise forms such as `fix: prevent cross-tenant source access`. PRs should explain intent and risk, link relevant issues, list verification commands, and include screenshots for UI changes. Call out schema, environment, deployment, or API-contract changes explicitly. Never commit `.env`, credentials, or production data.
