from vehicle_inventory.makes.mazda.colors import resolve_exterior_color_hex


def test_resolve_exterior_color_hex_ingot_blue():
    assert resolve_exterior_color_hex("Ingot Blue Metallic") == "4d7fa6"


def test_resolve_exterior_color_hex_soul_red_crystal():
    assert resolve_exterior_color_hex("Soul Red Crystal Metallic") == "890000"


def test_resolve_exterior_color_hex_rhodium_white_metallic():
    assert resolve_exterior_color_hex("Rhodium White Metallic") == "FFFFFF"


def test_resolve_exterior_color_hex_unknown_returns_none():
    assert resolve_exterior_color_hex("Mystery Paint") is None
