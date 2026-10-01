from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lucia.api.health import router as health_router
from lucia.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Lucia API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router, prefix="/api")
    return app


app = create_app()
