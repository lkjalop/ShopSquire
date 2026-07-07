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
    # GRADUATED 2026-07-07 (baseline 4 -> 0): capability classes/verdicts, persona labels, spec-strength
    # tokens, brand fallbacks, budget-floor hints and step-up spec all moved to StoreProfile slots —
    # the advisor now reads named fields + profile vocabulary only.
    "src/app/services/recommend_budget_advisor.py",
    # ENROLLED 2026-07-07 while clean (P/R-wave modules — time math, policy windows, ledger, evidence
    # orchestration: mechanisms only, no product vocabulary).
    "src/app/services/evidence_orchestrator.py",
    "src/app/services/claim_policy.py",
    "src/app/services/cart_ttl.py",
    "src/app/services/retention_sweeper.py",
    "src/app/services/refund_requests.py",
    # challenge-defense justification (N4): walks <field>_min KB keys vs specs[field] — all words
    # come from use_case_kb.json + the product row; mechanism only.
    "src/app/services/recommend_justification.py",
    "src/app/services/recommend_response_finalizer.py",
    "src/app/platform/store_profile.py",
    "src/app/policy/execution_gate.py",
    "src/app/services/answer_composer.py",
    "src/app/services/candidate_retriever.py",
    # profile-driven product narration: dims come from the StoreProfile slot, not hardcoded specs.
    "src/app/services/narration_tradeoff.py",
    # availability/fulfilment: stock + lead-time orchestration, vertical-blind (no product literals).
    "src/app/services/availability_agent.py",
    # multi-location availability + transfer feasibility: per-(sku,location) stock + transfer plan,
    # pure qty/location math — no product vocabulary.
    "src/app/services/multi_location_availability.py",
    # substitute generator: same-category in-budget alternatives ranked by PROFILE attributes (opaque
    # category/brand/specs DATA columns), no hardcoded product specs.
    "src/app/services/substitute_generator.py",
    # bulk alternatives assembler: orders buyer choices (partial/transfer/substitute/source/reduce) from
    # gathered facts, pure shaping — opaque sku/location/qty, generic strings, no product vocabulary.
    "src/app/services/bulk_alternatives.py",
    # inventory query service: injection-guarded direct stock lookups, opaque sku/qty — no product vocab.
    "src/app/services/inventory_query_service.py",
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
    # append-only payment ledger: order/intent ids + cents + event kinds only — no product
    # vocabulary. The governed refund two-step folds over these events.
    "src/app/services/payment_ledger.py",
    # outbound-DLP quarantine + human-release queue: opaque subject/body/dlp findings, owner-gated —
    # no product vocabulary.
    "src/app/services/outbound_dlp_quarantine.py",
    # shipping-address validation: format/postcode plausibility, ISO country→regex reference data —
    # no product vocabulary.
    "src/app/services/address_validation.py",
    # unified customer purchases + tracking read model: unions consumer orders + procurement cases;
    # order/case ids + cents + opaque statuses only — no product vocabulary.
    "src/app/services/account_purchases.py",
    # DMARC aggregate-report parsing + BEC heuristics (extracted from email_security): XML/zip parse +
    # SPF/DKIM counts + generic risky-word/homograph heuristics — no product vocabulary.
    "src/app/security/email_dmarc.py",
    # email forensics snapshots (extracted from email_security): attachment/sender/baseline/visual
    # pure builders over the email dict — opaque domains/attachments, no product vocabulary.
    "src/app/security/email_forensics_snapshots.py",
    # email finding normalization/ranking/compliance-mapping (extracted from email_security): pure
    # over finding dicts + control-registry lookup — opaque finding types, no product vocabulary.
    "src/app/security/email_findings.py",
    # email business-bundle + drilldown + structured-finding decoration (extracted from
    # email_security): composes email_findings helpers over finding dicts — no product vocabulary.
    "src/app/security/email_business_bundle.py",
    # email action policy (extracted from email_security): findings → bounded enforceable action
    # policy; opaque action names, no product vocabulary.
    "src/app/security/email_action_policy.py",
    # email structured-findings builder + pre-agent-gate + agent-runs audit (extracted from
    # email_security): composes finding helpers + passive-payload classifier — no product vocabulary.
    "src/app/security/email_structured_findings.py",
    # fast-path catalog scorer + candidate assembly: category boost is query-anchored against the
    # profile's category_keywords groups; brands from the profile — no product vocabulary.
    "src/app/services/catalog_scoring.py",
    # Dispatch_Agent: governed buyer-facing dispatch (propose → threshold-gated human approval →
    # execute); carrier labels + cents + profile delivery_policy only — no product vocabulary.
    "src/app/services/dispatch_agent.py",
    # clarify-turn payload builders: support copy read from the profile support_playbooks slot,
    # core carries only a vertical-neutral default — no product vocabulary.
    "src/app/services/recommend_clarify_payloads.py",
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
    # DB-backed hippograph projection: queries the agnostic trace/conversion tables, no product
    # vocabulary (brand aliases come from the profile).
    "src/app/services/hippograph_db.py",
    # hippograph feedback injection: reward-weighted recall for the current turn (advisory-OFF),
    # node math + ids only — zero product vocabulary.
    "src/app/services/hippograph_feedback.py",
    # market signal envelope + ingestion (Module 1): normalize+reliability over opaque signals;
    # signal_type/source are labels, payload is opaque — zero product vocabulary.
    "src/app/services/market_signal.py",
    # market signal source adapters: map orders/conversion/search rows → envelope; opaque payloads,
    # no product vocabulary.
    "src/app/services/market_signal_adapters.py",
    # market analysis engine (M3): market_signal → typed findings via deterministic detectors;
    # finding_type/entity_ref/evidence are opaque — no product vocabulary.
    "src/app/services/market_analysis.py",
    # market digest (M3 summarization): findings → operator brief; deterministic facts, flag-gated
    # LLM only rewrites wording; advisory-only — finding types/entities are opaque labels.
    "src/app/services/market_digest.py",
    # experiment + rollback framework (M6b): assignment/uplift/anti-Goodhart decision math; metrics
    # and variants are opaque labels — no product vocabulary.
    "src/app/services/experiments.py",
    # reversible ranking nudge: bounded additive score boost for treatment users, sku+score only —
    # no product vocabulary.
    "src/app/services/ranking_nudge.py",
    # experiment evaluation runtime: per-variant uplift → decide → auto-revert; opaque metrics —
    # no product vocabulary.
    "src/app/services/experiment_eval.py",
    # experiment operator console: promote/observe/evaluate/revert levers, opaque experiment/variant —
    # no product vocabulary.
    "src/app/services/experiment_console.py",
    # market intelligence agent: read-only context gatherer (recall + gated findings), opaque —
    # no product vocabulary.
    "src/app/services/market_intelligence_agent.py",
    # recommend intelligence stage: capture · market-intel · nudge orchestration, opaque state —
    # no product vocabulary.
    "src/app/services/recommend_intelligence_stage.py",
    # human-correction learning: signed feedback envelope + projection, opaque types/entities —
    # no product vocabulary.
    "src/app/services/human_feedback.py",
    # typed shadow actions: findings → log-only proposals, opaque action/target — no product vocabulary.
    "src/app/services/shadow_actions.py",
    # contact-frequency governance: consent/frequency/region gate, opaque channel/campaign —
    # no product vocabulary.
    "src/app/services/contact_governance.py",
    # experiment operationalization: guardrails/heartbeat/stale-detect/drill, opaque metrics —
    # no product vocabulary.
    "src/app/services/experiment_ops.py",
    # controlled template phrasing: tone-only message variants, opaque string — no product vocabulary.
    "src/app/services/template_phrasing.py",
    # adaptive-action gate: confidence/authz/audit chokepoint, opaque action types — no product vocabulary.
    "src/app/services/adaptive_action_gate.py",
    # offers/campaigns governance: readiness gate + governed dispatch planner, opaque channel/offer —
    # no product vocabulary.
    "src/app/services/campaign_governance.py",
    # fulfilment domain: bounded-autonomy state machine + actor guards, opaque states/events —
    # no product vocabulary, no channel detail.
    "src/app/services/fulfillment/domain.py",
    # fulfilment persistence + workflow: bitemporal case versions + the transition chokepoint, opaque
    # state/evidence — no product vocabulary.
    "src/app/services/fulfillment/repository.py",
    "src/app/services/fulfillment/workflow.py",
    # supplier draft: template-slot fill + scatter-gather evidence, opaque item/supplier refs —
    # no product vocabulary (real templates come from StoreProfile).
    "src/app/services/fulfillment/draft.py",
    # competitive RFQ fan-out + quote comparator: caged draft per top-N supplier + price/lead/reliability
    # ranking, cents·days·ratios only — no product vocabulary.
    "src/app/services/fulfillment/rfq_fanout.py",
    # external comms boundary + deterministic sandbox: send/receive/parse/validate, opaque refs —
    # no product vocabulary.
    "src/app/services/fulfillment/external_comms.py",
    # WS-C autonomous RFQ send: flag-gated safe-first policy gate (allowlist+KYV / claim-safe / complete /
    # confidence / value·qty caps / rate-limit / action-gate), pure policy — no product vocabulary.
    "src/app/services/fulfillment/autonomous_send.py",
    # Phase 3 buyer qualification: human-verified intent gate before supplier contact, opaque case/room
    # refs + a status flag — no product vocabulary.
    "src/app/services/fulfillment/buyer_qualification.py",
    # buyer status reply: claim-safe, commitment-free buyer-facing status per case state — no product vocab.
    "src/app/services/fulfillment/buyer_reply.py",
    # multi-line order split: groups a mixed request by approved supplier + creates one case per group,
    # opaque sku/qty/supplier — no product vocabulary.
    "src/app/services/fulfillment/order_split.py",
    "src/app/services/fulfillment/sandbox_supplier.py",
    # supplier-email transport seam: sandbox/SMTP provider interface, opaque message fields — no product vocab.
    "src/app/services/fulfillment/transport.py",
    # PO→ERP transport seam: sandbox/HTTP provider interface, opaque refs·cents — no product vocabulary.
    "src/app/services/fulfillment/po_transport.py",
    # fulfilment options planner: together/split/substitute with tradeoffs, opaque allocation —
    # no product vocabulary.
    "src/app/services/fulfillment/options.py",
    # recommend fulfilment stage: bulk availability + flag-gated case trigger, opaque — no product vocab.
    "src/app/services/recommend_fulfillment_stage.py",
    # inventory + bulk-shortfall handoff: stock eval → Sales approval/escalation, sku/stock/qty + opaque
    # agent-role labels only — no product vocabulary. Extracted from recommend.suggest.
    "src/app/services/recommend_inventory_handoff_stage.py",
    # recommendation choice-lanes: group candidates into profile-defined lanes (markers/exclusions are
    # opaque substrings from the profile; the core only matches + groups) — no product vocabulary.
    "src/app/services/recommend_choice_lanes.py",
    # per-pick narration evidence: typed *_fit metrics from candidate data + profile markers — no vocab.
    "src/app/services/recommend_evidence.py",
    # budget-band ranking truth: in/stretch/over/under + dominating over-budget penalty, cents/ratio only.
    "src/app/services/recommend_budget_band.py",
    # storefront-emphasis lever (David Phase 3): gated right-panel messaging variant for treatment users.
    # The only flavour (the variant copy) lives in the StoreProfile slot — the gate/canary/apply is opaque.
    "src/app/services/recommend_emphasis_stage.py",
    # market replay: deterministic synthetic signals → real M3, tenant-isolated — no product vocabulary.
    "src/app/services/market_replay.py",
    # market pipeline: real ingestion→analysis→findings (default tenant), opaque signals — no product vocab.
    "src/app/services/market_pipeline.py",
    # market warehouse sink (M2 depth + retention): daily (type,source) rollup + prune + depth query;
    # tenant·day·signal_type·source·counts·trust only — no product vocabulary.
    "src/app/services/market_warehouse.py",
    # competitor source: rival price observation table + seed, sku·cents only — no product vocabulary.
    "src/app/services/competitor_source.py",
    # support-objection source: buyer-objection table + seed, opaque theme — no product vocabulary.
    "src/app/services/support_objection_source.py",
    # funnel source: cart-abandonment table + seed, opaque stage·counts — no product vocabulary.
    "src/app/services/funnel_source.py",
    # supplier catalog: suppliers/supplier_products schema + demo seed, opaque ids — no product vocabulary.
    "src/app/services/supplier_catalog.py",
    # cart-commitment: GATE 1 materialization at the buyer's confirm — order_id idempotency + shortfall
    # arithmetic over opaque {item_ref, qty, in_stock} lines; routing/terms come from order_split. No vocab.
    "src/app/services/fulfillment/cart_commitment.py",
    # supplier out-of-band write-bus: records a supplier contact (domain·kind·note) + fans out to open
    # cases. Opaque strings only — no product vocabulary.
    "src/app/services/fulfillment/supplier_events.py",
    # procurement notifications: operator feed (kind·summary·ref opaque strings) — no product vocabulary.
    "src/app/services/fulfillment/notifications.py",
    # PO finalization: propose/approve/create/complete via the workflow chokepoint, opaque refs —
    # no product vocabulary.
    "src/app/services/fulfillment/purchase_order.py",
    # deal economics: margin/discount-headroom/profit math, cents + ratios only — no product vocabulary.
    "src/app/services/fulfillment/economics.py",
    # margin advisor (sell engine, rung A): verdict + proposed buyer discount, cents/ratios only — no vocab.
    "src/app/services/fulfillment/margin_advisor.py",
    # approval-tier policy (enterprise gate): spend→tier bands + role→level, cents/ints only — no product vocab.
    "src/app/services/fulfillment/approval_policy.py",
    # budget gate (enterprise gate): spend-vs-cap arithmetic keyed by an opaque category — no product vocab.
    "src/app/services/fulfillment/budget_gate.py",
    # 3-way match (AP control): PO=receipt=invoice qty/amount reconciliation, cents/ints only — no product vocab.
    "src/app/services/fulfillment/three_way_match.py",
    # reliable outbound queue: durable send + retry/backoff/dead-letter/855-ack — opaque to/subject/body, no product vocab.
    "src/app/services/fulfillment/outbound_queue.py",
    # outbound integrity guard: scan drafted supplier mail for relayed payloads + data leaks; regex over
    # opaque text, no product vocabulary.
    "src/app/services/fulfillment/outbound_integrity.py",
    # governance pulse: read-only Step-11 visibility — counts/rates over opaque audit labels, no product vocab.
    "src/app/services/governance_pulse.py",
    # procurement-request identity: PR/CASE/PO naming + rotation policy — opaque ids/dates/counts, no product vocab.
    "src/app/services/fulfillment/procurement_request.py",
    # Gate-3 change-order/cancellation: committed-cost/restock/penalty cents math + human-gated cancel — no product vocab.
    "src/app/services/fulfillment/change_order.py",
    # procurement fraud signals: amendment-churn cap + cancellation-pattern counts — opaque buyer key, no product vocab.
    "src/app/services/fulfillment/procurement_fraud_signals.py",
    # traffic-source attribution: utm/referrer → opaque channel label + per-channel visit/conversion — no product vocab.
    "src/app/services/traffic_source.py",
    # sales-response policy: {demand,inventory,margin}→{discount,price,promo,reorder} decision matrix — commerce-generic.
    "src/app/services/sales_response_policy.py",
    # support-phrasing policy: objection theme→response angle (price→value) — commerce-generic categories, no product vocab.
    "src/app/services/support_response_policy.py",
    # market store (deck M2): trend_indicator/competitor_snapshot/offer_policy — opaque entity_ref + numbers/enums.
    "src/app/services/market_store.py",
    # multi-intent turn parser (P0): amend/new-line/scoped-budget decomposition — numbers + grammar cues, no product vocab.
    "src/app/services/budget_grammar.py",
    "src/app/services/bulk_intent.py",
    "src/app/services/recommend_constraint_builder.py",
    "src/app/services/intent_decomposer.py",
    # scatter-gather adversarial guard (P0): category/budget/qty/context checks — opaque category token + numbers.
    "src/app/services/scatter_gather_guard.py",
    # multi-intent planner (P0): decompose→amend→scatter-gather→guard orchestration — opaque refs, injected search.
    "src/app/services/multi_intent_planner.py",
    # canonical catalog: price_book_entry + inventory_level (retail/stock), cents + counts — no product vocab.
    "src/app/services/commerce_catalog.py",
    # inventory source adapter: canonical-vs-legacy stock selection, sku→count only — no product vocab.
    "src/app/services/inventory_source.py",
    # supplier inbox reader: read-only supplier-history context (domain/cents/email) — no product vocab.
    "src/app/services/supplier_inbox_reader.py",
    # canonical identity + integration seam: product/variant/external_ref, attributes in JSON — no product vocab.
    "src/app/services/catalog_entities.py",
    # Shopify→canonical adapter (platform edge): speaks Shopify field names, not a product vertical.
    "src/app/services/shopify_catalog_adapter.py",
    # Magento→canonical adapter (platform edge): speaks Magento field names, not a product vertical.
    "src/app/services/magento_catalog_adapter.py",
]

