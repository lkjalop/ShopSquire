"""Phase X (2026-07-09): server-side swap parsing + deficit-reorder routing."""
from __future__ import annotations

from src.app.services.intent_decomposer import decompose_turn
from src.app.routers.chat import _is_deficit_reorder_query, _strip_deficit_observation, _classify_turn_intent


# ── swap (the one cart intent with no parser) ──
def test_swap_becomes_remove_plus_add():
    t = decompose_turn("swap the dell for a lenovo", has_prior_selection=True).as_dict()
    assert {"ref": "dell", "new_qty": 0} in t["amendments"]
    assert {"category": "lenovo", "qty": None} in t["new_lines"]
    assert any("swap" in n for n in t["notes"])


def test_swap_variants():
    for q, obj, repl in [("replace the HP with an Asus", "hp", "asus"),
                         ("change the monitor to a Dell", "monitor", "dell")]:
        t = decompose_turn(q, has_prior_selection=True).as_dict()
        assert any(a["ref"].lower() == obj and a["new_qty"] == 0 for a in t["amendments"]), q
        assert any(n["category"].lower() == repl for n in t["new_lines"]), q


def test_swap_without_cart_is_honest_noop():
    t = decompose_turn("swap the dell for a lenovo", has_prior_selection=False).as_dict()
    assert not t["amendments"] and not t["new_lines"]
    assert any("ignored" in n for n in t["notes"])


def test_swap_does_not_false_fire_on_plain_add():
    t = decompose_turn("i need 15 laptops", has_prior_selection=True).as_dict()
    assert not any("swap" in n for n in t["notes"])


# ── deficit-reorder routing ──
def test_deficit_detector_precision():
    assert _is_deficit_reorder_query("i need 50 dell laptops but you only have a few in stock, ok waiting for a reorder?")
    assert _is_deficit_reorder_query("30 laptops but limited stock, ok to wait?")
    assert not _is_deficit_reorder_query("gaming laptop under 2000 only 16gb ram")
    assert not _is_deficit_reorder_query("laptop with only 8gb ram")


def test_deficit_routes_to_search_not_filter():
    # "only " would otherwise trip the FILTER branch and zero retrieval
    assert _classify_turn_intent("i need 50 dell laptops but you only have a few in stock, ok to wait?") == "SEARCH"


def test_strip_keeps_core_bulk_request():
    assert _strip_deficit_observation(
        "i need 50 dell laptops but you only have a few in stock, am i ok waiting for a reorder?"
    ) == "i need 50 dell laptops"
    # a plain bulk request is never truncated
    assert _strip_deficit_observation("i need 50 dell laptops") == "i need 50 dell laptops"
