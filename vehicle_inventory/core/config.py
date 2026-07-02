"""Application configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    admin_password: str
    flask_secret_key: str
    log_level: str
    log_json: bool
    schema_path: Path
    project_root: Path
    use_redis_jobs: bool


def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    database_url = _env("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required (e.g. mysql+pymysql://user:pass@localhost:3306/vehicle_inventory)"
        )
    if not database_url.startswith("mysql"):
        raise RuntimeError(f"Only MySQL DATABASE_URL is supported, got: {database_url.split('://', 1)[0]}://")

    schema_path = Path(__file__).resolve().parent.parent / "db" / "schema_mysql.sql"
    redis_url = _env("REDIS_URL", "redis://localhost:6379/0")
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        admin_password=_env("ADMIN_PASSWORD"),
        flask_secret_key=_env("FLASK_SECRET_KEY"),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        log_json=_env_bool("LOG_JSON", True),
        schema_path=schema_path,
        project_root=project_root,
        use_redis_jobs=_env_bool("USE_REDIS_JOBS", bool(_env("REDIS_URL"))),
    )
