# ShopSquire Agnostic Core Independent Review

Date: 2026-06-18  
Scope: independent review of the current ShopSquire codebase against the agnostic-core roadmap, Claude/Opus 4.8 recommendations, future vertical portability, smarter NLP/product recommendation, bounded autonomy, latency, silent-fail risk, and `recommend.py` shrink strategy.

## Executive Verdict

ShopSquire is moving in the right direction. The architecture does not need a rewrite. The right move is a disciplined strangler extraction: keep the policy-bounded commerce decision layer, move vertical flavour into StoreProfile/config/adapters, and turn the monolithic recommendation route into small auditable stages.

The biggest current risk is not just the size of `recommend.py`. The larger portability blocker is that several supporting services still contain electronics-specific logic:

- `src/app/services/product_taxonomy.py`
- `src/app/services/checkout_upsell.py`
- `src/app/services/use_case_advisor.py`
- `src/app/services/cv_triage_basic.py`
- `src/app/services/llm_provider.py`
- `src/app/flows/nqe.py`
- selected blocks in `src/app/routers/recommend.py`

The StoreProfile scaffold now exists and is useful, but it is ahead of the actual wiring. Some modules read StoreProfile; others still read `config/store_vocab.json`, fixed use-case knowledge files, or hard-coded electronics rules. That creates dual-source drift.

Recommended first implementation sequence:

1. Fix StoreProfile strictness and config ownership so missing tenant/profile config cannot silently fall back to electronics in production.
2. Move product taxonomy, upsell companions, bundle rules, CV relevance, NQE templates, and LLM complexity keywords behind StoreProfile or a StoreTaxonomyPort.
3. Add a shared `QueryUnderstanding` contract before deeper LLM/narration changes.
4. Add V2 parity metrics before cutting over from the monolith.
5. Extract `recommend.py` stages only after the stage contracts are pinned by characterization tests.

## What Claude Got Right

The Claude/Opus 4.8 review is directionally correct:

- The moat is policy-bounded commerce decisions with evidence, not a generic chatbot.
- The core/adaptor split is the right path for vertical portability.
- `recommend.py` should be reduced by stage extraction, not rewritten.
- The platform should keep deterministic decision-making for stock, price, policy, safety, and audit.
- LLMs should interpret and narrate, not own privileged business decisions.
- Vision should not let raw OCR, QR payloads, or prompt-like text become instructions.
- The previous unbounded scatter-gather risk was real and needed attention.

## What Has Already Changed Since That Review

Some of the Claude blockers are now partially fixed or have shifted:

| Area | Current finding |
|---|---|
| StoreProfile exists | `src/app/platform/store_profile.py:1` now provides the canonical profile loader. |
| Electronics/pharmacy scaffold exists | `config/store_profiles/electronics.json:1` and `config/store_profiles/pharmacy.json:1` exist. |
| Query decomposition is partly profile-backed | `src/app/services/query_decomposer.py:86` loads `use_case_patterns` from StoreProfile. |
| Scatter-gather timeout exists | `src/app/services/recommend_pipeline.py:58` wraps legs with `asyncio.wait_for`. |
| V2 is still shadow-only | `src/app/routers/recommend.py:6369` starts the non-blocking V2 shadow path, but parity/fusion is still incomplete. |
| `recommend.py` is smaller but still huge | Current file is about 14,078 lines; `suggest()` starts at `src/app/routers/recommend.py:6287`. |

The new independent finding is that portability work must include `product_taxonomy.py`, `checkout_upsell.py`, `bundle_pricing.py`, and `use_case_advisor.py`, not only `recommend.py`, NQE, CV, and LLM routing.

## Highest Priority Findings

