"""新版案件 API 進入點。

與舊 backend/api.py 並存：舊的 /api/* 仍供現有 Vue demo 使用，新的契約掛在
/api/v1，兩者不共用狀態。
"""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from caseapi.ai.agentcore_provider import AgentCoreModelProvider
from caseapi.ai.contracts import ModelProvider
from caseapi.ai.fixed_provider import FixedModelProvider
from caseapi.api.routes_annotations import router as annotations_router
from caseapi.api.routes_cases import router as cases_router
from caseapi.api.routes_chat import router as chat_router
from caseapi.api.routes_documents import router as documents_router
from caseapi.api.routes_drafts import router as drafts_router
from caseapi.api.routes_evidence import router as evidence_router
from caseapi.api.routes_facts import router as facts_router
from caseapi.api.routes_intake import router as intake_router
from caseapi.api.routes_procedural_review import router as procedural_review_router
from caseapi.api.routes_statute_selection import router as statute_selection_router
from caseapi.api.routes_proposals import router as proposals_router
from caseapi.api.routes_resources import router as resources_router
from caseapi.api.routes_runs import router as runs_router
from caseapi.config import Settings, load_settings
from caseapi.db.connection import connect
from caseapi.db.migrations import apply_migrations
from caseapi.envelope import error_response
from caseapi.errors import ApiError, database_busy, invalid_field, malformed_request
from caseapi.ids import new_id
from caseapi.tools.evidence_tools import EvidenceRepositoryLike

API_TITLE = '訴願案件協作 API'
API_VERSION = '1.0.0'
_BUSY_MARKERS = ('locked', 'busy')


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    conn = connect(app.state.settings.db_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    yield


def create_app(
    settings: Settings | None = None,
    *,
    evidence_repository: EvidenceRepositoryLike | None = None,
    model_provider: ModelProvider | None = None,
) -> FastAPI:
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        lifespan=_lifespan,
        docs_url='/api/v1/docs',
        openapi_url='/api/v1/openapi.json',
    )
    app.state.settings = settings or load_settings()
    app.state.evidence_repository = evidence_repository
    app.state.model_provider = model_provider or _build_model_provider(app.state.settings)

    @app.middleware('http')
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = new_id('req')
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(request, _translate_validation_error(exc))

    @app.exception_handler(sqlite3.OperationalError)
    async def handle_sqlite_busy(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        if not any(marker in str(exc).lower() for marker in _BUSY_MARKERS):
            raise exc
        return error_response(request, database_busy())

    for router in (
        cases_router,
        intake_router,
        documents_router,
        facts_router,
        procedural_review_router,
        statute_selection_router,
        drafts_router,
        annotations_router,
        proposals_router,
        resources_router,
        runs_router,
        chat_router,
        evidence_router,
    ):
        app.include_router(router)
    return app


def _build_model_provider(settings: Settings) -> ModelProvider:
    """Pick the provider by `settings.model_provider`; default stays offline.

    `fixed` needs nothing else and works with no network or credentials.
    `agentcore` needs a deployed runtime ARN (see
    `backend/scripts/deploy_agentcore.py`); fail fast on misconfiguration
    instead of silently falling back, so a demo never *looks* like it is
    using the online model when it is actually still on the fixed one.
    """
    if settings.model_provider == 'fixed':
        return FixedModelProvider()
    if settings.model_provider == 'agentcore':
        if not settings.agentcore_runtime_arn:
            raise ValueError(
                'CASEAPI_MODEL_PROVIDER=agentcore requires CASEAPI_AGENTCORE_RUNTIME_ARN'
            )
        return AgentCoreModelProvider(
            runtime_arn=settings.agentcore_runtime_arn,
            region=settings.agentcore_region or 'us-west-2',
        )
    raise ValueError(f'unknown CASEAPI_MODEL_PROVIDER: {settings.model_provider!r}')


def _translate_validation_error(exc: RequestValidationError) -> ApiError:
    """壞掉的 JSON 是格式問題（400）；欄位不合規則是驗證問題（422）。"""
    errors = exc.errors()
    if any(error.get('type') == 'json_invalid' for error in errors):
        return malformed_request()
    return invalid_field('請求欄位未通過驗證', {'fields': _describe_fields(errors)})


def _describe_fields(errors: list[dict]) -> list[dict[str, str]]:
    return [
        {
            'location': '.'.join(str(part) for part in error.get('loc', ())),
            'message': error.get('msg', ''),
        }
        for error in errors
    ]


app = create_app()
