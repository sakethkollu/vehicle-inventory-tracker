from vehicle_inventory.makes.mazda.stage import resolve_mazda_allocation_stage


def test_resolve_mazda_allocation_stage_in_transit():
    code, label = resolve_mazda_allocation_stage(vehicle_location="01")
    assert code == "01"
    assert label == "In Transit"


def test_resolve_mazda_allocation_stage_at_dealership():
    code, label = resolve_mazda_allocation_stage(vehicle_location="2")
    assert code == "02"
    assert label == "At Dealership"


def test_resolve_mazda_allocation_stage_from_detail_location():
    code, label = resolve_mazda_allocation_stage(detail_location={"Code": "02"})
    assert code == "02"
    assert label == "At Dealership"
