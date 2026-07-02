def test_api_makes_lists_both_makes(client):
    response = client.get("/api/makes?make=toyota")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["current"]["slug"] == "toyota"
    assert payload["current"]["supports_catalog_sync"] is True
    slugs = {make["slug"] for make in payload["makes"]}
    assert slugs == {"toyota", "mazda"}


def test_api_makes_mazda_flags(client):
    response = client.get("/api/makes?make=mazda")
    assert response.status_code == 200
    current = response.get_json()["current"]
    assert current["slug"] == "mazda"
    assert current["requires_model_selection"] is True
    assert current["supports_catalog_sync"] is True
    assert current["inventory_origin"] == "https://www.mazdausa.com/"


def test_favicon_serves_svg(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert "image/svg" in response.content_type


def test_static_favicon_svg(client):
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200


def test_index_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Vehicle Inventory Tracker" in response.data


def test_session_make_switch(client):
    response = client.post(
        "/api/session/make",
        json={"make": "mazda"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["make"] == "mazda"
