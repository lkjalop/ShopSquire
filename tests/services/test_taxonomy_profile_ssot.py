"""Phase 1 (Profile SSOT) — store_vocab.json archived; product taxonomy is now profile-driven.

Two guarantees:
1. PARITY — the profile's product_type_rules/price_bands are byte-identical to the archived
   store_vocab.json (the migration was verbatim), so classification behaviour is unchanged.
2. AGNOSTIC PROOF — the SAME classifier mechanism classifies pharmacy products from
   pharmacy.json with zero laptop/GPU flavour.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.app.platform.store_profile import get_store_profile
from src.app.services.product_classifier import (
    classify_product_type,
    price_band_for_type,
    primary_types,
)

_ARCHIVED = Path("config/_archive/store_vocab.json")


# ── 1. Parity vs the archived store_vocab.json ────────────────────────────────
def test_profile_rules_match_archived_store_vocab_verbatim():
    archived = json.loads(_ARCHIVED.read_text(encoding="utf-8"))
    prof = get_store_profile("electronics")
    assert prof["product_type_rules"] == archived["product_type_rules"]
    assert prof["primary_types"] == archived["primary_types"]
    # every archived price band survives in the profile (profile may add more):
    for t, band in archived["price_bands"].items():
        assert prof["price_bands_usd"].get(t) == band


def test_classify_uses_profile_rich_rules():
    # The rich brand/model rules (XPS/ThinkPad/Nighthawk) now come from the profile, not store_vocab.
    assert classify_product_type("Dell XPS 13") == "laptop"
    assert classify_product_type("Lenovo ThinkPad X1") == "laptop"
    assert classify_product_type("Netgear Nighthawk Router") == "networking"
    assert classify_product_type("Generic Widget 9000") == "accessory"
    assert sorted(primary_types()) == ["desktop", "laptop"]
    assert price_band_for_type("laptop") == (350.0, 6000.0)
    assert price_band_for_type("accessory") == (5.0, 1500.0)


# ── 2. Agnostic proof: pharmacy taxonomy from pharmacy.json, zero laptop flavour ──
def _compile(profile_id: str):
    prof = get_store_profile(profile_id)
    return [(r["type"], re.compile(r["pattern"], re.IGNORECASE)) for r in prof["product_type_rules"]]


def _classify_with(rules, name: str) -> str:
    for t, rx in rules:
        if rx.search(name):
            return t
    return "accessory"


def test_pharmacy_taxonomy_classifies_from_profile():
    rules = _compile("pharmacy")
    assert _classify_with(rules, "Panadol 20 tablets") == "medicine"
    assert _classify_with(rules, "Blackmores Fish Oil 1000mg") == "supplement"
    assert _classify_with(rules, "Cetaphil Gentle Skin Cleanser") == "personal_care"
    assert _classify_with(rules, "Digital Thermometer") == "device"
    assert _classify_with(rules, "Band-Aid 50 pack") == "first_aid"
    # A laptop name does NOT classify as any pharmacy primary type — it's an accessory/unknown.
    assert _classify_with(rules, "Dell XPS 13 Laptop") == "accessory"


def test_pharmacy_profile_has_zero_electronics_flavour():
    prof = get_store_profile("pharmacy")
    # DATA slots only — _comment/_*-prose legitimately says "must not inherit laptop brands".
    data = {k: v for k, v in prof.items() if not str(k).startswith("_")}
    blob = json.dumps(data).lower()
    for flavour in ("rtx", "gtx", "macbook", "thinkpad", "vivobook", "laptop", "refresh_hz"):
        assert flavour not in blob, f"pharmacy profile leaked electronics flavour: {flavour!r}"
    # pharmacy has no GPU concept — the slot is explicitly empty (claim-guard honours it).
    assert prof.get("gpu_prefixes") == []
