"""Send-cage prohibited-claim FLOOR + profile EXTENSION (#6).

The hardcoded _PROHIBITED_CLAIM_RE floor always applies; a vertical may ADD patterns via the profile
slot `prohibited_claim_patterns`. The profile can only TIGHTEN the cage (add rejections), never weaken
it, and a malformed profile regex is skipped fail-safe (it must never crash or disable the cage).
"""
from __future__ import annotations

import pytest

from src.app.services.fulfillment import draft as D

_FOOTER = "this request does not constitute a purchase order"


def _body(extra: str) -> str:
    # a body that passes the footer check; `extra` carries the text under test
    return f"Hello, please send your quote. {extra}\n\n{_FOOTER}\nRegards, Procurement"


@pytest.fixture(autouse=True)
def _clear_cache():
    D.reset_prohibited_cache()
    yield
    D.reset_prohibited_cache()


def test_floor_applies_even_with_no_profile_patterns(monkeypatch):
    monkeypatch.setattr(D, "_profile_prohibited_patterns", lambda profile_id=None: [])
    # baseline floor still rejects a guarantee
    assert D.claim_safety_reason(_body("we guarantee the lowest price")) == "unsupported_or_binding_claim"
    # an otherwise-clean RFQ body is safe
    assert D.claim_safety_reason(_body("we look forward to your reply")) is None


def test_profile_extension_tightens_the_cage(monkeypatch):
    import re
    pats = [re.compile(r"\bbrand[- ]?new sealed\b", re.IGNORECASE)]
    monkeypatch.setattr(D, "_profile_prohibited_patterns", lambda profile_id=None: pats)
    # this phrase is NOT in the hardcoded floor, but the profile extension rejects it
    assert D.claim_safety_reason(_body("all units are brand new sealed")) == "unsupported_or_binding_claim"
    # a body that matches neither floor nor extension stays safe
    assert D.claim_safety_reason(_body("please confirm availability")) is None


def test_malformed_profile_regex_is_skipped_fail_safe(monkeypatch):
    # an unbalanced group is a bad regex — it must be skipped, the good one kept, no crash
    def fake_slot(slot, profile_id=None, default=None):
        return ["(unbalanced", r"\bcounterfeit\b"]

    monkeypatch.setattr("src.app.platform.store_profile.profile_slot", fake_slot)
    D.reset_prohibited_cache()
    pats = D._profile_prohibited_patterns()
    assert len(pats) == 1  # the good one compiled, the bad one skipped
    assert D.claim_safety_reason(_body("possibly counterfeit stock")) == "unsupported_or_binding_claim"
    assert D.claim_safety_reason(_body("genuine retail units")) is None  # floor + ext both clean -> safe


def test_real_electronics_profile_extends_the_floor(monkeypatch):
    # end-to-end against the REAL electronics profile slot (no monkeypatching of the patterns)
    monkeypatch.setenv("STORE_PROFILE_ID", "electronics")
    from src.app.platform import store_profile
    store_profile.reset_cache()
    D.reset_prohibited_cache()
    # "brand new sealed" / "100% genuine" are electronics extensions, not in the floor
    assert D.claim_safety_reason(_body("brand new sealed units")) == "unsupported_or_binding_claim"
    assert D.claim_safety_reason(_body("100% genuine product")) == "unsupported_or_binding_claim"
    # a normal RFQ ask remains sendable
    assert D.claim_safety_reason(_body("please share unit price and lead time")) is None
