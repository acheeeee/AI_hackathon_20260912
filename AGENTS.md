# Repository Guidelines

## Project Structure & Module Organization

Backend code lives in `app/`. The shared Python pipeline is under `app/src/`; `app/api.py` exposes FastAPI endpoints, while `app/app.py` provides the Streamlit demo. The active UI is the Vue 3/TypeScript app at the repository root in `frontend/src/`. Treat `app/web/` as legacy and do not add features there. Raw official PDFs live in root `data/`; parsed, versioned knowledge-base JSON lives in `app/data/kb/`, while rebuildable indexes in `app/data/index/` stay untracked. Domain and legal-design notes are under `docs/`, with `docs/Reference/開發文件.md` as the authority for legal rules.

## Build, Test, and Development Commands

Use Python 3.12 because the pinned scientific/PDF dependencies are not compatible with every Python release.

```bash
cd app
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src.build_kb                 # PDFs -> app/data/kb/*.json
python -m src.demo_retrieval          # CLI retrieval smoke test
python -m uvicorn api:app --reload --port 8000
streamlit run app.py                  # alternative demo UI
```

For the active frontend:

```bash
cd frontend
npm ci
npm run dev        # Vite on :5173; proxies /api to :8000
npm run build      # type-checks and creates the production bundle
npm run test:unit  # runs Vitest
npm run lint       # runs Oxlint and ESLint with fixes
```

## Coding Style & Naming Conventions

Use four spaces and PEP 8 for Python; name modules/functions `snake_case` and Pydantic models/classes `PascalCase`. Add type annotations at public boundaries. Route model and embedding calls through `src/providers.py`, and preserve the BM25-only fallback and source-grounding guarantees. Vue/TypeScript uses two spaces, single quotes, no semicolons, and a 100-column target via EditorConfig and Prettier. Name Vue components `PascalCase.vue` and variables/functions `camelCase`.

## Testing Guidelines

Vitest is configured, but no tests are committed and no coverage threshold is enforced. Add frontend tests as `src/**/__tests__/*.spec.ts`. The Python project does not yet declare pytest; until a backend suite is introduced, run `python -m src.demo_retrieval` and manually exercise changed API paths. Legal-logic changes must include source-based regression cases.

## Commit & Pull Request Guidelines

History uses short English summaries; make them specific and imperative, for example `Add BM25 fallback regression test`. Keep commits focused. PRs should explain scope, data/index impacts, validation commands, and linked issues. Include screenshots for UI changes and cite the relevant legal source or design note when changing domain logic.

## Security & Configuration

Create `app/.env` with `GEMINI_API_KEY=<your key>` (obtain one at https://aistudio.google.com/apikey); without it the system degrades to BM25 retrieval plus template drafts. Never commit `.env`, API keys, `.venv/`, `node_modules/`, or `app/data/index/`. A single root `.gitignore` covers both the Python and frontend trees. Do not log uploaded appeal contents or credentials.
