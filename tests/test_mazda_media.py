from vehicle_inventory.makes.mazda.media import (
    classify_mazda_media,
    enrich_mazda_media_row,
    normalize_mazda_media_href,
)


def test_normalize_mazda_media_href():
    assert (
        normalize_mazda_media_href("https://www.mazdausa.com:443/siteassets/x.png")
        == "https://www.mazdausa.com/siteassets/x.png"
    )
    assert normalize_mazda_media_href("/siteassets/x.png") == "https://www.mazdausa.com/siteassets/x.png"


def test_classify_mazda_media_exterior_jelly():
    payload = classify_mazda_media(
        "https://www.mazdausa.com/siteassets/vehicles/2025/cx-50-hybrid/04_btv/001_trims/34-jellies/hybrid.png"
    )
    assert payload["type"] == "carjellyimage"
    assert payload["imageTag"] == "Exterior"


def test_classify_mazda_media_interior():
    payload = classify_mazda_media(
        "https://www.mazdausa.com/siteassets/vehicles/2026/cx-50-hybrid/04_btv/003_interior/interior-static.png"
    )
    assert payload["type"] == "interior"
    assert payload["imageTag"] == "Interior"


def test_classify_mazda_media_interior_360():
    href = (
        "https://www.mazdausa.com/siteassets/vehicles/2026/cx-50-hybrid/04_btv/"
        "003_interior/interior-statics/preferred/i360-my26-cx50-hybrid-preferred.jpg"
    )
    payload = classify_mazda_media(href)
    assert payload["type"] == "interior360"
    assert payload["imageTag"] == "360 Interior"
    assert ":443" not in payload["href"]


def test_enrich_mazda_media_row_normalizes_and_classifies():
    row = enrich_mazda_media_row(
        {
            "media_id": 1,
            "href": "https://www.mazdausa.com:443/siteassets/x/003_interior/interior-statics/i360-test.jpg",
            "media_type": "image",
            "image_tag": "vehicle",
        }
    )
    assert row["media_type"] == "interior360"
    assert ":443" not in row["href"]