| Priority | File and lines | Problem | Why fix exactly | Business impact | Recommended fix | Tests |
|---|---:|---|---|---|---|---|
| P0 | `src/app/platform/store_profile.py:40` | Missing profiles fall back to electronics by default. | A tenant/profile typo can route pharmacy, grocery, or apparel through electronics rules without failing visibly. | Wrong recommendations, wrong NQE, wrong CV relevance, compliance risk for regulated verticals. | Add explicit `strict=True` production mode and require tenant profile resolution. Keep demo fallback only under dev/test flag. | `tests/platform/test_store_profile_loader.py`, new missing-profile strict test. |
| P0 | `src/app/services/checkout_upsell.py:668` | Price guards compare cent values to tiny thresholds such as `1200`. | `cart_price` appears to be cents; `1200` means $12, so the filter is probably always active for normal laptop carts. | Bad upsell filtering, missed revenue, misleading bundle/deal behavior. | Introduce named cents constants or convert to dollars once. Add cart-price unit tests. | New `tests/services/test_checkout_upsell_price_guards.py`. |
| P0 | `src/app/services/product_taxonomy.py:6` | Product taxonomy is hard-coded to laptop/accessory families. | Even if `recommend.py` becomes agnostic, downstream classification still assumes electronics. | Vertical #2 may get nonsensical bundles and upsells. | Move SKU families, product type patterns, accessory slugs, and complement rules into StoreProfile or StoreTaxonomyPort. | New `tests/services/test_product_taxonomy_profile.py`. |
| P1 | `config/store_vocab.json:12`, `config/store_profiles/electronics.json:1` | Dual config sources define overlapping taxonomy and price concepts. | StoreProfile can pass while product classifier reads stale `store_vocab.json`. | Hidden drift; profile-based tests give false confidence. | Pick one canonical source. Prefer StoreProfile, with optional compiled vocab cache. | Update `tests/platform/test_agnostic_profile.py` and flavour lint. |
| P1 | `src/app/services/llm_provider.py:13`, `config/ml/tier_ladder.json:19` | Medium default mismatch: code defaults to `qwen3.6:27b`, ladder says `qwen3:14b`. | Cost/latency claims depend on model tier routing. | Unexpected GPU load and slower responses. | Align defaults to `qwen3:14b`, or document and test intentional override. | New `tests/services/test_llm_provider_tier_ladder.py`. |
| P1 | `src/app/services/llm_provider.py:75` | Complexity routing keywords are electronics-heavy. | Pharmacy/grocery/apparel queries can be scored by laptop/GPU terms, or miss domain complexity. | Wrong model tier, wrong cost, wrong latency. | Move complexity keyword packs into StoreProfile by vertical. | New profile complexity tests. |
| P1 | `src/app/services/cv_triage_basic.py:109` | Image relevance is binary and electronics/food hard-coded. | Adjacent images need different behavior from off-topic images. | Laptop photo + "bag for this" can be mishandled; unrelated image can pollute ranking. | Add `image_relation = on_topic | adjacent | off_topic` using profile primary types and decomposed text intent. | New CV relation tests. |
| P1 | `src/app/flows/nqe.py:540` | NQE templates for school/university/gaming/corporate are hard-coded. | NQE is where user understanding becomes visible; verticals need different clarifying questions. | Bad UX and useless questions outside electronics. | Move templates, triggers, option sets, and field map into StoreProfile/NQE pack. | New `tests/flows/test_nqe_profile_templates.py`. |
| P1 | `src/app/services/use_case_advisor.py:73` | Use-case matching and suitability are fixed to laptop specs. | This service can override agnostic retrieval with electronics-only reasoning. | Wrong explanations and suitability scores for other stores. | Introduce `VerticalKnowledgePort` or StoreProfile use-case packs. | New `tests/services/test_use_case_advisor_profile.py`. |
| P1 | `src/app/services/recommend_pipeline.py:71` | Scatter legs now time out, but leg errors still collapse to empty results. | A failed source can look identical to a true no-hit result. | Silent quality drop and hard-to-debug latency/retrieval issues. | Return typed source statuses through the recommendation response and trace. Reuse `commerce_source_status.py`. | New `tests/services/test_recommend_pipeline_source_status.py`. |
| P2 | `src/app/services/bundle_pricing.py:23` | Bundle copy and bundle policy are laptop/accessory-specific. | Deals and bundles are core ecommerce behavior but vertical-specific in rules. | Wrong discount UX and possible margin leakage. | Move bundle eligibility/copy/rules to StoreProfile policy slots. | New bundle profile tests. |
| P2 | `src/app/routers/recommend.py:716` | Safe image brands/categories are hard-coded. | StoreProfile can know brands, but fast-path hints still know electronics directly. | ASUS/MSI fixes do not generalize; non-electronics images get bad hints. | Extract to `recommend_image_hints.py` and feed from profile. | Characterization tests on current image hint behavior. |
| P2 | `src/app/routers/recommend.py:12958` | LLM narration still needs stronger claim grounding. | Narration can overstate product claims not supported by product evidence. | Trust risk and demo risk. | Keep finalizer as mandatory claim guard; require reason/evidence fields for every claim. | Narration no-unsupported-claim tests. |

## Are We Going In The Right Direction?

Yes. The key direction is correct:

- Buy or adapt commodity ecommerce services around the edge.
- Keep ShopSquire's custom value in decisioning, policy gates, evidence, retrieval fusion, and traceable recommendations.
- Make store-specific knowledge declarative or adapter-owned.
- Keep privileged business actions behind `decide()`/policy gates.

The sequencing needs discipline. Do not start by making all NLP smarter with a large new LLM layer. First make the existing deterministic and profile-backed path reliable. Then let LLMs improve interpretation and narration within bounded contracts.

## Do We Need To Rearchitect?

No full rewrite is recommended.

The platform needs a spine extraction:

```text
Request
  -> Input normalization / threat boundary
  -> QueryUnderstanding
  -> StoreProfile / TenantConfig
  -> Candidate retrieval and fusion
  -> Policy / stock / price / eligibility gates
  -> Why/evidence builder
  -> Finalizer / narration
  -> Decision trace
```

That is an evolution of the current system, not a replacement.

The current route-level monolith is a maintainability problem, but the underlying architectural idea is viable. Rewriting it would risk throwing away the useful moat: trace-linked recommendations, policy separation, image quarantine, and deterministic commerce gates.

## Core Versus Adapter Boundary

### Core Logic

The following should remain ShopSquire core and product/vertical agnostic:

- Request envelope and input trust labels.
- Prompt-injection and multimodal boundary checks.
- Query decomposition contract.
- Retrieval orchestration and source-status accounting.
- Candidate fusion mechanics.
- Inventory availability checks.
- Policy gates for price, refund, discount, stock, fraud, and tool execution.
- Decision trace and audit semantics.
- Final answer grounding and unsupported-claim prevention.
- Consent-aware customer context envelope.
- CPU/GPU model-tier routing interface.

### StoreProfile / Adapter Logic

The following should move out of core code:

- Brand lists and brand aliases.
- Product type taxonomy.
- SKU family rules.
- Price floors and price bands.
- Use-case patterns.
- Spec constraints and extractors.
- NQE questions and answer options.
- CV relevance vocabulary.
- Bundle rules and discount eligibility.
- Upsell companion maps.
- Supplier email templates and thresholds.
- Store policy thresholds, such as max discount, approval rules, and restock triggers.

### Adapter Ports

Use ports for external systems:

