import pytest

from vehicle_inventory.api.image_proxy import (
    _referer_for_url,
    guess_content_type,
    is_allowed_image_url,
    normalize_image_proxy_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://media.rti.toyota.com/image.png", True),
        ("https://www.toyota.com/foo.jpg", True),
        ("https://www.mazdausa.com/siteassets/vehicles/2026/cx-5/profile.png", True),
        ("https://www.mazdausa.com/syssiteassets/vehicles/2026/cx-30/profile.png", True),
        ("https://evil.example.com/image.png", False),
        ("ftp://media.rti.toyota.com/x.png", False),
        ("", False),
    ],
)
def test_is_allowed_image_url(url, expected):
    assert is_allowed_image_url(url) is expected


@pytest.mark.parametrize(
    ("url", "content_type"),
    [
        ("https://x.com/a.png", "image/png"),
        ("https://x.com/a.jpg", "image/jpeg"),
        ("https://x.com/a.webp", "image/webp"),
        ("https://x.com/a.gif", "image/gif"),
        ("https://x.com/a?fmt=png", "image/png"),
        ("https://x.com/unknown", "application/octet-stream"),
    ],
)
def test_guess_content_type(url, content_type):
    assert guess_content_type(url) == content_type


@pytest.mark.parametrize(
    ("url", "referer"),
    [
        ("https://www.mazdausa.com/siteassets/x.png", "https://www.mazdausa.com/"),
        ("https://media.rti.toyota.com/x.png", "https://www.toyota.com/"),
    ],
)
def test_referer_for_url(url, referer):
    assert _referer_for_url(url) == referer


def test_normalize_image_proxy_url_strips_mazda_port():
    assert (
        normalize_image_proxy_url("https://www.mazdausa.com:443/siteassets/x.png")
        == "https://www.mazdausa.com/siteassets/x.png"
    )
