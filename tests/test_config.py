import pytest

from vehicle_inventory.core.config import Settings, get_settings


def test_get_settings_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        get_settings()


def test_get_settings_rejects_non_mysql(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp.db")
    with pytest.raises(RuntimeError, match="Only MySQL"):
        get_settings()


def test_get_settings_parses_env(monkeypatch, project_root, schema_path):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:p@localhost:3306/vehicle_inventory")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("USE_REDIS_JOBS", "1")
    monkeypatch.setenv("LOG_JSON", "0")

    settings = get_settings()
    assert settings.database_url.startswith("mysql+pymysql://")
    assert settings.redis_url == "redis://localhost:6379/1"
    assert settings.admin_password == "secret"
    assert settings.use_redis_jobs is True
    assert settings.log_json is False
    assert settings.schema_path == schema_path
    assert settings.project_root.name == "vehicle_inventory"


def test_settings_frozen(settings):
    with pytest.raises(Exception):
        settings.database_url = "other"  # type: ignore[misc]
