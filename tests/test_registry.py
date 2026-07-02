import pytest

from vehicle_inventory.makes.registry import (
    DEFAULT_MAKE_SLUG,
    _swap_database_url,
    all_image_host_suffixes,
    get_default_make_slug,
    get_make_adapter,
    get_make_profile,
    list_makes,
    resolve_database_url,
)


def test_swap_database_url():
    base = "mysql+pymysql://user:pass@localhost:3306/vehicle_inventory"
    assert _swap_database_url(base, "mazda_inventory") == (
        "mysql+pymysql://user:pass@localhost:3306/mazda_inventory"
    )


def test_list_makes_includes_toyota_and_mazda():
    slugs = {make.slug for make in list_makes()}
    assert slugs == {"toyota", "mazda"}


def test_get_make_profile_unknown_raises():
    with pytest.raises(KeyError, match="Unknown make"):
        get_make_profile("honda")


def test_resolve_database_url_uses_separate_mazda_db():
    toyota_url = resolve_database_url("toyota")
    mazda_url = resolve_database_url("mazda")
    assert "vehicle_inventory" in toyota_url
    assert "mazda_inventory" in mazda_url
    assert toyota_url != mazda_url


def test_get_make_adapter_returns_correct_types():
    toyota = get_make_adapter("toyota")
    mazda = get_make_adapter("mazda")
    assert toyota.slug == "toyota"
    assert mazda.slug == "mazda"
    assert toyota.supports_catalog_sync() is True
    assert mazda.supports_catalog_sync() is True
    assert mazda.requires_model_selection() is True


def test_all_image_host_suffixes_unique():
    suffixes = all_image_host_suffixes()
    assert ".toyota.com" in suffixes
    assert ".mazdausa.com" in suffixes
    assert len(suffixes) == len(set(suffixes))


def test_get_default_make_slug_falls_back(monkeypatch):
    monkeypatch.delenv("DEFAULT_MAKE", raising=False)
    assert get_default_make_slug() == DEFAULT_MAKE_SLUG


def test_get_default_make_slug_respects_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_MAKE", "mazda")
    import vehicle_inventory.makes.registry as registry

    registry._REGISTRY = None
    assert get_default_make_slug() == "mazda"
