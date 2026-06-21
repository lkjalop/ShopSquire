"""No-flavour-in-core lint — the mechanical boundary guard (agnostic core).

CORE modules are vertical-blind MECHANISMS. Laptop/electronics FLAVOUR (brand names, GPU
models, refresh-rate, etc.) must live in config/store_profiles/*.json, never in core code.
This test greps the core modules for laptop literals and FAILS the build if any appear —
so flavour bleeding into core is impossible to merge, not just discouraged.

As each suggest()/helper stage is extracted into a core module, ADD it to _CORE_MODULES.
A module that still carries transitional fallback flavour (query_decomposer,
product_classifier) is intentionally NOT listed until its flavour is fully excised.

Two tiers:
  * _CORE_MODULES         — ZERO tolerance (fully excised, vertical-blind).
  * _PENDING_EXCISION     — RATCHET: decision-path modules with KNOWN transitional flavour
                            whose data-vs-profile taxonomies don't yet have parity (so a
                            blind swap would regress electronics). Their distinct-flavour-token
                            count is recorded and may only move DOWN. New flavour cannot be
                            added, and every excision pass lowers the baseline toward zero —
                            at which point the module graduates to _CORE_MODULES.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# Modules that are CORE (agnostic mechanism) and must contain zero laptop flavour.
_CORE_MODULES = [
    "src/app/services/recommend_response_finalizer.py",
    "src/app/platform/store_profile.py",
    "src/app/policy/execution_gate.py",
    "src/app/services/answer_composer.py",
    "src/app/services/candidate_retriever.py",
    "src/app/services/recommend_pipeline.py",
    "src/app/services/commerce_source_status.py",
    "src/app/services/checkout_handoff.py",
    "src/app/services/recommend_context.py",
    "src/app/services/upsell_engine.py",
    "src/app/services/query_understanding.py",
    "src/app/platform/tenant_registry.py",
    "src/app/services/recommend_narration_stage.py",
    "src/app/services/suggest_context.py",
    "src/app/services/supplier_communication.py",
    # graduated from _PENDING_EXCISION 2026-06-20: entity NER patterns excised verbatim to
    # electronics.json `entity_*` slots; non-electronics verticals derive from their own data.
    "src/app/services/category_router.py",
    # graduated from _PENDING_EXCISION 2026-06-20: accessory FAMILY taxonomy excised verbatim to
    # electronics.json taxonomy slots; non-electronics verticals get UNK families (no bleed).
    "src/app/services/product_taxonomy.py",
]

# Unambiguous electronics/laptop flavour literals (brand models, GPU prefixes, display).
# Deliberately specific — avoids false positives on generic words.
_FLAVOUR_RE = re.compile(
    r"\b(rtx|gtx|vivobook|macbook|thinkpad|zenbook|ideapad|alienware|aspire|"
    r"predator|omen|spectre|pavilion|victus|katana|legion|"
    r"gaming laptop|refresh_hz|\d{3} ?hz|tgp)\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("module", _CORE_MODULES)
def test_core_module_has_no_laptop_flavour(module):
    p = Path(module)
    assert p.exists(), f"core module missing: {module}"
    text = p.read_text(encoding="utf-8", errors="replace")
    hits = sorted({m.group(0).lower() for m in _FLAVOUR_RE.finditer(text)})
    assert not hits, (
        f"{module} contains laptop/electronics FLAVOUR {hits} — move it to a "
        f"StoreProfile (config/store_profiles/*.json). Core must be vertical-blind."
    )


def test_lint_actually_detects_flavour():
    # Guard the guard: the regex must catch a known flavour literal.
    assert _FLAVOUR_RE.search("the RTX 4070 vivobook gaming laptop at 240hz")
    assert not _FLAVOUR_RE.search("a generic product recommendation pipeline")


# ── Pending-excision RATCHET ─────────────────────────────────────────
# Decision-path modules with KNOWN transitional electronics flavour: cross-vertical in INTENT
# but still hardcoding electronics literals. Their distinct flavour-token count is recorded and
# may only move DOWN (new flavour cannot be added; every excision pass lowers the baseline). At
# 0 the module graduates to _CORE_MODULES (zero-tolerance).
#
# Currently EMPTY — both initial entries graduated 2026-06-20:
#   * category_router  → entity_* slots in electronics.json (electronics byte-identical, no bleed)
#   * product_taxonomy → accessory-taxonomy slots in electronics.json (electronics byte-identical)
# Add a module here when a new transitional-flavour island is identified (e.g. when excising a
# decision-path module whose profile-slot parity can't be built in the same pass).
_PENDING_EXCISION: dict[str, int] = {}


def _distinct_flavour_count(module: str) -> int:
    text = Path(module).read_text(encoding="utf-8", errors="replace")
    return len({m.group(0).lower() for m in _FLAVOUR_RE.finditer(text)})


@pytest.mark.parametrize("module,limit", sorted(_PENDING_EXCISION.items()))
def test_pending_excision_flavour_does_not_grow(module, limit):
    p = Path(module)
    assert p.exists(), f"pending-excision module missing: {module}"
    n = _distinct_flavour_count(module)
    assert n <= limit, (
        f"{module} now has {n} distinct flavour tokens (baseline {limit}) — new electronics "
        f"flavour was added to a cross-vertical module. Move it to a StoreProfile slot instead. "
        f"Do NOT raise the baseline."
    )
    assert n == limit, (
        f"{module} flavour dropped to {n} (baseline {limit}) — good, now LOWER the baseline in "
        f"_PENDING_EXCISION to {n} to lock the gain (ratchet down). At 0, graduate it to _CORE_MODULES."
    )
