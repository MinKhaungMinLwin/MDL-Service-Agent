"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from api.routes import chunker, health, parser, schedule


def create_app() -> FastAPI:
    """Create and configure the Doosan MDL API."""
    app = FastAPI(
        title="Doosan MDL API",
        openapi_tags=[
            {"name": "health", "description": "Service health check."},
            {"name": "parser", "description": "PDF parser service APIs."},
            {"name": "chunker", "description": "Docling chunker service APIs."},
            {"name": "schedule", "description": "Schedule mapping and generation APIs."},
        ],
    )
    app.include_router(health.router)
    app.include_router(parser.router)
    app.include_router(chunker.router)
    app.include_router(schedule.router)
    return app


app = create_app()
