"""FastAPI application factory (ASGI entry point with Flask UI/API)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from a2wsgi import WSGIMiddleware

from vehicle_inventory.core.config import get_settings
from vehicle_inventory.core.logging import configure_logging, get_logger
from vehicle_inventory.api.web import create_app as create_flask_app

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    log.info(
        "app_starting",
        database_url=settings.database_url,
        use_redis_jobs=settings.use_redis_jobs,
        redis_url=settings.redis_url if settings.use_redis_jobs else None,
    )
    yield
    log.info("app_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    app = FastAPI(title="Vehicle Inventory Tracker", lifespan=lifespan)
    app.state.settings = settings

    flask_app = create_flask_app(settings=settings)
    app.mount("/", WSGIMiddleware(flask_app))
    return app
