"""P1 characterization (golden) snapshots — pin the EXACT current behaviour of the
answer-shaping helpers BEFORE they move into recommend_response_finalizer.py.

These import the helpers from their CURRENT location (recommend.py). After the move,
recommend.py keeps thin re-export shims, so these same tests must still pass with
byte-identical output — that is the parity gate for the refactor (the "ordering trap"
guard). If any assertion here changes, the move changed behaviour: stop and fix.
"""
from __future__ import annotations

import pytest

R = pytest.importorskip("src.app.routers.recommend")


# ── pure helpers (move directly) ──────────────────────────────────────────────

def test_char_ensure_result_prices_from_cents():
    p = {"results": [{"sku": "A", "price_cents": 112400}, {"sku": "B", "price_cents": 21900}]}
    out = R._ensure_result_prices(p)
    assert out["results"][0]["price"] == 1124
    assert out["results"][1]["price"] == 219


def test_char_ensure_result_prices_keeps_existing_price():
    p = {"results": [{"sku": "A", "price": 999, "price_cents": 112400}]}
    out = R._ensure_result_prices(p)
    assert out["results"][0]["price"] == 999  # existing price not overwritten


def test_currency_guard_prunes_every_repeated_product_projection():
    from src.app.services.recommend_response_finalizer import enforce_response_currency

    usd = {"sku": "USD-1", "name": "USD laptop", "price": 1200, "currency": "USD"}
    aud = {"sku": "AUD-1", "name": "AUD laptop", "price": 1200, "currency": "AUD"}
    payload = {
        "results": [usd.copy(), aud.copy()],
        "products": [usd.copy(), aud.copy()],
        "right_panel": {"anchor_sections": [{
            "count": 2,
            "top_products": [{"sku": "USD-1"}, {"sku": "AUD-1"}],
        }]},
        "device_lanes": [{
            "count": 2,
            "products": [{"sku": "USD-1"}, {"sku": "AUD-1"}],
        }],
    }

    out = enforce_response_currency(payload, "USD")

    assert [item["sku"] for item in out["results"]] == ["USD-1"]
    assert [item["sku"] for item in out["products"]] == ["USD-1"]
    assert out["right_panel"]["anchor_sections"][0]["top_products"] == [{"sku": "USD-1"}]
    assert out["right_panel"]["anchor_sections"][0]["count"] == 1
    assert out["device_lanes"][0]["products"] == [{"sku": "USD-1"}]
    assert out["currency_policy"]["excluded_mismatched"] == 2


def test_currency_guard_prunes_nested_buckets_when_root_slate_is_already_empty():
    from src.app.services.recommend_response_finalizer import enforce_response_currency

    payload = {
        "results": [],
        "products": [],
        "price_buckets": {"within_budget": [
            {"sku": "USD-1", "currency": "USD", "price": 1200},
        ]},
    }
    out = enforce_response_currency(payload, "AUD")
    assert out["price_buckets"]["within_budget"] == []
    assert out["currency_policy"]["excluded_mismatched"] == 1


def test_char_recovery_answer_exact_string():
    msg = R._recovery_answer({"budget_max": 1400, "brands": ["asus"]})
    assert msg == (
        "No in-stock ASUS match under $1,400 right now. "
        "You can raise your budget, allow other brands, or I can show the "
        "nearest in-stock options."
    )


def test_char_dereference_labels():
    p = {"assistant_message": "The [1] beats [2].",
         "results": [{"name": "MSI Katana 15"}, {"name": "Dell G15"}]}
    assert R._dereference_product_labels(p)["assistant_message"] == "The MSI Katana 15 beats Dell G15."


def test_char_demote_off_category_drops_accessory_when_primary_present():
    results = [{"name": "ASUS Vivobook Laptop"}, {"name": "TP-Link Wi-Fi Range Extender"}]
    out = R._demote_off_category(results, "laptop for uni")
    assert [r["name"] for r in out] == ["ASUS Vivobook Laptop"]


def test_char_annotate_price_integrity_quarantines_poisoned():
    p = {"results": [
        {"sku": "L1", "name": "Dell XPS 15 Laptop", "price": 45, "price_cents": 4500},
        {"sku": "L2", "name": "Lenovo IdeaPad Laptop", "price": 1124, "price_cents": 112400},
    ]}
    out = R._annotate_type_and_price_integrity(p)
    assert [r["sku"] for r in out["results"]] == ["L2"]  # poisoned $45 laptop removed
    di = out.get("data_integrity") or {}
    assert di.get("quarantined") is True
    assert any(f["sku"] == "L1" and f["anomaly"] == "underpriced" for f in di.get("price_anomalies", []))


# ── security challenge (move; gated by COMMERCE_COMPOSER) ──────────────────────

def test_char_build_security_challenge_text_qr():
    p = {"safe_image_hints": {"unsafe_flags": {"qr_prompt_injection": True}}}
    txt = R._build_security_challenge_text(p)
    assert txt and "QR" in txt and "http" not in txt.lower()


def test_char_maybe_apply_security_challenge_prefixes(monkeypatch):
    monkeypatch.setenv("COMMERCE_COMPOSER", "1")
    p = {"assistant_message": "Here are 3 laptops.",
         "safe_image_hints": {"unsafe_flags": {"steg_suspicious": True}}}
    out = R._maybe_apply_security_challenge(p)
    assert out["assistant_message"].startswith("⚠️")
    assert "steganography" in out["assistant_message"].lower()
    assert "Here are 3 laptops." in out["assistant_message"]


def test_char_maybe_apply_security_challenge_noop_when_clean(monkeypatch):
    monkeypatch.setenv("COMMERCE_COMPOSER", "1")
    p = {"assistant_message": "Here are 3 laptops.", "safe_image_hints": {"unsafe_flags": {}}}
    out = R._maybe_apply_security_challenge(p)
    assert out["assistant_message"] == "Here are 3 laptops."  # no flag -> unchanged


def test_char_finalize_answer_never_empty():
    out = R._finalize_answer({"constraints_used": {"budget_max": 400, "brands": ["asus"]}})
    assert out["assistant_message"].strip()
    assert "asus" in out["assistant_message"].lower()
