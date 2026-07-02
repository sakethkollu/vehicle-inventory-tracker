"""Regression tests: facet lists must not collapse when one value is selected."""

from __future__ import annotations

import pytest

import os
import unittest

from vehicle_inventory.db.backend import open_db_connection
from vehicle_inventory.api.filters import FilterContext, build_filters_payload

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


@pytest.mark.integration
@unittest.skipUnless(
    DATABASE_URL.startswith("mysql"),
    "DATABASE_URL must point at MySQL with ingested data for facet regression tests",
)
class FilterFacetRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = open_db_connection(DATABASE_URL)
        base = build_filters_payload(cls.conn, FilterContext(active_only=True))
        if not base["series"]:
            raise unittest.SkipTest("no inventory data in database")
        cls.base_counts = {key: len(base[key]) for key in (
            "series",
            "models",
            "exterior_colors",
            "interior_colors",
            "drivetrains",
            "stages",
            "options",
            "dealers",
            "states",
        )}
        cls.samples = {
            "series": base["series"][0]["series_code"],
            "models": base["models"][0]["value"],
            "exterior_colors": base["exterior_colors"][0]["value"],
            "interior_colors": base["interior_colors"][0]["value"],
            "drivetrains": base["drivetrains"][0]["value"],
            "stages": base["stages"][0]["value"],
            "options": base["options"][0]["value"],
            "dealers": base["dealers"][0]["value"],
            "states": base["states"][0]["value"],
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def _assert_facet_not_collapsed(self, ctx: FilterContext, facet_key: str) -> None:
        payload = build_filters_payload(self.conn, ctx)
        base_count = self.base_counts[facet_key]
        actual_count = len(payload[facet_key])
        self.assertGreaterEqual(
            actual_count,
            max(base_count - 2, 1),
            msg=f"{facet_key} collapsed from {base_count} to {actual_count}",
        )

    def test_series_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(series_codes=[self.samples["series"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "series")

    def test_models_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(model_values=[self.samples["models"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "models")

    def test_exterior_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(exterior_colors=[self.samples["exterior_colors"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "exterior_colors")

    def test_interior_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(interior_colors=[self.samples["interior_colors"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "interior_colors")

    def test_drivetrain_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(drivetrain_codes=[self.samples["drivetrains"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "drivetrains")

    def test_stage_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(stage_codes=[self.samples["stages"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "stages")

    def test_options_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(option_codes=[self.samples["options"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "options")

    def test_dealers_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(dealer_codes=[self.samples["dealers"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "dealers")

    def test_states_not_collapsed_when_one_selected(self) -> None:
        ctx = FilterContext(state_codes=[self.samples["states"]], active_only=True)
        self._assert_facet_not_collapsed(ctx, "states")

    def test_multi_series_and_model_selection(self) -> None:
        series = self.samples["series"]
        series_payload = build_filters_payload(
            self.conn,
            FilterContext(series_codes=[series], active_only=True),
        )
        model = series_payload["models"][0]["value"]
        ctx = FilterContext(series_codes=[series], model_values=[model], active_only=True)
        payload = build_filters_payload(self.conn, ctx)
        self.assertGreaterEqual(len(payload["series"]), self.base_counts["series"] - 2)
        self.assertEqual(len(payload["models"]), len(series_payload["models"]))
        self.assertIn(model, {row["value"] for row in payload["models"]})


if __name__ == "__main__":
    unittest.main()