- `CatalogPort`: products, variants, specs, media, price, categories.
- `InventoryPort`: stock, reservations, ETA, warehouse/store availability.
- `CustomerContextPort`: consented profile, loyalty tier, browsing session, purchase history.
- `OrderPort`: carts, orders, returns, refunds.
- `SupplierPort`: restock request, MOQ, lead time, vendor contact.
- `PromotionPort`: active deals, coupons, margin constraints.
- `LLMProviderPort`: tenant or generic interpretation/narration model.
- `VisionProviderPort`: tenant or generic image classifier/captioner.

The adapter can provide models, vision weights, policies, or catalog data, but it should not bypass the core policy and evidence gates.

## StoreProfile And Config Drift

### Current State

`src/app/platform/store_profile.py:1` defines the canonical StoreProfile loader. It reads `config/store_profiles/*.json`.

However, other services still read different sources:

- `src/app/services/product_classifier.py:1` reads `config/store_vocab.json`.
- `src/app/services/use_case_advisor.py:32` reads `config/use_case_knowledge_base.json`.
- `src/app/services/use_case_advisor.py:37` reads `config/use_case_knowledge.json`.
- `src/app/services/product_taxonomy.py:6` uses hard-coded family constants.
- `src/app/services/checkout_upsell.py:42` uses hard-coded persona accessory families.

This means the platform is not yet truly profile-driven. It has a profile scaffold plus several older vertical-specific paths.

### Fix

Make StoreProfile the only canonical vertical config source, or introduce a compiled vertical bundle generated from StoreProfile:

```text
config/store_profiles/electronics.json
  -> StoreProfile loader
  -> compiled StoreTaxonomy / UseCasePack / NQEPack
  -> services read typed profile APIs only
```

Keep `config/store_vocab.json` only if it becomes generated output or a legacy fallback under explicit test coverage.

## Upsell Assessment

There are two upsell systems to rationalize.

### Old Upsell Engine

`src/app/services/upsell_engine.py:33` has hard-coded cross-sell logic:

- gaming laptop -> mouse/headset/monitor/cooling
- school laptop -> backpack/sleeve/charger
- office laptop -> dock/keyboard/mouse/monitor

`src/app/services/upsell_engine.py:145` has category expansion that can silently return empty results. The comment at `src/app/services/upsell_engine.py:254` admits the path is for stores with category metadata. This is currently a dead or store-dependent silent path.

Recommendation:

- Either retire this module if `checkout_upsell.py` is the real path, or make it a thin profile-backed utility.
- Move companion maps to StoreProfile `upsell_companions`.
- Add observability for empty/error source statuses.

### Checkout Upsell

`src/app/services/checkout_upsell.py:609` is more advanced and commercially useful. It uses:

- cart items
- product catalog
- co-purchase data
- recent user interactions
- lifecycle profile
- conversion model reorder
- rule-based fallbacks

That is the right primitive for ecommerce. The problem is portability.

Hard-coded sections:

- `src/app/services/checkout_upsell.py:42` persona accessory slugs.
- `src/app/services/checkout_upsell.py:60` intent family inference.
- `src/app/services/checkout_upsell.py:76` family complement weight matrix.
- `src/app/services/checkout_upsell.py:668` price guard unit concern.

Recommended future shape:

```text
checkout_upsell.py
  -> reads StoreTaxonomyPort
  -> reads PromotionPort
  -> reads consented CustomerContextPort
  -> scores deterministic candidates
  -> policy gate validates discount/deal claims
  -> optional LLM only explains the already-selected candidates
```

### Business Impact

Upsell is one of the strongest revenue features if it is correct. It becomes harmful if it suggests irrelevant products, violates discount policy, or uses customer history without consent.

For electronics:

- laptop -> sleeve, dock, mouse, warranty, monitor
- gaming laptop -> mouse, headset, monitor, cooling pad
- school laptop -> backpack, sleeve, accidental damage plan

For pharmacy:

- medication -> eligible supporting product, only where clinically/policy safe
- skincare -> compatible cleanser/moisturizer/sunscreen
- no medical advice or contraindication claims without a governed health policy layer

For grocery:

- recipe ingredients -> missing ingredients
- pantry staples -> commonly replenished items
- loyalty offers -> only consented and promotion-valid

The scoring primitive is core. The companion taxonomy and policy constraints are adapter-owned.

## Inventory, Supplier Email, Deals, And Bounded Autonomy

Inventory-aware recommendation should be a first-class gate, not a narration detail.

### Product Availability Flow

```text
User asks product question
  -> QueryUnderstanding
  -> Candidate retrieval
  -> InventoryPort availability check
  -> Ranking suppresses unavailable items unless user asks for alternatives/preorder
  -> Why builder explains stock/ETA evidence
  -> Trace records inventory source and timestamp
```

### Supplier Email Automation

Automated supplier email is useful but should be bounded:

Allowed without human review:

- draft a restock email
- attach SKU, stock count, reorder threshold, recent demand signal
- route to an approved supplier contact
- queue for human approval or send only below low-risk thresholds

Requires human review:

- new supplier onboarding
- price negotiation
- non-standard MOQ
- unusually large reorder quantity
- regulated products
- confidential customer demand details
- any email containing PII
- discount/deal commitments

### Deals, Bundles, Discounts

Autonomous:

- surface active promotions from `PromotionPort`
- recommend eligible bundles already approved
- explain published discounts
- apply deterministic coupon if policy allows

Human review:

- create a new discount
- exceed margin threshold
- combine promotions not explicitly allowed
- price-match competitor data
- special corporate procurement pricing
- loyalty-based personalization without valid consent purpose

This is where ShopSquire can differentiate: the agent can be proactive, but the execution gate controls authority.

## Smarter Query Understanding

### Current Gap

The code has several partial query-understanding systems:

- `src/app/services/query_decomposer.py:148` defines `QueryPlan`.
- `src/app/flows/nqe.py:900` has the NQE refinement gate.
- `src/app/routers/recommend.py:12958` builds narration prompts near the end.
- `src/app/services/answer_composer.py:60` can compose deterministic answers.

