from vehicle_inventory.makes.mazda.models import (
    build_mazda_catalog_code_index,
    compose_mazda_model_marketing_name,
    normalize_mazda_model_code,
    resolve_mazda_series_code,
)


def test_normalize_mazda_model_code():
    assert normalize_mazda_model_code("CX-5") == "CX5"
    assert normalize_mazda_model_code("MAZDA CX-50 HYBRID") == "MAZDACX50HYBRID"


def test_build_mazda_catalog_code_index():
    index = build_mazda_catalog_code_index(
        [
            {"model_code": "CX5", "series": "CX5", "title": "MAZDA CX-5"},
            {"model_code": "CX50H", "series": "CX50H", "title": "MAZDA CX-50 HYBRID"},
        ]
    )
    assert index["CX5"] == "CX5"
    assert index["CX50H"] == "CX50H"
    assert index["MAZDACX5"] == "CX5"


def test_resolve_mazda_series_code_uses_catalog_index():
    index = build_mazda_catalog_code_index(
        [{"model_code": "CX5", "series": "CX5", "title": "MAZDA CX-5"}]
    )
    assert (
        resolve_mazda_series_code(
            carline="CX-5",
            model_name="CX-5 Select",
            catalog_index=index,
        )
        == "CX5"
    )


def test_compose_mazda_model_marketing_name_series_and_trim():
    assert (
        compose_mazda_model_marketing_name(
            marketing_series="CX-50 Hybrid",
            model_marketing_name="MAZDA CX-50 HYBRID",
            grade="Hybrid Preferred",
        )
        == "CX-50 Hybrid · Hybrid Preferred"
    )


def test_compose_mazda_model_marketing_name_uses_longer_search_name():
    assert (
        compose_mazda_model_marketing_name(
            marketing_series="CX-5",
            model_marketing_name="CX-5 2.5 S Select",
            grade="CX-5 2.5 S Select",
        )
        == "CX-5 2.5 S Select"
    )


def test_compose_mazda_model_marketing_name_same_series_and_grade():
    assert (
        compose_mazda_model_marketing_name(
            marketing_series="CX-5",
            model_marketing_name="CX-5",
            grade="CX-5",
        )
        == "CX-5"
    )
