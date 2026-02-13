from src.app.policy.vertical_pack import load_vertical_pack, list_vertical_packs


def test_vertical_pack_electronics_loads():
    p = load_vertical_pack("electronics")
    assert p.id == "electronics"
    assert "required_views" in p.__dict__
    assert isinstance(p.roi_allowlist, list)
    assert "product" in p.roi_allowlist


def test_vertical_pack_list_contains_electronics():
    packs = list_vertical_packs()
    assert "electronics" in packs

