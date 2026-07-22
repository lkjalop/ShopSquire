import importlib.util
from pathlib import Path


MODULE = Path(__file__).resolve().parents[2] / "scripts" / "seed_products_from_txt.py"


def _module():
    spec = importlib.util.spec_from_file_location("seed_products_from_txt_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parser_uses_explicit_source_currency():
    parsed = _module().parse_product("Wacom Intuos Small\nPrice: $79", currency="AUD")
    assert parsed["price_cents"] == 7900
    assert parsed["currency"] == "AUD"