They do not yet share one contract for:

- what the user asked
- what is known
- what is missing
- what can be inferred safely
- what needs a follow-up question
- what evidence is required before making a claim

### Recommended Contract

Add a `QueryUnderstanding` struct after flavour extraction is stabilized:

```python
class QueryUnderstanding(BaseModel):
    raw_query: str
    normalized_query: str
    intent: Literal["recommend", "compare", "availability", "support", "return", "deal", "bundle", "supplier", "other"]
    product_type: str | None
    use_case: str | None
    constraints: dict[str, Any]
    budget: dict[str, Any] | None
    image_relation: Literal["none", "on_topic", "adjacent", "off_topic"]
    safe_image_hints: list[str]
    known_slots: dict[str, Any]
    missing_slots: list[str]
    evidence_requirements: list[str]
    allowed_autonomy: list[str]
    escalation_reasons: list[str]
```

This should be produced deterministically where possible, then optionally refined by a small/generic LLM.

### Why This Improves NLP

The agent should not ask an LLM to "answer the user" from raw text. It should ask the LLM to help with one bounded job:

- restate the query
- extract missing constraints
- choose a clarifying question
- produce buyer-facing copy from already-selected evidence

That makes outputs more useful and less likely to hallucinate.

## Domain-Specific NQE

`src/app/flows/nqe.py` remains one of the main UX bottlenecks because it owns clarifying questions.

Hard-coded anchors:

- High school: `src/app/flows/nqe.py:540`
- University: `src/app/flows/nqe.py:578`
- Gaming: `src/app/flows/nqe.py:600`
- Corporate: `src/app/flows/nqe.py:639`
- Field priority/template map: `src/app/flows/nqe.py:909`

Recommendation:

Move these to an NQE profile pack:

```json
{
  "nqe": {
    "questions": [
      {
        "id": "school_activity",
        "when": {"intent": "recommend", "use_case": "school"},
        "prompt": "What will they use it for most?",
        "options": [...]
      }
    ],
    "priority": ["use_case", "budget", "portability", "performance"]
  }
}
```

For electronics, keep school/university/corporate/gaming. For pharmacy, questions might be about product category, format, allergies, prescription constraints, or whether the query requires pharmacist review. For grocery, questions might be household size, dietary preference, brand substitution, or delivery window.

Do not make this LLM-first. The LLM can paraphrase the selected question, but the selected question should be policy/profile-driven.

## Image + Text Reasoning

### Current Problem

`src/app/services/cv_triage_basic.py:109` uses binary relevance. `src/app/routers/recommend.py:732` extracts safe image hints from hard-coded electronics terms.

Binary relevance is too crude:

- User uploads laptop image and asks "bag for this" -> adjacent, not off-topic.
- User uploads apple image and asks "gaming laptop $1300-$1800" -> off-topic, recommendation should ignore image for ranking.
- User uploads MSI laptop with QR/SSN/prompt-like text and asks for a laptop -> on-topic product hint, unsafe raw payload quarantined.
- User uploads damaged product photo for a return -> on-topic for returns, not necessarily recommendation.

### Recommended 3-State Model

```text
on_topic:
  image product type matches requested product type
  safe hints can influence ranking

adjacent:
  image product type is related to requested accessory/bundle/compatibility question
  image can inform compatibility, not override text intent

off_topic:
  image does not support the text query
  ignore image for ranking, continue text/catalog path, warn user if needed
```

### Deterministic First

The first pass should be CPU-safe:

- file type and size validation
- perceptual hash
- safe label/category classifier
- OCR/QR quarantine
- profile-backed product type mapping
- image/text relation decision

Only escalate to VLM when:

- deterministic labels are ambiguous
- image is material to a return/damage claim
- image is material to compatibility
- security triage requires deeper analysis

### Where To Change

- Replace hard-coded relevance in `src/app/services/cv_triage_basic.py:109`.
- Replace hard-coded safe hint extraction in `src/app/routers/recommend.py:732`.
- Add StoreProfile slots for `cv_product_type_rules`, `adjacent_product_relations`, and `unsafe_visual_indicators`.
- Carry `image_relation` into `QueryUnderstanding`, recommendation trace, and buyer-facing note.

## Deterministic, Generic LLM, And Tenant LLM Boundaries

### Deterministic Core

These should be deterministic and controlled by ShopSquire core:

- stock eligibility
- price/budget filtering
- discount eligibility
- refund/return eligibility
- fraud and policy gates
- supplier action gating
- retrieval source status
- final claim validation
- audit and trace writing

No tenant model should bypass these.

### Generic LLM

Use a generic LLM for:

- query restatement
- intent classification fallback
- extracting loose constraints
- choosing among approved NQE questions
- summarizing evidence into natural buyer-facing copy

The LLM should receive structured evidence, not unrestricted tool access.

### Tenant/BYO LLM

Tenants may bring:

- a custom small LLM for domain language
- a custom VLM/captioner for product images
- trained embeddings or rerankers
- policy configuration
- catalog taxonomy

But BYO models should be plugged into interpretation and scoring ports only. They should not:

- approve refunds
- change prices
- send supplier emails
- execute discounts
- override stock status
- suppress security alerts
- rewrite audit traces

Commercial framing:

> Bring your model, catalog, and policies. You cannot bring a policy bypass.

## CPU-First And GPU-On-Demand Architecture

The current direction should reduce GPU reliance, not increase it.

### CPU Always-On Pool

Run these cheaply on CPU VMs:

- request normalization
- StoreProfile loading
- deterministic query decomposition
- regex/profile extraction
- SQL/catalog retrieval
- cached embedding lookup
- inventory checks
- policy gates
- RRF/candidate fusion
- answer finalizer
- deterministic `answer_composer.py`
- trace logging
- NQE selection

