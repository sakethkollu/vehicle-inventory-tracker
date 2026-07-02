"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "vehicle_inventory" / "db" / "schema_mysql.sql"
TEST_DATABASE_URL = "mysql+pymysql://vit:pass@localhost:3306/vehicle_inventory"


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def schema_path() -> Path:
    return SCHEMA_PATH


@pytest.fixture
def test_database_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def _reset_make_registry(monkeypatch):
    """Ensure make registry is rebuilt per test when env is set."""
    import vehicle_inventory.makes.registry as registry

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    registry._REGISTRY = None
    registry._ADAPTER_CACHE = None
    yield
    registry._REGISTRY = None
    registry._ADAPTER_CACHE = None


@pytest.fixture
def settings(test_database_url, project_root, schema_path):
    from vehicle_inventory.core.config import Settings

    return Settings(
        database_url=test_database_url,
        redis_url="redis://localhost:6379/0",
        admin_password="test-admin",
        flask_secret_key="test-secret-key",
        log_level="INFO",
        log_json=False,
        schema_path=schema_path,
        project_root=project_root,
        use_redis_jobs=False,
    )


@pytest.fixture
def app(settings):
    mock_db_instance = MagicMock()
    mock_db_instance.conn = MagicMock()
    with patch("vehicle_inventory.db.InventoryDb") as mock_inventory_db:
        mock_inventory_db.return_value = mock_db_instance
        from vehicle_inventory.api.web import create_app

        yield create_app(settings)


@pytest.fixture
def client(app):
    return app.test_client()
