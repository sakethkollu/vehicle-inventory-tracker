from vehicle_inventory.core.secrets import redact_database_url, sanitize_secrets


def test_redact_database_url():
    url = "mysql+pymysql://vit:secret@mysql:3306/mazda_inventory"
    assert redact_database_url(url) == "mysql+pymysql://vit:***@mysql:3306/mazda_inventory"


def test_redact_database_url_without_user():
    url = "mysql://mysql:3306/test"
    assert redact_database_url(url) == url


def test_sanitize_secrets_in_rq_description():
    text = (
        "run_ingest_task(20, 'mazda', "
        "'mysql+pymysql://vit:secret@mysql:3306/mazda_inventory', {...})"
    )
    sanitized = sanitize_secrets(text)
    assert "secret" not in sanitized
    assert "vit:***@" in sanitized
