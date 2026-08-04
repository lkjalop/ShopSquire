"""Phase 1d.3 — intent-aware cart swap. When the shopper swaps a product INTO the cart, does it
still meet the intent they expressed earlier? A SOFT advisory (never blocks): the fit verdict IS
the call-out (data-driven), the alternatives are the ranked closest — not brittle rules."""
from src.app.services.catalog_read_model import VariantView
from src.app.services.recommendation_core.fit import assess_intent_fit

# the shopper's remembered intent: a real discrete-GPU machine (the session's accepted constraint)
REQ = {"gpu_vram_gb": [(">=", 8)]}


def _v(sku, title, specs):
    return VariantView(sku=sku, title=title, price_cents=150000, specs=specs)


def test_swap_meets_intent_confirms():
    legion = _v("LEGION", "Lenovo Legion Slim", {"gpu_discrete": True, "gpu_vram_gb": 8})
    a = assess_intent_fit(legion, REQ)
    assert a["verdict"] == "meets" and a["advisory"] is False
    assert "good swap" in a["message"].lower()


def test_swap_fails_intent_soft_callout_with_alternatives():
    # the swap-in has too little GPU for what the shopper originally asked → soft call-out
    weak = _v("WEAK", "Lenovo IdeaPad", {"gpu_vram_gb": 4})
    closer = _v("SLIM", "Lenovo Legion Slim", {"gpu_discrete": True, "gpu_vram_gb": 8})   # meets
    a = assess_intent_fit(weak, REQ, alternatives=[weak, closer])
    assert a["verdict"] == "fails" and a["advisory"] is True
    assert "gpu_vram_gb" in a["message"]                 # names the missed intent key
    assert "want it anyway" in a["message"].lower()      # soft, never blocks
    alt_skus = [x["sku"] for x in a["alternatives"]]
    assert "SLIM" in alt_skus and "WEAK" not in alt_skus  # closer alt offered, not the candidate itself


def test_swap_unknown_is_cant_confirm_not_a_failure():
    mystery = _v("MYST", "Mystery Laptop", {})           # no GPU data → unknown, not a false fail
    a = assess_intent_fit(mystery, REQ)
    assert a["verdict"] == "unknown" and a["advisory"] is True
    assert "can't verify" in a["message"].lower()


def test_no_remembered_intent_no_opinion():
    v = _v("X", "Anything", {"gpu_vram_gb": 8})
    a = assess_intent_fit(v, {})
    assert a["verdict"] == "none" and a["advisory"] is False
