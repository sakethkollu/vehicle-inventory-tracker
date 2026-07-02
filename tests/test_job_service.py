from unittest.mock import MagicMock

from vehicle_inventory.jobs.service import JobService


class _FakeMake:
    slug = "mazda"
    redis_prefix = "vit:mazda"
    database_url = "mysql+pymysql://vit:pass@localhost/mazda_inventory"


class _FakeSettings:
    use_redis_jobs = True
    redis_url = "redis://localhost:6379/0"
    schema_path = None

    def __eq__(self, other):
        return isinstance(other, _FakeSettings)


def _service() -> JobService:
    service = JobService.__new__(JobService)
    service.make = _FakeMake()
    service.settings = _FakeSettings()
    return service


def test_resolve_live_ingest_job_type_from_live_payload():
    service = _service()
    store = MagicMock()
    live = {"status": "running", "job_type": "dealer_vehicle_refresh", "job_run_id": 15}
    assert service._resolve_live_ingest_job_type(live, store) == "dealer_vehicle_refresh"
    store.get.assert_not_called()


def test_resolve_live_ingest_job_type_from_job_run():
    service = _service()
    store = MagicMock()
    store.get.return_value = {"job_type": "dealer_vehicle_refresh"}
    live = {"status": "running", "job_run_id": 15}
    assert service._resolve_live_ingest_job_type(live, store) == "dealer_vehicle_refresh"
    store.get.assert_called_once_with(15)


def test_resolve_live_ingest_job_type_defaults_to_ingest():
    service = _service()
    store = MagicMock()
    store.get.return_value = None
    live = {"status": "running", "job_run_id": 99}
    assert service._resolve_live_ingest_job_type(live, store) == "ingest"
