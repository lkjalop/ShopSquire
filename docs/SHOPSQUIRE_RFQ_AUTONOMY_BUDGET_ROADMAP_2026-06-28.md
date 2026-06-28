# ShopSquire — RFQ Draft Quality · Autonomous Send · Budget-Ranking Truth — Roadmap (2026-06-28)

Exact file/line plan to (WS-A) fix the budget-ranking trust bug, (WS-B) make the supplier RFQ a real,
complete email, and (WS-C) make autonomous RFQ send safe enough to drop the human gate. Each workstream
is self-contained, agnostic-core-clean, ratchet-safe, and ends green. Sequence by value/risk:
**WS-A (budget) → WS-B (RFQ quality) → WS-C (autonomy)**.

Conventions: every config string lives in the StoreProfile (electronics.json), core stays vertical-blind
(`tests/test_no_flavour_in_core.py`), no new silent-excepts (`tests/test_no_silent_except_in_core.py`),
restore `config/feature_flags.json` after each test run.

---

## WS-A — Budget-ranking truth (the #1 buyer-trust must-fix)

**Bug:** the hard budget band is applied ONLY in the image-fallback builder
[recommend.py:866-868](src/app/routers/recommend.py#L866-L868); the PRIMARY ranker
[`_fast_path_product_score`:973-980](src/app/routers/recommend.py#L973-L980) treats budget as a SOFT
penalty (`score -= min(20, overage/100)`), so a $4,500 unit with a strong use-case/brand score outranks
in-budget units for a "$1,900 each" query.

**Fix (extract + harden, not a band-aid):**
1. New agnostic core module **`src/app/services/recommend_budget_band.py`**:
   - `band_status(price_cents, budget_min, budget_max, *, over_tol=0.10, under_tol=0.40) -> "in"|"stretch"|"over"|"under"` — tolerance-aware (a 10% stretch is "stretch", beyond is "over").
   - `budget_rank_penalty(status) -> float` — `in=0`, `stretch=-8`, `over=-1000`, `under=-6` (a **dominating** over-budget penalty so use-case score can never lift an over-budget unit above an in-budget one).
   - `filter_to_band(candidates, budget_min, budget_max, *, min_keep=4)` — keep in/stretch; if fewer than `min_keep`, re-add the cheapest over-budget as explicit `stretch` (never an empty result).
2. Wire into `_fast_path_product_score` [recommend.py:973-980](src/app/routers/recommend.py#L973-L980): replace the soft +/- block with `score += budget_rank_penalty(band_status(...))`. Keep the in-budget `+8/+10` bonuses.
3. Wire the candidate filter: after retrieval/rerank (near [recommend.py:1048-1063](src/app/routers/recommend.py#L1048-L1063) where `min_cents/max_cents` are computed) call `filter_to_band(...)` so over-budget items are dropped/tagged before tier-split + lanes.
4. Tag each result `budget_fit: in|stretch|over` (feeds the existing `price_fit` evidence in `recommend_evidence.py`) so narration says "within budget" / "a stretch at $X".

**Excise:** the inline soft-penalty math (973-980) and the fallback-only band (866-868) both move into the one module → single source of truth (kills the dup).

**Tests (until green):**
- New `tests/services/test_recommend_budget_band.py`: in/stretch/over/under classification; over-budget penalty dominates a max use-case score; `filter_to_band` never empties + tags stretch.
- New live-route acceptance in `tests/test_recommend.py`: "15 laptops $1900 each" → **no result priced > ~$2,090 ranks above an in-budget unit**; top results all in/stretch.
- Regression: `tests/services/test_use_case_business_ranking.py`, `test_use_case_fit_b2b.py`, full `tests/test_recommend.py`.
- Graduate `recommend_budget_band.py` → `_CORE_MODULES`.

---

## WS-B — Make the RFQ a real, complete email

**Today:** [DEFAULT_TEMPLATE:34](src/app/services/fulfillment/draft.py#L34) is a 6-slot fill; `needed_by`
defaults to the literal `"the stated deadline"` [build_draft:410](src/app/services/fulfillment/draft.py#L410);
`item_ref` is a bare code; `_requirements_block:330` renders only use_case/specs/days; slots assembled at
[draft.py:443](src/app/services/fulfillment/draft.py#L443). The profile already has a
`supplier_message_templates` slot [electronics.json:1370](config/store_profiles/electronics.json#L1370) but
build_draft does NOT read it (it uses the inline DEFAULT_TEMPLATE).

**Fix (richer structured RFQ, deterministic + claim-safe):**
1. **Profile (DATA):** add to electronics.json a `supplier_rfq` template + commercial-term slots:
   `quote_validity_days` (e.g. 14), `warranty_preference` ("3-year NBD onsite"), `payment_terms_ask`
   ("state payment terms / MOQ"), `ship_to_region` ("AU – metro"), `rfq_required_fields`
   (["sku_description","deadline","ship_to","quantity"]). A richer body template with new slots:
   `{sku_description}`, `{deadline_date}`, `{ship_to}`, `{warranty_terms}`, `{quote_validity}`,
   `{volume_discount_ask}`, `{payment_terms_ask}`. (Strings stay in the profile → core agnostic.)
2. **New SKU-description source** — `src/app/services/fulfillment/draft.py` helper
   `_sku_description(db, item_ref, tenant_id)`: `SELECT name, specs FROM products WHERE sku=:s AND active=1`
   (pattern from [recommend_narration_stage.py:217](src/app/services/recommend_narration_stage.py#L217)) →
   "Dell Latitude 7450 — Core Ultra 7 / 16GB / 512GB / 14" FHD / Win11". Falls back to `item_ref`.
3. **Real deadline + region** — set on the case at the procurement trigger:
   [recommend_fulfillment_stage.py:82-122](src/app/services/recommend_fulfillment_stage.py#L82-L122) add
   `reqs["needed_by"]` (concrete date from `needed_within_days`) + `reqs["ship_to"]` (profile region). Thread
   `needed_by` into `draft_and_record` [draft.py:484](src/app/services/fulfillment/draft.py#L484) → `build_draft(needed_by=...)`.
4. **Build the body** — extend the slots dict [draft.py:443](src/app/services/fulfillment/draft.py#L443):
   add sku_description/deadline_date/ship_to/warranty_terms/quote_validity/volume_discount_ask (the
   volume ask only when `quantity >= bulk_threshold`). Load the profile template in build_draft
   (`profile_slot("supplier_rfq")`), fall back to DEFAULT_TEMPLATE.
5. **Completeness check** — new `rfq_completeness_reason(slots, required_fields) -> Optional[str]` in
   draft.py (sibling to `claim_safety_reason:104`); attach `draft["completeness"] = {ok, missing}` in
   `draft_and_record`. An incomplete draft is FLAGGED (and, in WS-C, blocks auto-send).
6. **Cage unchanged** — `claim_safety_reason:104` still rejects price/PO/URL/foreign-email; the new fields
   are all non-price asks, so they pass. Keep the not-a-PO footer.

**Extract/refactor:** the body assembly grows — pull slot-building into `_build_rfq_slots(db, case_state,
item_ref, quantity, needed_by, evidence, profile_fn)` so build_draft stays readable; keep `draft.py` in
`_CORE_MODULES` (flavour stays in the profile).

**Tests (until green):**
- Extend `tests/services/fulfillment/test_draft.py`: body now contains SKU description (not just code),
  a concrete deadline, ship-to, quote-validity, and a volume-discount ask for qty≥threshold; still
  claim-safe (no price/PO); completeness passes when fields present, flags when missing.
- Profile parity: `tests/test_no_flavour_in_core.py` (draft.py clean), `test_profile_parity.py`.
- Full `tests/services/fulfillment/ -q` + `tests/integration/test_fulfillment_api.py`.

---

## WS-C — Autonomous RFQ send (drop the human gate, safely)

**Today:** GATE 2 is the human in [`external_comms.send_approved`:100](src/app/services/fulfillment/external_comms.py#L100)
(hash-checked, sandbox transport by default). The policy chokepoint
[`adaptive_action_gate.authorize`:108](src/app/services/adaptive_action_gate.py#L108) exists with
`ALLOWED_ACTION_TYPES:38` (today `supplier_contact_draft` is drafting-only; **send is NOT an allowed
autonomous action**).

**Fix (policy gate replaces human gate, bounded + reversible):**
1. Add `"supplier_rfq_send"` to `ALLOWED_ACTION_TYPES`
   [adaptive_action_gate.py:38](src/app/services/adaptive_action_gate.py#L38).
2. New `src/app/services/fulfillment/autonomous_send.py` (agnostic core) —
   `maybe_autonomous_send(db, *, case_id, draft, send_fn, gate_fn, ...) -> ("auto_sent"|"escalated", reason)`.
   Auto-send ONLY when ALL hold (else return "escalated" → existing human gate):
   - flag `FULFILLMENT_AUTONOMOUS_RFQ=1` (default OFF) + kill-switch (`experiment_ops.adaptation_killed()`),
   - recipient on allowlist + KYV-verified (already resolved in build_draft via `select_supplier:300`),
   - `claim_safety_reason(body)` is None AND `rfq_completeness_reason` is None (WS-B),
   - `draft.confidence >= AUTO_SEND_MIN_CONFIDENCE` (default 0.8) AND
     `estimated_value_cents <= AUTO_SEND_MAX_VALUE_CENTS` (default e.g. $20k) AND
     `quantity <= AUTO_SEND_MAX_QTY`,
   - per-supplier/tenant rate limit (Redis SETNX window) — no spam,
   - `adaptive_action_gate.authorize(action_type="supplier_rfq_send", confidence, subject, target)` ALLOWs.
   On all-pass → call the real send via `external_comms.send_approved` (transport seam) + record an
   `autonomous_send` trace event; on any fail → "escalated" (case stays AWAITING_APPROVAL for a human).
3. Wire one call in `fulfillment_cases.py` after `draft-quote`/`request-approval` (operator path keeps the
   manual gate; the autonomous path is the flag-gated branch). Reversibility/observability: bitemporal
   trace (already), anomalies → `exception_resolver.enqueue_exception`, post-hoc human override.

**Why safe first:** an RFQ is non-binding (not a PO, no price) to an APPROVED supplier → worst case is
reputational, and the completeness + claim cage + value/qty caps + rate-limit + kill-switch bound it.

**Tests (until green):**
- New `tests/services/fulfillment/test_autonomous_send.py`: auto-sends when all gates pass; escalates on
  each failing gate (flag off, low confidence, over value cap, incomplete draft, unsafe body, rate-limited,
  killed); records the trace event; transport injected (no network).
- `GATE_PROCUREMENT=1 pytest tests/e2e/test_procurement_journey_playwright.py` (governed path intact).
- Graduate `autonomous_send.py` → `_CORE_MODULES` + silent-except baseline 0.

**Still needed beyond code (gated on you):** real SMTP transport creds
(`FULFILLMENT_SUPPLIER_TRANSPORT=smtp`); the supplier-reply ingest + quote parse already exist
(`external_comms.receive_reply`/`parse_quote`) to auto-advance; a trained confidence model later (rules first).

---

## Cross-cutting + iterate-until-green discipline
- **Order:** WS-A (commit) → WS-B (commit) → WS-C (commit). Each: edit → `py_compile` → targeted tests →
  graduate to `_CORE_MODULES` → ratchets → relevant full suite (`test_recommend.py` for A, `fulfillment/`
  for B/C) → restore `feature_flags.json` → commit.
- **Agnostic ratchet:** all new strings (RFQ template, terms, thresholds-as-profile where vertical) live in
  electronics.json; core modules stay flavour-free.
- **Demo flags (orthogonal, from the live test):** start the backend with `FULFILLMENT_DEMO_ENABLED=1` +
  `tmp_feature_flags_demo.json`; map `409 chat_replay_detected` to a "retry shortly" UI message
  ([chat.py:1256](src/app/routers/chat.py#L1256), [App.tsx:1231](frontend/src/App.tsx#L1231)) — small,
  separate from these three workstreams.

## Effort / sequence summary
| WS | Scope | New files | Risk | Demo value |
|---|---|---|---|---|
| A budget | hard band module + 2 wire points | recommend_budget_band.py | low | **high (trust)** |
| B RFQ | richer template + sku-desc + completeness | (helpers in draft.py) | low–med | high |
| C autonomy | policy-send gate, flag-OFF default | autonomous_send.py | med (gated) | high (David's doctrine) |