`src/app/services/answer_composer.py:1` is a good primitive for this path because it can produce useful buyer-facing text without an LLM.

### GPU Autoscale Pool

Use GPU only for:

- VLM captioning
- OCR/vision security when needed
- batch visual index builds
- larger LLM narration/reasoning
- offline embedding generation if local embedding model requires it

### Immediate Cost Fixes

- Align `src/app/services/llm_provider.py:13` with `config/ml/tier_ladder.json:19` so medium is `qwen3:14b` unless intentionally overridden.
- Move complexity keywords out of `llm_provider.py:75` and into profile packs.
- Add telemetry for selected model tier, reason, latency, and whether CPU deterministic composition was enough.
- Make "catalog/budget/in-stock recommendation" a no-LLM default path.

## V2 Pipeline: Shadow Metrics Or Real Fusion

`RECOMMEND_PIPELINE_V2` currently runs shadow-only at `src/app/routers/recommend.py:6369`.

That is acceptable only if it produces actionable parity data. Today it records:

- elapsed ms
- count
- top SKUs
- error string
- trace event

It still needs:

- top-k overlap with monolith results
- budget adherence
- stock adherence
- product type adherence
- brand/image conflict behavior
- source status comparison
- reason-code/evidence comparison
- latency percentile by leg
- typed empty/error distinction

Do not cut over V2 until these metrics exist. If the team wants V2 to affect user results now, then make it true candidate fusion behind a feature flag and compare against monolith output in the same response trace.

## `recommend.py` Shrink Plan

Current state:

- `src/app/routers/recommend.py` is about 14,078 lines.
- The main `suggest()` route starts at `src/app/routers/recommend.py:6287`.
- The next route starts at `src/app/routers/recommend.py:13984`.
- That makes `suggest()` roughly 7,700 lines by itself.

Line count is not the primary business metric, but it is now hurting safe change velocity.

### Target

Get `suggest()` under 2,000 lines and `recommend.py` under 7,000 lines.

This is appropriate, but only if done by stage extraction with characterization tests. Do not do a cosmetic split that preserves hidden global state and route-level coupling.

### Extraction Order

#### Stage 1: Image Hint And Multimodal Context

Move:

- `src/app/routers/recommend.py:716` safe image brand/category constants.
- `src/app/routers/recommend.py:732` `_safe_image_hints_for_fast_path`.
- `src/app/routers/recommend.py:8490` GPU assumption checks.
- `src/app/routers/recommend.py:8505` brand aliases.
- `src/app/routers/recommend.py:8524` brand label patterns.
- `src/app/routers/recommend.py:8656` cross-modal brand conflict.

New file:

- `src/app/services/recommend_image_hints.py`

Why first:

- It is self-contained.
- It improves ASUS/MSI safe image hint behavior.
- It is needed for image relation and vertical portability.

Tests:

- ASUS image hint ranks ASUS-relevant results when text is compatible.
- Unrelated apple image does not pollute laptop ranking.
- Adjacent laptop image + bag query does not force laptop recommendation.
- Unsafe OCR/QR remains quarantined.

#### Stage 2: Budget And Brand Constraints

Move:

- `src/app/routers/recommend.py:2548` `_assess_budget_fitness`.
- `src/app/routers/recommend.py:2596` `_build_minimum_recommended_tiers`.
- `src/app/routers/recommend.py:4998` `_build_brand_budget_answer`.
- `src/app/routers/recommend.py:5225` `_build_brand_budget_answer_v2`.
- `src/app/routers/recommend.py:8600` brand price floor profile reader.

New file:

- `src/app/services/recommend_budget_advisor.py`

Why:

- Budget reasoning is core to usefulness.
- Brand price floors already partially use StoreProfile.
- This helps with "why is this relevant?" because budget fit becomes explicit evidence.

Tests:

- High-budget query does not recommend low-end mismatch.
- Low-budget premium brand query gives honest minimum-tier answer.
- Pharmacy/grocery profile can disable electronics floor behavior.

#### Stage 3: NQE Stage

Move route glue that decides whether to ask clarifying questions out of `recommend.py`.

Likely anchors:

- `src/app/routers/recommend.py:1766`
- `src/app/routers/recommend.py:3472`
- `src/app/routers/recommend.py:3542`
- `src/app/routers/recommend.py:12486`

New file:

- `src/app/services/recommend_nqe_stage.py`

Why:

- NQE is a stage, not route code.
- Makes question decomposition easier to test.

Tests:

- High school, university, and corporate laptop queries trigger correct questions.
- Complete queries skip NQE.
- Pharmacy profile does not ask laptop questions.

#### Stage 4: Narration And Why

Move:

- `src/app/routers/recommend.py:4249` `_build_persona_prompt_context`.
- `src/app/routers/recommend.py:4560` `_summarize_results`.
- `src/app/routers/recommend.py:5923` `_deterministic_assistant_message`.
- `src/app/routers/recommend.py:12958` LLM narration block.

New files:

- `src/app/services/recommend_narration_stage.py`
- or extend `src/app/services/answer_composer.py`

Why:

- Narration is where unsupported claims appear.
- It should depend on structured evidence, not scattered locals.

Tests:

- No unsupported claim from LLM narration.
- Claims must cite product fields, inventory, price, or policy evidence.
- Image-off-topic note is accurate.
- Deterministic fallback is useful without LLM.

#### Stage 5: Result Finalization

Move:

- final response shaping
- finalizer invocation
- off-category demotion
- source statuses
- trace payload assembly

Likely anchors:

- `src/app/routers/recommend.py:12900`
- `src/app/routers/recommend.py:13968`

