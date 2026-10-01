from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lucia.api.health import router as health_router
from lucia.api.tags import openapi_tags
from lucia.auth.router import router as auth_router
from lucia.connectors.hooks import router as hooks_router
from lucia.connectors.oauth import router as oauth_router
from lucia.connectors.router import router as connections_router
from lucia.core.config import get_settings
from lucia.core.errors import install_error_handlers
from lucia.db.session import get_sessionmaker
from lucia.firms.router import router as firms_router
from lucia.mappings.router import router as mappings_router
from lucia.platform.router import router as platform_router
from lucia.registry.router import router as registry_router
from lucia.registry.sync import sync_registry
from lucia.studio.agents_router import router as agents_router
from lucia.studio.versions_router import router as versions_router

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with get_sessionmaker()() as session:
        await sync_registry(session)
    yield


def api_router() -> APIRouter:
    api = APIRouter(prefix=API_PREFIX)
    for r in (
        health_router,
        auth_router,
        firms_router,
        registry_router,
        agents_router,
        versions_router,
        connections_router,
        oauth_router,
        hooks_router,
        mappings_router,
        platform_router,
    ):
        api.include_router(r)
    return api


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Lucia API", version="0.1.0", openapi_tags=openapi_tags(), lifespan=lifespan
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(api_router())
    return app


app = create_app()
