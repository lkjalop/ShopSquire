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
    # profile-driven product narration: dims come from the StoreProfile slot, not hardcoded specs.
    "src/app/services/narration_tradeoff.py",
    # availability/fulfilment: stock + lead-time orchestration, vertical-blind (no product literals).
    "src/app/services/availability_agent.py",
    # negation/exclusion response filter: matches excluded terms against product DATA, no literals.
    "src/app/services/negation_filter.py",
    # escalation policy: risk/complexity → human-in-the-loop decision, vertical-blind signal math.
    "src/app/services/escalation_policy.py",
    # B2B intent: quantity + business-language → consumer/b2b/ambiguous/anomalous, vertical-blind.
    "src/app/services/b2b_intent.py",
    # LLM intent-planner fallback: prompt seeded from the profile vocab, no hardcoded verticals.
    "src/app/services/llm_planner.py",
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
    "src/app/adapters/external_research_httpx.py",
    # graduated from _PENDING_EXCISION 2026-06-20: entity NER patterns excised verbatim to
    # electronics.json `entity_*` slots; non-electronics verticals derive from their own data.
    "src/app/services/category_router.py",
    # graduated from _PENDING_EXCISION 2026-06-20: accessory FAMILY taxonomy excised verbatim to
    # electronics.json taxonomy slots; non-electronics verticals get UNK families (no bleed).
    "src/app/services/product_taxonomy.py",
    # graduated from _PENDING_EXCISION 2026-06-24 (NEW-2): the last spec literals in
    # _extract_hard_constraints (refresh/RAM/storage/weight/esports) excised to electronics.json
    # hard_constraint_rules / use_case_spec_implications / portable_weight_kg_max (parity-tested
    # byte-for-byte). use_case_patterns/portable_pattern already read from the profile.
    "src/app/services/query_decomposer.py",
    # attribution backbone: decision→conversion measurement loop, vertical-blind (speaks only
    # decision_id/trace_id/sku/uid_hash/value_cents/window — no product vocabulary).
    "src/app/services/attribution.py",
    # adaptive agent budgets: tier/risk/event-signal → per-agent tool+token budget, agent names
    # only (no product vocabulary). Extracted from orchestrator.
    "src/app/services/agent_budgets.py",
    # request-scoped bandit-arm carrier: an "arm" is an opaque label, zero product vocabulary.
    "src/app/services/bandit_context.py",
    # entity resolution: canonicalize brand/product/user → stable graph-node ids; alias DATA comes
    # from the profile, the normalize+lookup MECHANISM is vertical-blind.
    "src/app/services/entity_resolution.py",
    # hippograph projection + recall: build the in-memory graph from trace/conversion rows and
    # spread-activation recall, reward-weighted. Node math only — zero product vocabulary.
    "src/app/services/hippograph.py",
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
# category_router + product_taxonomy graduated 2026-06-20 (→ electronics.json slots, byte-identical).
#
# 2026-06-22 audit: the decision-path modules below carry KNOWN transitional electronics flavour and
# are NOT yet in _CORE_MODULES. Recorded here so NO NEW flavour can be added to them (the ratchet
# blocks growth) and every excision pass must lower the baseline toward 0 → graduation. Baselines are
# the EXACT distinct-flavour-token count today (recompute with _distinct_flavour_count before lowering).
# Excision targets (where the flavour should move):
#   recommend.py            → brand→canonical/alias maps, brand_price_floors, GPU/gaming token lists,
#                             refresh-rate logic, SQL brand literals → electronics.json slots / the
#                             recommend_candidate_classify electronics adapter (LANE D extraction).
#   recommend_image_hints   → _SUPPORTED_IMAGE_BRAND_HINTS brand catalog → electronics.json image slot.
#   recommend_budget_advisor→ persona labels + gpu/spec vocab → electronics.json (Phase-2, noted in module).
#   recommend_nqe_helpers / query_decomposer / *_agent / *_parsing / use_case_advisor / vision_stage
#                           → spec-key + brand/gpu literals → profile spec/keyword slots.
_PENDING_EXCISION: dict[str, int] = {
    "src/app/routers/recommend.py": 14,
    "src/app/routers/chat.py": 13,  # chat router: clarify-text + brand-alias literals → profile slots
    "src/app/services/recommend_image_hints.py": 13,
    "src/app/services/recommend_budget_advisor.py": 4,
    "src/app/services/recommend_nqe_helpers.py": 3,
    # query_decomposer.py GRADUATED to _CORE_MODULES 2026-06-24 (NEW-2) — spec logic excised to profile.
    "src/app/services/product_ranking_agent.py": 2,
    "src/app/services/recommend_vision_stage.py": 2,
    "src/app/services/recommend_budget_parsing.py": 1,
    "src/app/services/use_case_advisor.py": 1,
    "src/app/services/product_identity_agent.py": 1,
    "src/app/services/product_classifier.py": 1,
}


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