New file:

- `src/app/services/recommend_result_stage.py`

Why:

- Finalization is a stable contract boundary.
- It makes V2 parity easier.

Tests:

- Payload schema parity before/after extraction.
- Decision trace fields preserved.
- Source errors are visible as partial failures.

### Expected Outcome

After these stages, `suggest()` should drop below 3,000 lines. After retrieval/fusion is cut over to `recommend_pipeline.py`, `recommend.py` can realistically fall below 7,000 lines.

Do not chase the exact line count before source-status, profile, NQE, and narration contracts are stable.

## Silent Fails And Observability

Measured current broad patterns:

- About 4,887 `except Exception` matches under `src/app`.
- About 155 `return []` matches under `src/app`.
- About 99 debug logging calls under `src/app`.

Critical surfaces:

- `src/app/routers/recommend.py` has hundreds of broad exception catches.
- `src/app/services/orchestrator.py` remains a large silent-fail risk.
- `src/app/services/checkout_upsell.py` catches and falls back in commercially important paths.
- `src/app/services/recommend_pipeline.py` has timeout wrappers but leg errors still often return empty structures.
- `src/app/services/candidate_retriever.py` records metrics, but main user traces still need typed source statuses.

### Do Not Fix All Broad Exceptions At Once

Prioritize request-critical paths:

1. candidate retrieval
2. inventory filter
3. V2 scatter legs
4. CV/image relevance
5. checkout upsell
6. final narration/finalizer
7. supplier and discount action paths

### Required Pattern

Replace silent empty returns with typed partial failures:

```python
SourceStatus(
    source="caption",
    outcome="error",
    count=0,
    latency_ms=42,
    error_type="TimeoutError",
    trace_id=trace_id,
)
```

Buyer-facing output should still degrade gracefully, but admin trace must distinguish:

- no products matched
- source timed out
- source errored
- source disabled
- source returned stale data

## Personalization, Privacy, And Customer Context

Personalization is useful, but it must be consented, purpose-limited, and explainable.

### What Data Agents May Use

Allowed with consent and clear purpose:

- current query
- current session product views
- current cart
- prior purchases
- loyalty tier/offers
- explicit preferences
- store region
- product availability at selected location

Higher-risk:

- inferred demographics
- sensitive health attributes
- third-party enrichment
- cross-site browsing
- long-term behavioral profiling
- employee/customer identity correlation

### Recommended Contract

Introduce `CustomerContextPort` with:

```python
class CustomerContext(BaseModel):
    user_id_hash: str | None
    consent_scope: list[str]
    region: str | None
    session_views: list[ProductView]
    cart: CartSnapshot | None
    purchase_history_summary: PurchaseHistorySummary | None
    loyalty_summary: LoyaltySummary | None
    forbidden_fields_removed: bool
    source_freshness: dict[str, str]
```

The recommender should not read raw customer data directly. It should receive a minimized, purpose-bound context envelope.

### Privacy Notes

GDPR/EU AI Act/privacy regimes differ by jurisdiction, but the design principle is stable:

- minimize data
- require consent/purpose
- avoid sensitive inference unless explicitly governed
- provide explanation and trace
- retain only what is needed
- support deletion/access requests
- separate recommendation from privileged action

For Australia, treat Privacy Act 1988 obligations seriously: notice, purpose limitation, data quality, security, access/correction, and cross-border disclosure controls. For critical infrastructure/SOCI-adjacent customers, add stricter operational logging, supplier-risk controls, and incident response hooks.

## Better Product Recommendations And "Why"

A better recommendation answer should be built from evidence:

```text
User asked:
  gaming laptop between 1300 and 1800

Known constraints:
  product_type=laptop
  use_case=gaming
  budget_min=1300
  budget_max=1800
  image_relation=off_topic or on_topic

Candidate evidence:
  price
  stock
  GPU
  RAM
  display refresh
  product type
  brand hint
  reviews/returns if available
  current promotion if eligible

Why:
  matches budget
  has dedicated GPU
  in stock
  better fit than excluded alternatives
  image was ignored/used only as safe hint
```

The "why" should not be generic persuasion. It should answer:

- Which part of the user's query does this product satisfy?
- Which constraints did it fail or partially satisfy?
- What data source supports that claim?
- What was not considered?
- Why were close alternatives ranked lower?

Potential files:

- `src/app/agents/why_builder.py`
- `src/app/agents/why_formatter.py`
- `src/app/agents/why_sources.py`
- `src/app/services/recommend_response_finalizer.py`
- `src/app/services/answer_composer.py`

These should consume structured evidence from `QueryUnderstanding` and candidate scoring, not scrape text from narration.

## External Data Platforms And Loyalty

For platforms similar to Everyday Rewards, Flybuys, Kroger, Nectar, Payback, Segment, mParticle, Snowflake, Databricks, or reverse-ETL pipelines:

Core should not know vendor-specific schemas.

Use adapters:

```text
Loyalty/CDP/Warehouse
  -> CustomerContextPort
  -> consent and purpose filter
  -> minimized context envelope
  -> recommender
```

Important caveat:

- Reverse ETL is often not real-time.
- Session/cart/inventory decisions need real-time ports.
- Warehouse-derived segments are useful for personalization, but stale for stock, pricing, or time-sensitive promotions.

## What Should Be Deterministic

Deterministic:

- product eligibility
- inventory
- price/budget math
- discount rules
- deal/bundle eligibility
- refund/return policy
- supplier email authority
- model tier routing floor/ceiling
- safe image quarantine
- source-status recording
- final claim guard

Interpreted by generic or tenant LLM:

- natural language restatement
- fuzzy use-case mapping
- free-text constraint extraction
- product explanation copy
- tone adaptation
- summarizing alternatives

