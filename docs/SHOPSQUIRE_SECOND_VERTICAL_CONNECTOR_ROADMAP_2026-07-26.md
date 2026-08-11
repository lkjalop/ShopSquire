# ShopSquire — Second Demo Vertical + Connector Registry + Narration + Replenishment + Market Intel + Bounded Autonomy

**Date:** 2026-07-26. A staged, TDD roadmap. Every stage: files·line, wiring, red test, commit boundary, why.

---

## 0. The pick — Pharmacy/health as the second demo vertical (it's already half-built)

`config/store_profiles/{pharmacy,fashion}.json` and `data/attributes/{pharmacy,fashion}.json` **already
exist** — the agnostic core is multi-vertical at the config layer; these verticals are dormant, not
absent. Choosing pharmacy is an *activation*, and it's the strongest choice for the themes you named:

| Theme you asked for | Why pharmacy is the best contrast to electronics |
|---|---|
| **Authoritative narration** | Regulator citation (openFDA / **TGA (AU)**) — the trust moat; safety-critical → citation is *mandatory*, which showcases the guard |
| **Bounded autonomy** | THE canonical case: "agent proposes, a **pharmacist** authorizes, never acts autonomously on safety" — bounded autonomy made vivid |
| **Auto-replenishment** | Pharmacies reorder OTC/supplements/consumables constantly — natural cadence-reorder story |
| **Market intelligence** | Seasonal demand (cold/flu), velocity, expiry/waste — textbook |
| **Supplier comms** | Regulated pharmaceutical wholesale — a real, governed supply chain |
| **Proves the agnostic core** | "RAM → milligrams" is literally the doctrine's own example — dramatic vertical-blind proof |

**Demo-risk control:** scope to **OTC / supplements / consumables**, never prescription/diagnosis. The
safety-critical nature becomes the *feature* — the platform refuses medical advice, cites the regulator,
defers to the pharmacist. If you want zero health exposure, **grocery/facilities-consumables** (Open
Food Facts connector) is the fallback with the same replenishment story minus the regulator moat; the
roadmap below is vertical-parameterized so either works.

---

## 1. Stage G0 — Activate the pharmacy vertical (data-first, agnostic path)

**Goal:** the existing agnostic core serves a pharmacy query end-to-end with no core code change.

- **Wire:** seed a pharmacy catalog (products + inventory + `product_classification` under pharmacy
  taxonomy nodes); confirm `data/attributes/pharmacy.json` covers the fit attributes (dosage_mg,
  form, active_ingredient, pack_size); set the store profile active for a `pharmacy_demo` tenant.
- **Files:** [config/store_profiles/pharmacy.json], [data/attributes/pharmacy.json],
  `taxonomy_registry` (pharmacy sold nodes), a new `scripts/seed_pharmacy_demo.py` (mirror
  `seed_demo_sales_metrics.py`).
- **TDD (red→green):**
  - `sells_within(db, <pharmacy_node>, tenant="pharmacy_demo")` is True; an electronics node is False.
  - `route_turn` on *"something for a cold and sore throat, under $20"* returns SEARCH grounded to a
    pharmacy node, **no GPU/VRAM leakage** (the agnostic-core invariant — reuses `test_no_flavour_in_core`).
  - `normalize_specs` maps `dosage_mg` (proves the RAM→mg blindness).
- **Commit:** `feat(pharmacy): activate dormant vertical with demo catalog`

---

## 2. Stage G1 — Connector registry (generalize the Steam pattern)

**Goal:** the Steam pattern becomes a pluggable interface so a new category is a new connector file,
zero core change (vertical-blind doctrine).

- **Wire:** new `src/app/services/connectors/base.py`:
  ```
  class KnowledgeConnector(Protocol):
      vertical: str
      trust_tier: int              # 1 regulator/first-party · 2 fixture · 3 allowlisted-structured · 4 web
      allowlist_domain: str | None
      def lookup(self, entity: str, *, allow_live: bool) -> Evidence | None   # fixture-first, cited, never raises
  # Evidence = {claims:[{key,value,unit}], source, source_url, retrieved_at, cached, trust_tier, ttl_days}
  ```
  Refactor `steam_requirements.py` + `competitor_price_fetch.py` to it (behavior-preserving). Register
  connectors per vertical in the store profile (`knowledge_connectors: [...]`), resolved like
  `external_research_allowlist` is today.
- **New connector:** `connectors/openfda_connector.py` (pharmacy) — openFDA/DailyMed drug+supplement
  label facts → `Evidence` with `source_url`; fixture-first (`config/knowledge_pool/openfda_fixtures.json`),
  live behind allowlist + consent. Same shape as Steam.
