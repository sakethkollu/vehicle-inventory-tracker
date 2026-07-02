from datetime import datetime, timezone

from vehicle_inventory.jobs.runs import (
    _duration_sec,
    _parse_iso,
    _parse_json_field,
    geocode_params,
    ingest_params_from_payload,
    ingest_params_from_settings,
    job_status_is_active,
    live_progress_result,
)


def test_parse_iso_accepts_z_suffix():
    dt = _parse_iso("2026-07-02T12:00:00Z")
    assert dt.tzinfo is not None
    assert dt.year == 2026


def test_duration_sec_non_negative():
    start = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    end = datetime(2026, 7, 2, 12, 0, 5, tzinfo=timezone.utc).isoformat()
    assert _duration_sec(start, end) == 5.0


def test_parse_json_field():
    assert _parse_json_field(None, default={}) == {}
    assert _parse_json_field('{"a": 1}', default={}) == {"a": 1}
    assert _parse_json_field({"x": 1}, default={}) == {"x": 1}
    assert _parse_json_field("not-json", default=[]) == []


def test_ingest_params_from_payload():
    params = ingest_params_from_payload(
        {"zip_code": "95132", "distance": 500, "page_size": 250, "lead_id": "abc"},
        all_models=True,
        model_codes=[],
        make_slug="toyota",
    )
    assert params["zip_code"] == "95132"
    assert params["distance"] == 500
    assert params["page_size"] == 250
    assert params["make"] == "toyota"
    assert params["lead_id"] == "abc"


def test_ingest_params_from_payload_applies_make_defaults():
    toyota = ingest_params_from_payload({}, all_models=True, model_codes=[], make_slug="toyota")
    assert toyota["zip_code"] == "95132"
    assert toyota["distance"] == 500
    assert toyota["page_size"] == 250

    mazda = ingest_params_from_payload({}, all_models=True, model_codes=[], make_slug="mazda")
    assert mazda["zip_code"] == "95101"
    assert mazda["distance"] == 50
    assert mazda["page_size"] == 100
    assert mazda["nationwide"] is False

    mazda_nationwide = ingest_params_from_payload(
        {"nationwide": True}, all_models=True, model_codes=[], make_slug="mazda"
    )
    assert mazda_nationwide["nationwide"] is True


def test_geocode_params():
    params = geocode_params(limit=10, delay_sec=1.1, force=False, workers=4)
    assert params == {"limit": 10, "delay_sec": 1.1, "force": False, "workers": 4}


class _FakeSettings:
    zip_code = "95101"
    distance = 50
    page_size = 100
    series_code = None
    make_slug = "mazda"


def test_ingest_params_from_settings():
    params = ingest_params_from_settings(_FakeSettings(), all_models=True, model_codes=None)
    assert params["make"] == "mazda"
    assert params["zip_code"] == "95101"


def test_live_progress_result_strips_job_run_id():
    assert live_progress_result({"job_run_id": 9, "status": "running"}) == {"status": "running"}


def test_job_status_is_active():
    assert job_status_is_active("queued") is True
    assert job_status_is_active("running") is True
    assert job_status_is_active("completed") is False
    assert job_status_is_active("idle") is False
