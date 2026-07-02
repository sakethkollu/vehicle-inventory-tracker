import pytest

import os
import unittest

from vehicle_inventory.db.backend import open_db_connection
from vehicle_inventory.jobs.runs import JobRunStore, ensure_job_runs_table

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


@pytest.mark.integration
@unittest.skipUnless(
    DATABASE_URL.startswith("mysql"),
    "DATABASE_URL must point at MySQL for integration tests",
)
class JobRunsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = JobRunStore(DATABASE_URL)
        conn = open_db_connection(DATABASE_URL)
        try:
            ensure_job_runs_table(conn)
            conn.commit()
        finally:
            conn.close()

    def test_start_finish_and_list(self) -> None:
        job_run_id = self.store.start(
            "ingest",
            {"zip_code": "95132", "distance": 500, "all_models": True, "model_codes": []},
            trigger_source="ui",
        )
        self.store.finish(
            job_run_id,
            "completed",
            result={"vehicles_persisted": 1200, "completed_models": ["1852", "1853"]},
            message="Ingest complete.",
        )
        run = self.store.get(job_run_id)
        assert run is not None
        self.assertEqual(run["job_type"], "ingest")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["params"]["zip_code"], "95132")
        self.assertEqual(run["result"]["vehicles_persisted"], 1200)
        self.assertIsNotNone(run["duration_sec"])
        self.assertGreaterEqual(run["duration_sec"], 0)

        runs = self.store.list_runs(limit=10)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["job_run_id"], job_run_id)

    def test_summary_groups_by_type(self) -> None:
        ingest_id = self.store.start("ingest", {"zip_code": "95132"}, trigger_source="ui")
        self.store.finish(ingest_id, "completed", result={"vehicles_persisted": 10})
        geocode_id = self.store.start(
            "geocode",
            {"limit": None, "workers": 8, "force": False, "delay_sec": 1.1},
            trigger_source="auto",
        )
        self.store.finish(geocode_id, "failed", error="network error")

        summary = self.store.summary(since_days=30)
        self.assertEqual(summary["ingest"]["count"], 1)
        self.assertEqual(summary["ingest"]["completed"], 1)
        self.assertEqual(summary["geocode"]["count"], 1)
        self.assertEqual(summary["geocode"]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
