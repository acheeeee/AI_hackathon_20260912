# Repository Guidelines

## Source of Truth and Scope

Read `sysdoc/README.md` for the verified current system and `sysdoc/驗證報告.md` for evidence and limitations. `docs/README.md` maps the requirement documents. Design documents describe intended behavior, not implemented capabilities.

The initial 2026-09-12 task was audit and cleanup only. The user later explicitly authorized Stage A, r3/BM25, run/events, evidence adapters, a fixed-model end-to-end flow, online-model integration, BM25 gold evaluation, and vector retrieval only if measured evidence shows BM25 is insufficient. Implement in that order; each completed stage requires RED/GREEN evidence, a focused commit, and updated handoff docs. Authentication and frontend integration still require separate authorization.

## Project Structure

- `frontend/`: active Vue 3 / TypeScript UI. Its `/api/*` calls still depend on `backend/api.py`.
- `backend/`: legacy compatibility backend; `backend/src/` contains its Python pipeline. Retain it until a replacement is integrated and tested. The Streamlit `app/app.py` and static `app/web/` UIs were removed while this directory was still named `app/`; it was renamed to `backend/` on 2026-09-12.
- `backend/data/kb/`: versioned legacy JSON. `backend/data/index/`: rebuildable, ignored local indexes. Neither is the new r1/r2/r3 release. `backend/caseapi/evidence/` reads r3 directly and does not use this legacy index.
- `data/raw/`: original PDFs, with 141 corpus PDFs (under the four official category folders) and 12 incoming-document PDFs (`訴願書予行政處分函-1/`). Preserve bytes and provenance.
- `data/processed/releases/r1/`: immutable audit subject, not accepted for new RAG ingestion. Do not trust its `validated` label as full contract acceptance; read the sysdoc findings.
- `data/processed/releases/r2/`: historical intermediate release. It fixed r1's source-path, chunk-span-precision, `chunking_version`, case-family, and citation-resolution gaps. Its claim that four statutes required replacement PDFs was later disproved; the actual defect was PyMuPDF block reading order.
- `data/processed/releases/r3/`: current mechanically validated evidence release. It keeps the same raw PDF bytes and uses `ext-2.0` bbox visual ordering for statutes; all 2,214 statute-article sections have parseable article keys and all 3,103 chunk quotes rebuild from their spans. It is still not legal-review sign-off: article/label review and synthetic evaluation inputs/gold remain incomplete. See `sysdoc/verification/r3-audit.json`. Do not overwrite r1, r2, or r3; use a new release id.
- `data/evaluation/v1/`: `splits.json` only (dev/holdout case-family grouping); synthetic inputs/gold per spec §7.2 not generated.
- `scripts/preprocess/`, `tests/preprocess/`: current preprocessing tools, the historical r2 regression runner, and the four-document visual-order regression test.
- `docs/design/`: visual design artifacts. `docs/協作設計/`: next-stage collaboration and `/api/v1` design. `docs/Reference/開發文件.md`: legal-source/design reference.

## Environments and Verification

Use Python 3.12 for the backend's pinned dependencies (`backend/requirements.txt`). The existing preprocessing environment `.venv_pre/` uses Python 3.9.6 with PyMuPDF 1.26.5; that exact local environment reproduced r1, r2, and r3 (r3 was byte-identical across the final output and two independent temporary runs). Its dependency declaration is separate at `scripts/preprocess/requirements.txt`. Do not mix the backend's PyMuPDF 1.24.9 with release reproduction or assume other interpreter versions have been verified. Both environments must stay untracked.

From the repo root, with existing environments:

```bash
backend/.venv/bin/python -m tests.preprocess.test_regression  # historical r2 checks
.venv_pre/bin/python -m tests.preprocess.test_statute_layout  # current 4-law layout checks
```

From `backend/`:

```bash
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m src.demo_retrieval
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000
# Only if the legacy index is missing; leaves legacy KB and r1 untouched:
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -c 'from src.build_index import build_all; build_all(use_vector=False)'
```

Do not run the old `src.build_kb` as a smoke test: it writes data and may overwrite an empty KB from a stale root. `scripts.preprocess.run process` refuses to overwrite an existing release directory, so re-running against `r1`, `r2`, or `r3` fails fast rather than corrupting them; use a new `--release` id for any experiment. Category inference correctly reads `data/raw/<category>/...` and excludes the 12 incoming-document PDFs automatically — do not reintroduce the old `data/<category>/` assumption.

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

Vitest is configured; the first committed frontend tests live under `src/utils/__tests__/*.spec.ts`. After the fixed-model B3 flow (including the cancel-race fix), the online AWS Bedrock AgentCore provider, upload intake with rule-based appeal-letter extraction, the AI chat sidebar, and the appeal-deadline procedural review, the backend suite has 143 passing tests with 95% aggregate `caseapi` coverage; the fixed runner is covered at 98%, `agentcore_provider` at 100%, `appeal_extraction` at 94%, `EvidenceToolAdapter` at 93%, and `EvidenceRepository` at 87%; the frontend suite has 5 passing tests. `TestClient` alone missed a real cross-thread SQLite bug that only showed up under an actually-running `uvicorn` server — see 協作設計 06 §3 rule 12 — so `pytest` passing is not sufficient proof any endpoint the frontend calls actually works; verify live too. The preprocessing release validator passes 15/15 for r3 and the four-document layout regression passes 4/4. Legal-logic changes require source-based regression cases; passing transport/data-contract tests or showing a legal label is not evidence of legal correctness.

## Git and Configuration

Use focused commits with short imperative English summaries. PRs explain scope, data/index impact, validation and limitations. Preserve existing user changes and never stage unrelated files.

Never commit API keys, `.env`, `.venv/`, `.venv_pre/`, `node_modules/`, or `backend/data/index/`. Keep uploaded contents and credentials out of logs. Provider configuration is process environment or local env files; no secret values belong in documentation. Offline tests set both `GEMINI_API_KEY` and `GOOGLE_API_KEY` to empty strings. New backends must follow the approved case isolation and versioning contract rather than extending the legacy global `_last` state.