# Unambiguous electronics/laptop flavour literals (brand models, GPU prefixes, display).
# Deliberately specific — avoids false positives on generic words.
_FLAVOUR_RE = re.compile(
    r"\b(rtx|gtx|vivobook|macbook|thinkpad|zenbook|ideapad|alienware|aspire|"
    r"predator|omen|spectre|pavilion|victus|katana|legion|"
    # canary WIDENED 2026-07-07 (next literal generation: vendors, chips, game/display words) —
    # affected baselines re-frozen at true counts the same day; the only-move-down rule resumes there.
    r"geforce|nvidia|radeon|ryzen|valorant|fortnite|vram|oled|"
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
    "src/app/routers/recommend.py": 20,  # re-frozen 2026-07-07 canary widening
    "src/app/routers/chat.py": 17,  # re-frozen 2026-07-07 canary widening  # chat router: clarify-text + brand-alias literals → profile slots
    "src/app/services/recommend_image_hints.py": 13,
    "src/app/services/recommend_nqe_helpers.py": 8,  # re-frozen 2026-07-07 canary widening
    # query_decomposer.py GRADUATED to _CORE_MODULES 2026-06-24 (NEW-2) — spec logic excised to profile.
    "src/app/services/product_ranking_agent.py": 5,  # re-frozen 2026-07-07 canary widening
    "src/app/services/recommend_vision_stage.py": 2,
    "src/app/services/recommend_budget_parsing.py": 4,  # re-frozen 2026-07-07 canary widening
    "src/app/services/use_case_advisor.py": 2,  # re-frozen 2026-07-07 canary widening
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