- **Files:** [connectors/steam_requirements.py:278], [connectors/competitor_price_fetch.py], new
  `base.py` + `openfda_connector.py`, [config/store_profiles/*.json] (`knowledge_connectors`).
- **TDD:**
  - Registry resolves the right connectors for a vertical; unknown vertical → empty (no guess).
  - `openfda_connector.lookup("ibuprofen")` returns cited claims from a fixture; miss + `allow_live=False` → None.
  - Every connector conforms (contract test over the registry): returns `Evidence|None`, never raises, always carries `source_url` + `trust_tier`.
- **Commit:** `feat(connectors): pluggable knowledge-connector registry` · `feat(pharmacy): openFDA connector`

---

## 3. Stage G2 — Claim guard extends to external evidence (the #1 accuracy fix)

**Goal:** the narration guard grounds against the assembled **evidence set**, not just the catalog —
closes the gap where "Cyberpunk needs RTX 4090" or "TGA-approved" slips through.

- **Wire:** [product_claim_guard.py:1-9](../src/app/services/product_claim_guard.py#L1) currently binds
  claims to `results` (catalog). Add an `evidence_claims` input (the union of connector `Evidence.claims`
  + `steam_note` lines + regulatory facts). A narrated spec/claim must trace to **either** the catalog
  **or** the evidence set; anything else → reject → deterministic fallback. Make the
  `format_evidence_for_narration` "cite ONLY these lines, never invent beyond them"
  ([market_intelligence_agent.py:105-114](../src/app/services/market_intelligence_agent.py#L105)) the
  **enforced** wrapper for every external block, not a per-prompt request.
- **Trust-tiered language:** narration renders T1 as fact ("per the TGA…"), T3/T4 hedged ("according to
  notebookcheck…"), parametric knowledge avoided for factual claims — mirroring the UI trust tiers
  ([evidenceDisplay.ts:30-35](../frontend/src/lib/evidenceDisplay.ts#L30)).
- **Files:** [product_claim_guard.py], [recommend_workload_stage.py:200-204](../src/app/services/recommend_workload_stage.py#L200), evidence_orchestrator narration path.
- **TDD:**
  - Narration asserting a spec **not** in catalog **or** evidence → `rejected=True` (deterministic fallback used).
  - A claim present in `Evidence.claims` with a `source_url` → allowed, citation attached.
  - A safety claim ("TGA-approved") with **no** regulator evidence → rejected. With evidence → allowed as "per the TGA".
- **Commit:** `fix(narration): ground cite-or-suppress against external evidence set`

---

## 4. Stage G3 — Source trust tiering, freshness, conflict, injection

**Goal:** the accuracy hardening from the adversarial critique.

- **Wire:**
  - **Tiering & routing:** the orchestrator picks the highest-trust available source; **T4 web never
    overrides T1** ([evidence_orchestrator.py:75](../src/app/services/evidence_orchestrator.py#L75)).
  - **Freshness:** `Evidence.ttl_days` + `retrieved_at` → a `stale` flag surfaced in the citation;
    **safety-critical claims blocked on stale data** (re-fetch or suppress).
  - **Conflict:** two sources disagree → conservative-wins (higher requirement / stricter safety) +
    surface the disagreement in the trace.
  - **Entity match confidence:** [steam_requirements.py:103-133](../src/app/services/connectors/steam_requirements.py#L103) token-subset score gets a threshold; below it, surface "did you mean <title>?" instead of grounding silently.
  - **Unknown-translation:** [gpu_translation.py] unknown GPU ⇒ `unknown` verdict, never silent pass (tri-state doctrine applied).
  - **Injection:** sanitize/bound fetched HTML text before it reaches the narrator (reuse the injection-marker scan; content stays "verified-untrusted").
- **TDD:** T4 can't override T1; stale fixture flags `stale` + blocks a safety claim; conflicting sources → conservative + surfaced; below-threshold title → clarify, not ground; unknown GPU → `unknown`; injected payload in fetched text → stripped/quarantined.
- **Commit (slice):** `feat(evidence): trust tiering + freshness` · `feat(evidence): conflict + confidence resolution` · `fix(fit): unknown GPU translation is unknown, not pass`

---

## 5. Stage G4 — Supplier comms + auto-replenishment (recurring, human-gated)

**Goal:** move replenishment from *event-triggered only* to *cadence-aware*, keeping the send human-gated.

- **Current:** [market_action_policy.authorize_replenishment](../src/app/services/market_action_policy.py#L29)
  gates on ATP deficit + demand + economics + source-diversity — but it's event-triggered, not cadence.
  There are **no standing-order/consumption-cadence primitives** (confirmed by grep).
- **Wire:**
  - **Consumption-rate + reorder-point** (new detector, [market_analysis.py] alongside velocity/DSI):
    `ROP = mean_daily_consumption × lead_time + safety_stock`; when `on_hand ≤ ROP` **and** the policy
    authorizes → a **standing-order reorder proposal** with a computed quantity (rounds up to MOQ break).
  - **Proposal, never auto-send:** flows through
    [commercial_action_proposals.py](../src/app/services/commercial_action_proposals.py) (`auto_sent:False`,
    `send_gate:human`) → [reorder_supplier_flow.py] drafts → **human approves** (GATE 2 unchanged).
  - **Supplier-comms integrity:** amendments redraft content but **never silently switch channel**
    (email/API/EDI); a channel change requires a supplier-record change (regression-lock this).
- **Files:** [market_analysis.py], [market_action_policy.py:29], [commercial_action_proposals.py],
  [reorder_supplier_flow.py], [fulfillment/draft.py:503].
- **TDD:** consumption → ROP → proposal with MOQ-respecting qty; weak/stale evidence → **denied**; send stays human; quantity amendment redrafts but channel is stable; reorder proposal never marks itself sent.
- **Commit:** `feat(market): consumption-rate + reorder-point detector` · `feat(actions): cadence replenishment proposal (human-gated)` · `test(fulfilment): supplier-channel stability across amendments`

---

## 6. Stage G5 — Market-intelligence metrics (vertical-appropriate + earned autonomy)

**Goal:** metrics that fit consumables + the forecast-accuracy loop that earns autonomy.

- **Wire:**
  - **Consumables metrics** on the existing evidence spine: reorder frequency, days-of-cover (WOS),
    consumption trend, expiry/waste-risk (if the vertical carries expiry) — all as `MetricEvidence` with
    `status ∈ {observed,estimated,insufficient,unavailable}` + provenance
    ([executive_metrics.py], [market_projection.py]).
  - **Forecast-accuracy loop** (from the exec-metrics doc): persist forecast→actual pairs → WAPE/bias →
    feed measured accuracy into `authorize_replenishment`'s `min_confidence`. **Autonomy earned from
    demonstrated accuracy**, never configured on.
  - **Seasonal** demand already exists ([market_analysis.py] `seasonal_demand`) — surfaces cold/flu peaks.
- **Files:** [executive_metrics.py], [market_projection.py], [market_action_policy.py:107] (shadow forecast-quality hook already present).
- **TDD:** metrics compute from canonical facts; unavailable-when-unproven (GMROI-style honesty); WAPE below threshold → replenishment confidence stays conservative; property tests (`WOS≥0`, no cross-currency, duplicate events don't move metrics) extended per vertical.
- **Commit:** `feat(bi): consumables metrics + forecast-accuracy → gate confidence`

---

## 7. Stage G6 — Bounded-autonomy ladder + per-vertical policy packs (cross-cutting)

**Goal:** one gate engine, per-vertical policy — the segregation-of-duties story the demo sells.

- **Wire:** the gate ladder is `adaptive_action_gate` (confidence floor + authorization + durable audit)
  → `market_action_policy` (evidence sufficiency) → **GATE 2 human send**. Add **per-vertical policy
  packs** (tenant config, not code):
  - **pharmacy:** discounts/marketing conservative; **safety actions NEVER autonomous** — always
    pharmacist-gated; replenishment allowed with approval.
  - **electronics:** current behavior.
  - **grocery/consumables:** cadence reorder allowed with approval; markdown on surplus allowed.
  - The trace's role ontology (model▸proposes / gate▸authorizes / connector▸executes / observer▸observes,
    [DecisionTrace.tsx:206-228](../frontend/src/components/DecisionTrace.tsx#L206)) shows the SoD live.
- **Files:** `adaptive_action_gate`, [market_action_policy.py], store-profile policy-pack slot, DecisionTrace.
- **TDD:** weak evidence → authorized DENY; earned WAPE widens bounds; **pharmacy safety action hard-gated
  regardless of confidence**; every verdict reproducible from its recorded evidence (audit invariant).
- **Commit:** `feat(policy): per-vertical bounded-autonomy policy packs`

---

## 8. Execution order & why

1. **G0** (activate pharmacy) — unlocks the whole second-vertical demo; data-first, lowest risk.
2. **G2** (claim-guard→evidence) — the **#1 accuracy fix**, small, stack-verifiable now; makes any cited
   claim trustworthy across both verticals.
3. **G1** (connector registry + openFDA) — the regulator-citation moat; the demo's headline.
4. **G3** (tiering/freshness/conflict) — hardening; ships in slices behind G1.
5. **G4** (cadence replenishment) — the supplier-comms/auto-reorder beat.
6. **G5** (metrics + earned autonomy) — deepens the BI story.
7. **G6** (policy packs) — the cross-cutting SoD/bounded-autonomy showcase.

**Demo-day subset (if time-boxed):** G0 + G2 + G1 alone give you a *second industry, regulator-cited,
grounded-narration* demo — the "it's a platform, not a laptop bot, and it cites the TGA" story — which
is the single most credibility-shifting thing you can add.

**Doctrine guardrails (unchanged, enforced at every stage):** unknown ⇒ `unknown` (never a guessed pass);
every external claim carries a `source_url`; safety claims require a regulator citation or are suppressed;
consequential sends stay human-gated; one-concern commits, red-test-first, `as_of`+confidence on every
number.

*No code changed in this assessment.*
