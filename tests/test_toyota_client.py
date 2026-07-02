from vehicle_inventory.makes.toyota.client import _describe_locate_failure, _truncate_json


def test_truncate_json_short_payload():
    assert _truncate_json({"a": 1}) == '{"a":1}'


def test_truncate_json_long_payload():
    payload = {"items": list(range(500))}
    text = _truncate_json(payload, limit=40)
    assert "truncated" in text
    assert len(text) > 40


def test_describe_locate_failure_null_locate():
    payload = {"data": {"locateVehiclesByZip": None}}
    message = _describe_locate_failure(payload, page_no=3)
    assert "page 3" in message
    assert "null" in message


def test_describe_locate_failure_missing_data():
    message = _describe_locate_failure({}, page_no=1)
    assert "missing `data`" in message


def test_describe_locate_failure_unrecognized_payload():
    payload = {"data": {"locateVehiclesByZip": {"unexpected": True}}}
    message = _describe_locate_failure(payload, page_no=2)
    assert "unrecognized vehicle payload" in message
