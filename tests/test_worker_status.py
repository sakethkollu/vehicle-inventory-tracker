from vehicle_inventory.jobs.worker_status import parse_rq_job_id


def test_parse_rq_job_id_ingest():
    parsed = parse_rq_job_id("mazda-ingest-42")
    assert parsed == {"make": "mazda", "job_type": "ingest", "job_run_id": 42}


def test_parse_rq_job_id_geocode():
    parsed = parse_rq_job_id("toyota-geocode-7")
    assert parsed == {"make": "toyota", "job_type": "geocode", "job_run_id": 7}


def test_parse_rq_job_id_dealer_refresh():
    parsed = parse_rq_job_id("mazda-dealer-refresh-15")
    assert parsed == {
        "make": "mazda",
        "job_type": "dealer_vehicle_refresh",
        "job_run_id": 15,
    }


def test_parse_rq_job_id_unknown():
    assert parse_rq_job_id("custom-job") == {}
