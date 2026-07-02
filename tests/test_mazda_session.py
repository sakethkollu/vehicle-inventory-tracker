import json

import pytest

from vehicle_inventory.makes.mazda.session import cookies_from_env


def test_cookies_from_env_empty(monkeypatch):
    monkeypatch.delenv("MAZDA_SESSION_COOKIE", raising=False)
    assert cookies_from_env() == {}


def test_cookies_from_env_json_object(monkeypatch):
    monkeypatch.setenv("MAZDA_SESSION_COOKIE", json.dumps({"ak_bmsc": "abc", "session": "xyz"}))
    assert cookies_from_env() == {"ak_bmsc": "abc", "session": "xyz"}


def test_cookies_from_env_header_string(monkeypatch):
    monkeypatch.setenv("MAZDA_SESSION_COOKIE", "foo=bar; baz=qux")
    assert cookies_from_env() == {"foo": "bar", "baz": "qux"}


def test_cookies_from_env_invalid_json_falls_back_to_header(monkeypatch):
    monkeypatch.setenv("MAZDA_SESSION_COOKIE", "{not-json; valid=1")
    assert cookies_from_env() == {"valid": "1"}