Custom tenant model:

- domain synonyms
- product visual captions
- catalog-specific feature extraction
- localized phrasing
- taxonomy mapping

Never delegated to tenant model alone:

- policy bypass
- refund approval
- price changes
- supplier send authority
- discount creation
- hiding security warnings
- audit modification

## Roadmap Ordered To Avoid Scope Creep

### Phase 0: Lock The Baseline

Goal: make current behavior measurable before extraction.

Work:

- Add characterization fixtures for 10-15 representative recommendation queries.
- Add V2 parity metrics but keep shadow-only.
- Add strict StoreProfile missing-profile test.
- Add checkout upsell price-unit test.

Files:

- `tests/test_recommend.py`
- `tests/services/test_recommend_pipeline_parity.py`
- `tests/platform/test_store_profile_loader.py`
- `tests/services/test_checkout_upsell_price_guards.py`

Exit:

- Known baseline preserved.
- V2 can be judged by metrics, not impression.

### Phase 1: Fix Profile Ownership

Goal: remove config drift and unsafe fallback.

Work:

- Harden `store_profile.py`.
- Decide fate of `config/store_vocab.json`.
- Add profile APIs for taxonomy, NQE, CV, upsell, bundle, and complexity keyword packs.

Files:

- `src/app/platform/store_profile.py`
- `config/store_profiles/electronics.json`
- `config/store_profiles/pharmacy.json`
- `config/store_vocab.json`
- `tests/platform/test_agnostic_profile.py`

Exit:

- Pharmacy profile can load without electronics fallback leakage.
- Missing profile fails closed under strict mode.

### Phase 2: Product Taxonomy And Upsell

Goal: make commercial recommendation primitives vertical-safe.

Work:

- Move product taxonomy to StoreProfile/StoreTaxonomyPort.
- Update `product_classifier.py` to read the same source.
- Profile-drive `checkout_upsell.py`.
- Fix cents/dollars threshold bug.
- Move bundle rules to profile.

Files:

- `src/app/services/product_taxonomy.py`
- `src/app/services/product_classifier.py`
- `src/app/services/checkout_upsell.py`
- `src/app/services/upsell_engine.py`
- `src/app/services/bundle_pricing.py`
- `config/store_profiles/electronics.json`
- `config/store_profiles/pharmacy.json`

Exit:

- Electronics upsell still works.
- Pharmacy does not suggest electronics accessories.
- Bundle copy is no longer laptop-specific in core code.

### Phase 3: Vision 3-State

Goal: make image+text robust and portable.

Work:

- Implement `image_relation`.
- Replace binary relevance.
- Move safe image hint extraction out of `recommend.py`.
- Keep OCR/QR/prompt-like content quarantined.

Files:

- `src/app/services/cv_triage_basic.py`
- `src/app/services/recommend_image_hints.py`
- `src/app/routers/recommend.py`
- `config/store_profiles/electronics.json`
- `config/store_profiles/pharmacy.json`

Exit:

- on-topic, adjacent, and off-topic are trace-visible.
- Unrelated images do not influence ranking.
- Adjacent images inform accessory/compatibility queries without hijacking intent.

### Phase 4: NQE And QueryUnderstanding

Goal: make the agent ask smarter questions before LLM narration.

Work:

- Add `QueryUnderstanding`.
- Move NQE templates to profile.
- Make `query_decomposer.py` consume profile spec constraints dynamically, not import-time only.
- Feed `QueryUnderstanding` into why/narration.

Files:

- `src/app/services/query_decomposer.py`
- `src/app/flows/nqe.py`
- `src/app/core/schema.py`
- `src/app/services/recommend_nqe_stage.py`
- `src/app/agents/why_builder.py`
- `src/app/agents/why_formatter.py`
- `src/app/agents/why_sources.py`

Exit:

- High school, university, corporate, gaming queries recover.
- Non-electronics profiles do not ask electronics questions.
- LLM receives structured evidence and missing slots.

### Phase 5: CPU/GPU Model Ladder

Goal: lower cost and make latency claims defensible.

Work:

- Align medium default with tier ladder.
- Move complexity keyword packs to profile.
- Add tier telemetry.
- Make deterministic `answer_composer.py` the default for simple recommendation answers.

Files:

- `src/app/services/llm_provider.py`
- `config/ml/tier_ladder.json`
- `src/app/services/answer_composer.py`
- `src/app/observability/metrics.py`

Exit:

- Simple catalog queries avoid LLM.
- Medium tier is `qwen3:14b` unless explicitly overridden.
- GPU usage is measurable by request type.

### Phase 6: `recommend.py` Stage Extraction

Goal: reduce the route from a monolith to an orchestrator.

Work:

- Extract image, budget, NQE, narration, and result stages.
- Preserve response schema.
- Add per-stage timing spans.
- Expand no-flavour lint as modules are cleaned.

Files:

- `src/app/routers/recommend.py`
- `src/app/services/recommend_image_hints.py`
- `src/app/services/recommend_budget_advisor.py`
- `src/app/services/recommend_nqe_stage.py`
- `src/app/services/recommend_narration_stage.py`
- `src/app/services/recommend_result_stage.py`
- `tests/test_no_flavour_in_core.py`

Exit:

- `suggest()` below 3,000 lines.
- `recommend.py` below 7,000 lines after retrieval cutover.
- Tests prove old payload compatibility.

### Phase 7: Ports And Tenant Adapters

Goal: make ShopSquire portable to other ecommerce stores.

Work:

- Define port interfaces.
- Implement Shopify/Magento/Woo/custom adapters later.
- Add CustomerContextPort with consent gating.
- Add SupplierPort and PromotionPort behind execution gates.

Files:

