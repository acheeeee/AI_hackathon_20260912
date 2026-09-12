# Repository Guidelines

## Source of Truth and Scope

Read `sysdoc/README.md` for the verified current system and `sysdoc/驗證報告.md` for evidence and limitations. `docs/README.md` maps the requirement documents. Design documents describe intended behavior, not implemented capabilities.

The 2026-09-12 task is audit and cleanup only. Further feature development requires explicit user authorization. Do not silently implement the new RAG, LLM, API, SQLite, or collaboration design while tidying this repository.

## Project Structure

- `frontend/`: active Vue 3 / TypeScript UI. Its `/api/*` calls still depend on `backend/api.py`.
- `backend/`: legacy compatibility backend; `backend/src/` contains its Python pipeline. Retain it until a replacement is integrated and tested. The Streamlit `app/app.py` and static `app/web/` UIs were removed while this directory was still named `app/`; it was renamed to `backend/` on 2026-09-12.
- `backend/data/kb/`: versioned legacy JSON. `backend/data/index/`: rebuildable, ignored local indexes. Neither is the new r1 release.
- `data/raw/`: original PDFs, with 141 corpus PDFs and 12 incoming-document PDFs. Preserve bytes and provenance.
- `data/processed/releases/r1/`: immutable audit subject, not accepted for new RAG ingestion. Do not trust its `validated` label as full contract acceptance; read the sysdoc findings.
- `scripts/preprocess/`, `tests/preprocess/`: current preprocessing tools and custom regression runner.
- `docs/design/`: visual design artifacts. `docs/協作設計/`: next-stage collaboration and `/api/v1` design. `docs/Reference/開發文件.md`: legal-source/design reference.

## Environments and Verification

Use Python 3.12 for the backend's pinned dependencies (`backend/requirements.txt`). The existing preprocessing environment `.venv_pre/` uses Python 3.9.6 with PyMuPDF 1.26.5; that exact local environment reproduced r1. Its dependency declaration is separate at `scripts/preprocess/requirements.txt`. Do not mix the backend's PyMuPDF 1.24.9 with r1 reproduction or assume other interpreter versions have been verified. Both environments must stay untracked.

From the repo root, with existing environments:

```bash
backend/.venv/bin/python -m tests.preprocess.test_regression
```

From `backend/`:

```bash
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m src.demo_retrieval
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000
# Only if the legacy index is missing; leaves legacy KB and r1 untouched:
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -c 'from src.build_index import build_all; build_all(use_vector=False)'
```

Do not run the old `src.build_kb` or preprocess `all/process/validate --release r1` as a smoke test: these commands write data, and validation does not cover the full handoff contract. Current `data/raw/` layout also breaks the preprocessor's category inference. Verify in an isolated output location.

From `frontend/`:

```bash
npm run dev
npm run build
npm run test:unit -- --run  # Currently exits 1: no test files
./node_modules/.bin/oxlint .
./node_modules/.bin/eslint .
```

`npm run lint` applies fixes. Use the read-only linter commands for audits. Do not install packages or change runtime setup without authorization.

## Coding and Testing

Python: four spaces, PEP 8, `snake_case` functions/modules, `PascalCase` models, annotations at public boundaries. Keep provider calls in `backend/src/providers.py`; preserve the BM25 fallback and explicit source limitations.

Vue/TypeScript: two spaces, single quotes, no semicolons, 100-column target; `PascalCase.vue` components and `camelCase` variables/functions.

Vitest is configured but no tests are committed. Future frontend tests go under `src/**/__tests__/*.spec.ts`. The preprocessing runner has 19 custom checks and no pytest dependency. Legal-logic changes require source-based regression cases; passing transport tests or showing a legal label is not evidence of legal correctness.

## Git and Configuration

Use focused commits with short imperative English summaries. PRs explain scope, data/index impact, validation and limitations. Preserve existing user changes and never stage unrelated files.

Never commit API keys, `.env`, `.venv/`, `.venv_pre/`, `node_modules/`, or `backend/data/index/`. Keep uploaded contents and credentials out of logs. Provider configuration is process environment or local env files; no secret values belong in documentation. Offline tests set both `GEMINI_API_KEY` and `GOOGLE_API_KEY` to empty strings. New backends must follow the approved case isolation and versioning contract rather than extending the legacy global `_last` state.