- `src/app/ports/catalog.py`
- `src/app/ports/inventory.py`
- `src/app/ports/customer_context.py`
- `src/app/ports/promotion.py`
- `src/app/ports/supplier.py`
- `src/app/core/execution_gate.py`

Exit:

- Electronics is one adapter.
- A second vertical can be tested without touching core.

## Iterative Test Strategy

For every new extraction or feature:

1. Add characterization tests first.
2. Move one stage or one flavour slot.
3. Run old and new paths side-by-side.
4. Assert payload schema parity.
5. Assert trace fields are present.
6. Assert source statuses distinguish hit/empty/error/timeout.
7. Assert profile swap behavior with electronics and pharmacy.
8. Assert no unsupported narration claim.
9. Add no-flavour lint only after the module is clean.
10. Run latency smoke and compare p50/p95 for affected path.

### Suggested Test Files

| Area | Test file |
|---|---|
| StoreProfile strict mode | `tests/platform/test_store_profile_loader.py` |
| Agnostic profile proof | `tests/platform/test_agnostic_profile.py` |
| Product taxonomy profile | `tests/services/test_product_taxonomy_profile.py` |
| Checkout upsell price guards | `tests/services/test_checkout_upsell_price_guards.py` |
| Checkout upsell profile | `tests/services/test_checkout_upsell_profile_taxonomy.py` |
| Bundle profile rules | `tests/services/test_bundle_pricing_profile_rules.py` |
| CV image relation | `tests/services/test_cv_triage_profile_relevance.py` |
| QueryUnderstanding | `tests/services/test_query_understanding_contract.py` |
| NQE profile templates | `tests/flows/test_nqe_profile_templates.py` |
| LLM tier ladder | `tests/services/test_llm_provider_tier_ladder.py` |
| V2 parity | `tests/services/test_recommend_pipeline_parity.py` |
| Source status | `tests/services/test_recommend_pipeline_source_status.py` |
| No-flavour lint | `tests/test_no_flavour_in_core.py` |

## What To Tell GPT-5.5 For Code Review

Give GPT-5.5 this review request:

```text
Please review the ShopSquire agnostic-core migration with focus on scope control.

Primary questions:
1. Is the proposed StoreProfile/StoreTaxonomyPort boundary correct, or should product taxonomy remain a separate port?
2. Is `store_profile.py` missing-profile fallback to electronics acceptable only for demo/dev, and should production fail closed?
3. Does `checkout_upsell.py:668-672` compare cents to dollar-like thresholds? If yes, propose the minimal safe fix and tests.
4. Should `config/store_vocab.json` be removed, generated, or retained as legacy fallback?
5. Is `llm_provider.py` medium default inconsistent with `config/ml/tier_ladder.json`, and should qwen3:14b be the default medium tier?
6. What is the smallest QueryUnderstanding contract that improves NQE and narration without pulling Phase E forward too early?
7. Is the image_relation design enough for on-topic / adjacent / off-topic multimodal recommendations?
8. Before V2 cutover, are top-k overlap, budget adherence, stock adherence, and source status metrics sufficient parity gates?
9. Which `recommend.py` stage extraction has the lowest regression risk?
10. Are there hidden coupling points in `orchestrator.py`, `recommend.py`, or frontend trace rendering that this plan misses?

Please avoid recommending a rewrite. Prioritize the smallest safe PR order.
```

## Recommended Next PR

Do not start with QueryUnderstanding or a full `recommend.py` split.

Start with this narrow PR:

1. Harden StoreProfile strict missing-profile behavior.
2. Add profile-backed StoreTaxonomy accessors.
3. Move product taxonomy constants out of `product_taxonomy.py`.
4. Fix checkout upsell price guard units.
5. Add electronics/pharmacy tests proving no gaming accessories appear for pharmacy.

Why this PR first:

- It attacks a real portability blocker.
- It improves revenue-critical upsell correctness.
- It reduces silent wrong behavior.
- It is smaller than touching NQE, narration, and the main route.
- It gives the team a repeatable slot-by-slot migration pattern.

## Dirty Tree At Review Time

Observed dirty tree before this report was added:

```text
 M config/security/cv_playbooks.json
?? docs/SHOPSQUIRE_CLAUDE_HANDOFF_DAVID_OPUS48_2026-06-18.md
?? docs/SHOPSQUIRE_CORE_ADAPTER_DATA_PLATFORM_ROADMAP_2026-06-18.md
?? docs/SHOPSQUIRE_OPUS48_AGNOSTIC_COMMERCE_AI_ROADMAP_2026-06-18.md
```

This report adds:

```text
?? docs/SHOPSQUIRE_AGNOSTIC_CORE_INDEPENDENT_REVIEW_2026-06-18.md
```

Commit recommendation:

- Commit roadmap/review docs together if they are intended handoff artifacts.
- Do not commit `config/security/cv_playbooks.json` until it is reviewed; it may be unrelated generated or experimental security config drift.
- Do not discard anything automatically. Inspect diffs first, especially security config.

## Final Position

ShopSquire did not waste time. The strongest assets are:

- policy-bounded commerce decisions
- traceable recommendation evidence
- multimodal quarantine model
- rules/catalog fast path
- V2 retrieval/fusion direction
- StoreProfile scaffold
- deterministic finalizer/answer composer path

The delta to pursue is not "more chatbot." It is:

- faster CPU-first recommendations
- profile-backed vertical portability
- safer image/text reasoning
- typed partial failures instead of silent empties
- consented customer context
- traceable why explanations
- bounded autonomous actions for inventory, deals, supplier drafts, and escalation

The work should stay ordered. First make vertical flavour declarative and tested. Then make the agent smarter with QueryUnderstanding. Then cut over V2. Then shrink the route aggressively.
