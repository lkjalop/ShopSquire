# ShopSquire Core/Adapter Data Platform Roadmap

Date: 2026-06-18  
Scope: verify `SHOPSQUIRE_AGNOSTIC_ROADMAP_FOR_GPT55_2026-06-18.md`, assess what belongs in ShopSquire core versus ecommerce/customer-data adapters, and define the next implementation path for an electronics/laptop-first adapter.

## Executive Position

The agnostic-core direction is correct, but the line needs to be made enforceable in code.

ShopSquire should not become a Woolworths/Flybuys/Kroger/Nectar-style loyalty platform, a CDP, or a warehouse analytics product. Those systems should feed ShopSquire through bounded adapters. ShopSquire's durable product is the commerce decision layer:

- parse the buyer's text/image query into a structured, policy-bounded request;
- retrieve and rank products from store-owned catalog, inventory, context, and approved preference signals;
- explain why each recommendation is relevant;
- decide what can be automated and what must be escalated;
- record the evidence, timing, policy gates, model use, and trace.

The key change is to treat electronics/laptops as the first `StoreProfile`/adapter pack, not as the core product. The core should own mechanisms. The electronics adapter should own vocabulary, brands, specs, fit rules, accessory/bundle logic, and domain-specific NQE questions.

## Verification Summary

I verified the GPT-5.5 roadmap claims against the repository. Most strategic claims hold, but a few need correction or tighter wording.

### Verified

- The latest roadmap exists at `docs/SHOPSQUIRE_AGNOSTIC_ROADMAP_FOR_GPT55_2026-06-18.md`.
- The last 8 commits in the current branch match the roadmap's general sequence:
  - `56d730d` roadmap commit
  - `ed2126c` electronics StoreProfile scaffold
  - `935bbc3` execution-gate facade
  - `fceeca7` P2 schema hardening/autonomy tables
  - `af10f32` finalizer pipeline
  - `3d733b9`, `fd7b523`, `cd91263` finalizer extraction commits
- `src/app/routers/recommend.py` is still a large monolith at 14,689 lines.
- `src/app/services/orchestrator.py` is a second major risk surface at 4,009 lines.
- `frontend/src/components/DecisionTrace.tsx` is 3,055 lines.
- `frontend/src/App.tsx` is 2,225 lines.
- `src/app/services/recommend_pipeline.py:250` has `asyncio.gather(*scatter_tasks, return_exceptions=True)` without a timeout.
- `src/app/services/recommend_pipeline.py:285-288` has another unbounded `asyncio.gather`.
- `src/app/services/recommend_response_finalizer.py:214-236` now centralizes the final response payload pipeline.
- `src/app/routers/recommend.py:14007-14008` calls `_compose_compound_if_needed(...)` and then `finalize_response_payload(...)` near the true exit.
- `src/app/policy/execution_gate.py:80-97` provides a `decide(...)` facade that logs policy decisions and fails closed to human review when the lower-level authorization engine fails.
- `tests/security/test_execution_gate.py:28-34` asserts each decision writes one `policy_evaluation_log` row.
- `config/store_profiles/electronics.json` exists and already contains the first electronics profile scaffold.

### Corrections

- The roadmap's "0 flavour in NQE/scatter-gather" claim should be narrowed. The main swarm/scatter-gather mechanism is mostly generic, but electronics literals still exist in NQE-adjacent code:
  - `src/app/flows/nqe.py:176-177` hard-codes brands in `_detect_brand_request`.
  - `src/app/flows/nqe.py:574`, `src/app/flows/nqe.py:642`, and `src/app/flows/nqe.py:910-960` still carry laptop/product-question IDs and templates.
  - `src/app/services/query_decomposer.py:68-83` still owns electronics use-case patterns.
  - `src/app/services/query_decomposer.py:134-191` still owns electronics spec extraction.
- `src/app/platform/store_profile.py` does not exist yet. The scaffold exists in config, but there is no canonical loader/validator module.
- The "missing Postgres migration" should be stated precisely: the current SQLAlchemy bootstrap has autonomy tables and product columns, but Alembic parity for the newer product attributes/profile columns still needs confirmation and likely migration work.
- The finalizer is not yet the only writer. `src/app/routers/recommend.py:233-242` still imports several private finalizer helpers, and `_demote_off_category(...)` is still called in pre-exit branches around `src/app/routers/recommend.py:5545`, `10316`, `12913`, `12931`, and `13630`.

## External Data Research: What Changes Core Logic?

The research answer is: loyalty/CDP/warehouse systems should change the adapter contracts and evidence model, not the recommendation core.

### Loyalty And Retail Media Platforms

Everyday Rewards, Flybuys, Kroger/84.51, Nectar360, and Coles360 show the same pattern: high-value first-party customer, purchase, offer, and audience data sits outside the shopping assistant but can materially improve relevance.

- Everyday Rewards/Woolworths privacy material describes collection and use of member identity, contact, date-of-birth, transaction, purchases, points, and rewards information. This is powerful personalization data but privacy-sensitive and consent-bound. Sources: [Everyday Rewards privacy](https://www.everyday.com.au/privacy.html), [Everyday Rewards collection notice](https://www.everyday.com.au/privacy/policy-documents/collection-notice.html), [Woolworths Group Privacy Policy PDF](https://www.woolworthsgroup.com.au/content/dam/wwg/privacy/Woolworths_Group_Privacy_Policy_20240709.pdf).
- Flybuys says it collects, uses, and discloses personal information to provide, administer, improve, and personalise the program, products, services, and offers. Its older PDF also describes sharing with program partners and using de-identified data for advertising products. Sources: [Flybuys privacy policy](https://experience.flybuys.com.au/policies/privacy-policy/), [Flybuys privacy PDF](https://register.flybuys.com.au/cdn/pdf/FLYBUYS-PrivacyPolicy-NOV2021.pdf).
- Coles360 positions itself as a retail media and customer insight platform built around Coles customer insight and media activation. Source: [Coles360](https://www.coles.com.au/coles360).
- 84.51, Kroger's retail data science company, describes first-party retail data, insights, and tools such as Stratum and Collaborative Cloud. Databricks' customer story says 84.51 uses first-party retail data from more than 62 million U.S. households through Kroger Plus. Sources: [84.51](https://www.8451.com/), [Databricks 84.51 customer story](https://www.databricks.com/customers/8451).
- Nectar360 describes media services backed by shopper insights from 19 million Nectar customers and large-scale Sainsbury's data. Source: [Nectar360 media services](https://www.nectar360.co.uk/what-we-do/media-services/).

Implication for ShopSquire:

- Do not put loyalty logic in core ranking code.
- Add a `CustomerContextPort` that returns bounded, consent-filtered, provenance-labeled customer context.
- Add an `OfferEligibilityPort` for discounts, coupons, points, bundle eligibility, and partner offers.
- Add a `ConsentPort` and `DataUsePolicy` check before any customer trait is used in retrieval, ranking, narration, or automation.
- Add freshness and source metadata to every customer-context feature.

### CDP Platforms

Segment and mParticle show the right integration shape for live profile context.

- Segment's Profile API lets systems read user/account data such as external IDs, traits, and events. Source: [Segment Profile API](https://www.twilio.com/docs/segment/unify/profile-api).
- mParticle's Profile API exposes identities, user attributes, audience memberships, and user profile data. Its docs also describe real-time profile updates and consent-based data privacy controls. Sources: [mParticle Profile API](https://docs.mparticle.com/developers/profile-api), [mParticle user profiles](https://docs.mparticle.com/guides/customer-360/profiles/overview/), [mParticle data privacy controls](https://docs.mparticle.com/guides/data-privacy-controls/).

Implication for ShopSquire:

- CDP data is useful for "knows this buyer usually buys business laptops" or "prefers Lenovo and has a student segment", but it must be optional, scoped, and auditable.
- The hot path should not depend on CDP availability. Use cached profile snapshots with TTL, and fall back to non-personalized ranking on timeout or denied consent.
- Narration should disclose personalization at a useful level: "I prioritized lighter laptops because your saved preference says portability matters." It should not expose sensitive segments.

### Warehouse, Lakehouse, And Reverse ETL

Warehouses and reverse-ETL systems are strong for precomputed personalization and weak for low-latency live decisions unless data is materialized.

- Hightouch describes syncing records from a warehouse/source to downstream tools without custom scripts or CSVs. Source: [Hightouch Reverse ETL](https://hightouch.com/platform/reverse-etl).
- Fivetran describes managed reverse ETL/Activations from a centralized source of truth to business tools. Source: [Fivetran Activations](https://fivetran.com/docs/activations).
- Snowflake Cortex Analyst provides a REST API for natural language over structured Snowflake data, but this should not become the default buyer-path recommender. Source: [Snowflake Cortex Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst).
- Snowflake dynamic tables support incremental/full/AUTO refresh modes, which is useful for feature freshness but not guaranteed live request latency. Source: [Snowflake dynamic tables](https://docs.snowflake.com/en/user-guide/dynamic-tables/overview).
- Databricks AI Search provides vector search integrated with Databricks governance/productivity tools. Source: [Databricks AI Search](https://docs.databricks.com/gcp/en/ai-search/ai-search).
- Athena Federated Query can query across relational, non-relational, object, and custom data sources. Source: [AWS Athena Federated Query](https://docs.aws.amazon.com/athena/latest/ug/federated-queries.html).

Implication for ShopSquire:

- Warehouse/lakehouse data should be pulled into a local read model or feature store, not queried synchronously during the buyer's recommendation request.
- Reverse ETL is not a real-time decision fabric. Treat it as a feature sync path with explicit freshness timestamps.
- Add `FeatureFreshness` to the customer context envelope and block or down-weight stale personalization in high-risk decisions.

### Product And Marketplace APIs

Electronics/laptop stores will often need external catalog, availability, and attribute normalization sources.

- Best Buy's developer API exposes products, stores, categories, and product attributes through official API endpoints. Sources: [Best Buy Developer Portal](https://developer.bestbuy.com/), [Best Buy API docs](https://bestbuyapis.github.io/api-documentation/).

Implication for ShopSquire:

- External product APIs should be `CatalogPort` or `MarketDataPort` adapters.
- Availability should come from a trusted inventory adapter, not from an LLM narration step.
- Marketplace data can enrich search, but only store-owned catalog and inventory should drive purchase availability unless policy allows external recommendations.

## Core Versus Adapter Boundary

### Keep In Core

These should be product/category/store agnostic:

- `QueryEnvelope`: normalized text, safe image hints, trust labels, conversation context references, locale, currency, tenant, and user consent state.
- `QueryPlan`: intent, constraints, entities, ambiguity, required evidence, required clarifying questions.
- `EvidenceBundle`: catalog hits, inventory state, customer-context features, offer eligibility, prior-session references, image hints, policy results, model outputs, provenance.
- `RecommendationCandidate`: product ID, score components, constraints satisfied/missed, availability, risk flags, evidence IDs.
- `WhyPayload`: concise relevance explanation, data sources used, caveats, rejected alternatives, missing evidence.
- `ActionProposal`: recommend, ask clarifying question, reserve item, request supplier quote, generate supplier email draft, offer bundle, apply eligible discount, escalate.
- `ExecutionGate`: one entry point for privileged actions, audit logging, segregation of duties, human-review fallback.
- `AdapterPolicy`: timeouts, freshness, consent scope, trust level, allowed use, redaction, retention.
- `StoreProfile`: data-driven vocabulary/spec/use-case/ranking configuration.
- Observability: latency spans, per-adapter metrics, cache hit/miss, fallback reason, timeout reason, policy decision ID.

### Keep In Electronics/Laptop Adapter

These should move out of core code and into `config/store_profiles/electronics.json` or `src/app/adapters/electronics/*`:

- Brand aliases and brand regexes.
- Safe image brand hint allowlist.
- Brand price floors.
- Product-type taxonomy: laptop, monitor, desktop, keyboard, mouse, accessory.
- Spec extraction: RAM, storage, GPU, CPU, display size, refresh rate, weight, battery, ports, OS.
- Use-case mappings: gaming, school, university, corporate, creator, travel, programming, CAD, AI/ML.
- Constraint defaults: student budget, corporate manageability, gaming GPU floor, creator display/GPU needs.
- Accessory compatibility: USB-C docks, monitors, laptop bags, chargers, keyboards, mice.
- Bundle rules: laptop + sleeve + mouse; gaming laptop + headset; business laptop + dock + monitor.
- NQE question sets and domain templates.
- Vision vocabulary: laptop brand/logo hints, model badges, ports, keyboard layouts, screen damage, serial/asset-tag handling.
- Product-specific caveats: refurbished/open-box, warranty, regional keyboard, charger wattage, GPU TGP ambiguity.

### Keep In Store/Tenant Adapter

These are not electronics-general. They belong to the merchant implementation:

- Inventory source of truth and stock thresholds.
- Supplier contacts and reorder policies.
- Discount authority, coupon eligibility, margin floors, bundle approval rules.
- Shipping providers and fulfilment statuses.
- Returns/refunds policy.
- Loyalty program integration and consent model.
- CRM/CDP/customer identity mapping.
- Data residency and retention policy.
- Human escalation queues and approval roles.
- Brand partnerships and sponsored ranking constraints.

## Current File Anchors And Required Work

### StoreProfile Loader

Status: scaffold exists; loader missing.

- Current scaffold: `config/store_profiles/electronics.json`.
- Missing file: `src/app/platform/store_profile.py`.

Build:

- `src/app/platform/store_profile.py`
  - Load profile JSON by profile ID.
  - Validate required slots.
  - Normalize regex/pattern config.
  - Cache immutable profile objects.
  - Expose `get_store_profile(profile_id: str = "electronics") -> StoreProfile`.
  - Fail closed on invalid config in CI/test; fail open to default profile only in demo/dev mode if explicitly configured.

Tests:

- `tests/platform/test_store_profile_loader.py`
  - Loads `electronics`.
  - Rejects malformed profile.
  - Preserves slot names and metadata.
  - Does not mutate cached profile between tests.

Business impact:

- This is the first enforceable cut between core and category logic.
- It makes onboarding a new vertical a config/adaptor exercise instead of another `recommend.py` fork.

### Brand Price Floors

Status: duplicated concept exists in profile and code.

- Profile slot: `config/store_profiles/electronics.json:27`.
- Code still owns floors: `src/app/routers/recommend.py:8608-8626`.

Build:

- Add a profile-backed reader for `brand_price_floors_usd`.
- Change the ranking/fallback code to call the reader.
- Keep existing values as characterization baseline.
- Remove `_BRAND_PRICE_FLOORS` only after tests pass under both default and explicit electronics profile.

Tests:

- `tests/routers/test_recommend_brand_price_floors_profile.py`.
- Characterization: same outputs before and after for ASUS/MSI/Lenovo/Dell budget queries.
- Regression: ASUS safe image brand hint should lift ASUS candidates in fallback results without forcing irrelevant products.

Business impact:

- Prevents electronics brand economics from leaking into non-electronics stores.
- Improves laptop query relevance while keeping the product engine portable.

### Brand Labels And Safe Image Hints

Status: still in `recommend.py`.

- Safe image brands: `src/app/routers/recommend.py:716-748`.
- Brand aliases: `src/app/routers/recommend.py:3212-3214`.
- Supported image brand hints: `src/app/routers/recommend.py:3233`.
- Label patterns: `src/app/routers/recommend.py:8535-8560`.

Build:

- Move brand alias/pattern config into StoreProfile.
- Split "safe image hint extraction" from "brand ranking boost".
- Require image-derived brand hints to be labeled as `safe_image_hint`, never as user instruction.
- Add an evidence ID for every applied image hint.

Tests:

- ASUS laptop image + "gaming laptop 1300-1800" should prefer ASUS only when ASUS candidates also satisfy price/use-case constraints.
- Unrelated image + text query should not override text intent.
- Image OCR/QR/prompt text should not reach ranking as instruction.

Business impact:

- Fixes buyer-visible relevance failures.
- Supports the security narrative that images are evidence, not authority.

### Query Decomposition

Status: core parser still owns electronics assumptions.

- Use-case patterns: `src/app/services/query_decomposer.py:68-83`.
- Spec extraction: `src/app/services/query_decomposer.py:134-191`.

Build:

- Introduce `decompose(query, *, profile, safe_image_hints=None, customer_context=None)`.
- Move use-case and spec patterns into `StoreProfile`.
- Return a structured `QueryPlan` with:
  - `intent`
  - `product_type`
  - `use_case`
  - `budget`
  - `hard_constraints`
  - `soft_preferences`
  - `ambiguous_slots`
  - `evidence_requirements`
  - `clarifying_questions`

Tests:

- High school, university, corporate, gaming, creator, and travel laptop queries.
- Text-only and image+text variants.
- Non-electronics profile should not extract GPU/RAM as domain constraints unless its profile defines them.

Business impact:

- Better query understanding directly improves recommendation precision.
- The same core can support pharmacy, furniture, apparel, or grocery later.

### NQE Domain Questions

Status: NQE still contains electronics/domain-specific content.

- Brand detection: `src/app/flows/nqe.py:176-177`.
- Domain question/template map: `src/app/flows/nqe.py:574`, `642`, `910-960`.

Build:

- Move domain question IDs/templates into StoreProfile.
- Keep NQE as a generic mechanism:
  - identify missing slots;
  - ask the fewest useful questions;
  - avoid asking questions already answered by text, image hints, session context, or customer context;
  - prefer defaults when policy permits.

Tests:

- High school laptop query should ask about durability/weight/budget only if missing.
- University query should ask about course/workload only when not inferable.
- Corporate laptop query should ask about manageability/security/warranty only when the store profile marks them as relevant.

Business impact:

- Reduces buyer friction and improves "feels smart" interaction quality.
- Keeps the NQE engine reusable outside laptop retail.

### Scatter-Gather Timeout

Status: unbounded gather risk in the V2 path.

- `src/app/services/recommend_pipeline.py:250`.
- `src/app/services/recommend_pipeline.py:285-288`.

Build:

- Add per-leg timeout budgets.
- Wrap each leg in `asyncio.wait_for`.
- Return typed empty/error outcomes rather than raw exceptions.
- Emit metrics:
  - `shopsquire_retrieval_source_total{source,outcome}`
  - `shopsquire_retrieval_source_latency_seconds{source,outcome}`
  - `shopsquire_scatter_gather_timeout_total{source}`
- Include timeout and fallback reason in Decision Trace.

Tests:

- Hanging caption leg returns within request budget.
- Hanging CLIP leg does not block DB/catalog results.
- Timeout is visible in trace and metrics.

Business impact:

- Prevents silent hangs in the path intended to replace the monolith.
- Makes latency claims defensible.

### V2 Shadow Versus Fusion

Status: V2 is still shadow-only unless explicitly wired.

Build options:

1. True shadow metrics:
   - Run monolith and V2.
   - Compare top-k overlap, price/budget adherence, brand-hint adherence, availability, and "why" evidence.
   - Emit parity metrics and write decision trace diff.
2. True candidate fusion:
   - DB/catalog fast path remains authoritative for availability.
   - Caption-RAG and visual CLIP legs contribute candidates/evidence.
   - Fuse with RRF or weighted scorer.
   - Require final candidates to pass policy, stock, and product-type constraints.

Recommendation:

- Do true shadow metrics first.
- Cut over only after the parity harness proves no regression for laptop queries, image+text queries, and attack-image queries.

Files:

- `src/app/services/recommend_pipeline.py`.
- `src/app/routers/recommend.py`.
- `src/app/services/candidate_retriever.py`.
- `tests/services/test_recommend_pipeline_parity.py`.

Business impact:

- Avoids a hidden "compute and discard" system that costs latency/GPU without improving buyer results.
- Creates evidence for a safe cutover.

### Finalizer And Early Returns

Status: improved but not done.

- Finalizer entry: `src/app/services/recommend_response_finalizer.py:214-236`.
- True-exit call site: `src/app/routers/recommend.py:14007-14008`.
- Remaining private helper imports: `src/app/routers/recommend.py:233-242`.
- Remaining pre-exit calls: `src/app/routers/recommend.py:5545`, `10316`, `12913`, `12931`, `13630`.

Build:

- Route early `_with_trace(...)` returns through the finalizer.
- Stop importing private finalizer helpers into `recommend.py`.
- Make the finalizer the only place that shapes final answer text, product label dereference, price integrity, and off-category demotion.

Tests:

- Characterization for all early-return branches.
- Security challenge response still applies.
- No unsupported claim is added by narration/finalization.

Business impact:

- Reduces user-facing inconsistencies.
- Prevents one branch from saying "best for 4K gaming" while another branch does not have evidence for that claim.

### Orchestrator Risk Surface

Status: bigger silent-fail surface than `recommend.py` in practical terms.

- File: `src/app/services/orchestrator.py`.
- Size: 4,009 lines.
- `except` count: 241.

Build:

- Do not rewrite first.
- Add timing spans and error counters around major blocks.
- Replace silent `except` paths with typed outcomes in the highest-traffic branches.
- Move privileged actions to `execution_gate.decide(...)`.
- Add a small public `OrchestrationResult` structure before extracting modules.

Tests:

- Orchestrator "no silent success on exception" tests.
- Escalation branch tests.
- Timing span presence tests.

Business impact:

- Improves trustworthiness of automation.
- Reduces the risk that a failed agent silently looks like a valid commerce decision.

### Execution Gate Migration

Status: facade exists; callers remain.

- Facade: `src/app/policy/execution_gate.py:80-97`.
- Existing direct authorization call example: `src/app/agents/inventory_agent.py:998`.

Build:

- Migrate all privileged actions to `execution_gate.decide(...)`.
- Privileged actions include:
  - supplier email send;
  - supplier reorder request;
  - discount creation or application beyond explicit eligibility;
  - refund approval;
  - return exception approval;
  - inventory reservation;
  - manual price override;
  - customer notification with material promise;
  - admin/SOC escalation closure.

Business impact:

- Makes bounded autonomy real instead of aspirational.
- Supports segregation of duties and audit.

## Customer Context And Personalization Design

### New Core Contract

Create:

- `src/app/ports/customer_context.py`
- `src/app/ports/consent.py`
- `src/app/ports/offer_eligibility.py`
- `src/app/ports/catalog.py`
- `src/app/ports/inventory.py`
- `src/app/ports/feature_store.py`

Core structures:

```python
@dataclass(frozen=True)
class CustomerContext:
    subject_ref: str
    consent_scope: ConsentScope
    features: list[CustomerFeature]
    source: str
    source_freshness: datetime
    allowed_uses: set[str]
    provenance_id: str
```

```python
@dataclass(frozen=True)
class CustomerFeature:
    name: str
    value: str | int | float | bool | None
    confidence: float
    sensitivity: str
    allowed_uses: set[str]
    expires_at: datetime | None
```

Rules:

- No customer feature may influence ranking unless `allowed_uses` includes `recommendation`.
- No customer feature may influence discounting unless `allowed_uses` includes `offer_eligibility`.
- No sensitive feature may be surfaced in narration.
- No inferred feature should be stored permanently unless policy allows it.
- Every personalized recommendation must include an evidence/provenance ID in the trace.

### What To Personalize

Good personalization signals:

- explicit saved preferences;
- recent viewed products in the same session;
- cart contents;
- wishlist items;
- prior purchases, if consent allows;
- return/refund constraints, if relevant and consent allows;
- brand affinity, if non-sensitive and consented;
- price sensitivity band, if derived transparently and allowed;
- loyalty offer eligibility;
- inventory location/store pickup preference;
- accessibility preferences such as screen size or weight, if explicitly provided.

Avoid or escalate:

- sensitive traits;
- inferred age/health/disability/financial hardship;
- protected-class proxies;
- behavioral manipulation;
- undisclosed sponsored ranking;
- loyalty or credit data used to deny opportunity;
- personalization with stale or unprovenanced data.

### Buyer-Facing Narration

The agent should answer:

- "What did you ask for?"
- "Which constraints did I satisfy?"
- "Which products fit best?"
- "Why this product, using what evidence?"
- "What tradeoff should you know?"
- "What should happen next?"

Example:

> I prioritized laptops in your $1,300-$1,800 range with gaming-grade GPUs. The MSI option is strongest on GPU fit, the Lenovo option balances price and portability, and the ASUS option is only ranked higher when the image brand hint is combined with matching specs and stock availability.

Do not say:

> This is the best laptop for all AAA games at ultra settings.

Unless the data includes benchmark evidence, GPU model, TGP, resolution target, and game/quality assumption.

Business impact:

- Better explanations increase trust and conversion.
- Bounded claims reduce legal, support, and refund risk.

## Inventory, Supplier Email, Deals, Bundles, And Human Review

### Availability From Inventory Agent

The recommender should treat availability as a first-class hard constraint.

Core flow:

```text
QueryPlan
  -> Candidate retrieval
  -> InventoryPort availability check
  -> Candidate ranking
  -> WhyPayload includes stock/availability evidence
  -> ActionProposal
  -> ExecutionGate for any privileged action
```

Recommended inventory evidence:

- `in_stock`
- `available_quantity`
- `reserved_quantity`
- `warehouse_or_store_location`
- `eta_if_backordered`
- `supplier_reorder_threshold`
- `last_synced_at`
- `source`

### Supplier Email Automation

Automate only the draft by default.

Allowed without human review:

- generate supplier email draft;
- attach trace/evidence;
- suggest reorder quantity within approved reorder policy;
- queue email for review.

Allowed with gate and policy:

- send reorder email if:
  - supplier is approved;
  - SKU is approved;
  - reorder quantity is within min/max policy;
  - unit cost is within expected range;
  - no contract exception;
  - inventory data freshness is acceptable;
  - action is logged by `execution_gate.decide(...)`.

Must escalate:

- new supplier;
- changed payment/bank details;
- unusual quantity;
- price variance above threshold;
- missing stock freshness;
- ambiguous SKU;
- customer-specific promise like "will arrive by Friday";
- supplier email content generated from untrusted OCR/email text;
- any discount/reorder that crosses margin or policy limits.

### Deals And Bundles

Safe autonomous actions:

- show existing eligible deal;
- explain an existing bundle;
- apply a coupon explicitly eligible for the user/session;
- recommend compatible accessories with no discount promise;
- propose a bundle for staff approval.

Human review required:

- create a new discount;
- override price;
- combine offers outside policy;
- promise future price matching;
- approve margin-negative bundle;
- use loyalty/customer data in a way not covered by consent;
- hide cheaper options because of sponsored ranking unless clearly disclosed and allowed.

Business impact:

- This turns "agentic" into controlled commerce operations.
- It lets ShopSquire help sell more without silently giving away margin or creating operational promises.

## Latency And Wiring Concerns

### Hot Path Budget

Target path for laptop recommendation:

```text
normalize/scrub/query envelope        10-30 ms
query decomposition/profile parse     20-80 ms
catalog DB/filter retrieval           50-200 ms
inventory check                       50-200 ms
profile/cached customer context       10-100 ms
rank/fuse/finalize                    30-120 ms
LLM narration, if used                bounded or background
```

Rules:

- StoreProfile access must be local and cached.
- Inventory should be local DB/cache first, remote adapter second.
- CDP/loyalty calls should not block the hot path unless cached and budgeted.
- Warehouse queries should not run live in the buyer path.
- VLM/image analysis should run in parallel/background unless the image is essential to the query.
- Any external adapter must have timeout, circuit breaker, fallback, and trace-visible outcome.

### Latency Work Items

Files:

- `src/app/services/recommend_pipeline.py:250`
- `src/app/services/recommend_pipeline.py:285-288`
- `src/app/routers/recommend.py`
- `src/app/services/orchestrator.py`
- `src/app/services/candidate_retriever.py`
- `src/app/services/product_captioner.py`
- `src/app/services/visual_search.py`

Build:

- Add `RecommendationTimingSpan` or equivalent trace records around:
  - query parse;
  - NQE/decomposition;
  - DB retrieval;
  - visual retrieval;
  - caption retrieval;
  - inventory;
  - customer context;
  - ranking/fusion;
  - finalizer;
  - narration.
- Add adapter-level timeout metrics.
- Add request-level budget enforcement.
- Fail open to non-personalized, catalog-only results when customer/loyalty/CDP is unavailable.
- Fail closed for privileged actions when policy, inventory, consent, or supplier state is unavailable.

Business impact:

- Avoids false latency claims.
- Prevents high-value but slow personalization systems from degrading buyer experience.

## What Could Break

### Recommendation Quality

- Brand hints can overboost irrelevant products.
- Moving regexes into config can change extraction order.
- NQE can ask too many questions if profile slots are incomplete.
- Fallback ranking can regress when profile values are missing.
- Candidate fusion can rank visually similar but unavailable products.

Mitigation:

- Characterization tests before each extraction.
- Golden laptop query set with text-only and image+text variants.
- Top-k overlap and constraint-adherence metrics.

### Security

- OCR/email/loyalty text could become instructions if not wrapped in a trust envelope.
- Customer context could leak into narration.
- Supplier email automation could execute from untrusted content.
- Adapter credentials could cross tenant boundaries.

Mitigation:

- Parse-before-LLM contract.
- Trust label every external text field.
- Gate every privileged action through `execution_gate.decide(...)`.
- Add tenant-aware credential lookup and audit.

### Privacy And Compliance

- New customer context tables/adapters may be missed by export/delete flows.
- Loyalty/CDP data may be used beyond consent.
- Warehouse feature freshness may be unclear.
- Inferred preferences may become sensitive profiles.

Mitigation:

- Register each adapter in privacy export/delete inventory.
- Add `allowed_uses` and `source_freshness`.
- Store minimal derived features, not raw event streams.
- Trace why a feature was used without exposing sensitive values in the buyer UI.

### Data Model Drift

- SQLite bootstrap and Postgres/Alembic can diverge.
- Product attributes may exist in ORM but not migration.
- Adapter profile schema can drift from code expectations.

Mitigation:

- Add Alembic migration for product profile columns if missing.
- Add schema contract tests for both SQLite and Postgres paths.
- Add profile JSON schema validation.

### Frontend

- `frontend/src/App.tsx` and `frontend/src/components/DecisionTrace.tsx` are large enough that new fields can cause fragile rendering.
- New timing, adapter, customer-context, and policy fields need null guards.
- LLM/narration text sinks need CSP and safe rendering.

Mitigation:

- Extract Decision Trace tabs.
- Add strict payload type guards.
- Add Playwright smoke tests for trace rendering with missing/partial adapter fields.

## Staged Roadmap

### R0: Baseline And Guardrails

Goal: prove current behavior before extracting more logic.

Work:

- Keep `docs/SHOPSQUIRE_AGNOSTIC_ROADMAP_FOR_GPT55_2026-06-18.md` as historical roadmap.
- Use this document as the adapter/data-platform refinement plan.
- Run baseline tests:
  - `python -m compileall -q src/app`
  - `python -m pytest tests/services/test_finalizer_characterization.py tests/test_schema_contract.py tests/security/test_execution_gate.py -q`
- Capture baseline outputs for:
  - ASUS safe image hint;
  - high school laptop;
  - university laptop;
  - corporate laptop;
  - gaming laptop budget query;
  - unrelated/compromised image + text query.

Exit criteria:

- Baseline outputs stored as fixtures.
- Known failures documented rather than hidden.

### R1: StoreProfile Loader And First Reader

Goal: make the profile scaffold real without broad behavior change.

Files:

- Add `src/app/platform/store_profile.py`.
- Add `tests/platform/test_store_profile_loader.py`.
- Modify first call site in `src/app/routers/recommend.py:8608-8626`.

Work:

- Load `config/store_profiles/electronics.json`.
- Replace `_BRAND_PRICE_FLOORS` with profile-backed reader.
- Keep exact current values.
- Add characterization tests.

Exit criteria:

- ASUS/MSI/Lenovo/Dell ranking stays stable except for known intended ASUS fallback fix.
- No LLM/GPU dependency added.

### R2: Electronics Query Profile Extraction

Goal: remove laptop use-case/spec parsing from generic decomposition.

Files:

- `src/app/services/query_decomposer.py:68-83`
- `src/app/services/query_decomposer.py:134-191`
- `config/store_profiles/electronics.json`
- `tests/services/test_query_decomposer_profile.py`

Work:

- Add `profile` parameter to decomposition.
- Move use-case and spec regexes to profile.
- Return structured `QueryPlan`.

Exit criteria:

- High school, university, corporate, gaming, creator, and travel queries parse correctly.
- Non-electronics profile does not inherit laptop assumptions.

### R3: NQE Profile Questions

Goal: keep NQE mechanism generic while electronics owns domain questions.

Files:

- `src/app/flows/nqe.py:176-177`
- `src/app/flows/nqe.py:574`
- `src/app/flows/nqe.py:642`
- `src/app/flows/nqe.py:910-960`
- `config/store_profiles/electronics.json`
- `tests/flows/test_nqe_profile_questions.py`

Work:

- Move brand detection and domain question templates into profile.
- Add "do not ask if already answered" logic using QueryPlan/evidence.

Exit criteria:

- Fewer redundant questions.
- Same or better recommendation quality.

### R4: CustomerContextPort And Consent Gate

Goal: allow smarter personalization without baking loyalty/CDP/warehouse logic into core.

Files:

- Add `src/app/ports/customer_context.py`.
- Add `src/app/ports/consent.py`.
- Add `src/app/services/customer_context_service.py`.
- Update `src/app/routers/privacy.py`.
- Update `src/app/services/recommendations.py`.
- Update `src/app/services/checkout_upsell.py`.

Work:

- Implement a local/mock customer context adapter first.
- Add consent and allowed-use checks.
- Add freshness metadata.
- Feed context into ranking as optional evidence.
- Feed only safe summary into narration.

Exit criteria:

- Recommendations improve with consented context.
- Same query works with no context, denied consent, stale context, and adapter timeout.
- Privacy export/delete inventory includes customer context artifacts.

### R5: Inventory, Offers, Supplier Actions

Goal: connect recommendations to bounded commerce actions.

Files:

- Add/normalize `src/app/ports/inventory.py`.
- Add `src/app/ports/offer_eligibility.py`.
- Review `src/app/agents/inventory_agent.py:998`.
- Review existing supplier/email modules.
- Update `src/app/policy/execution_gate.py`.

Work:

- Inventory availability becomes hard evidence.
- Existing eligible deals can be shown automatically.
- New discount or supplier email send requires policy gate.
- Supplier email draft can be generated autonomously but sending is gated.

Exit criteria:

- Buyer sees stock-aware recommendations.
- Admin sees traceable supplier/deal actions.
- Human review triggers for risky inventory/deal cases.

### R6: Scatter-Gather Timeout And V2 Parity

Goal: make V2 safe to compare and eventually cut over.

Files:

- `src/app/services/recommend_pipeline.py:250`
- `src/app/services/recommend_pipeline.py:285-288`
- `src/app/services/candidate_retriever.py`
- `tests/services/test_recommend_pipeline_timeouts.py`
- `tests/services/test_recommend_pipeline_parity.py`

Work:

- Add per-leg timeouts.
- Add parity metrics.
- Add Decision Trace diff.
- Keep V2 shadow until parity is proven.

Exit criteria:

- No silent hang.
- V2 produces measurable top-k/constraint/availability/why parity.

### R7: Frontend Trace And UX

Goal: expose better reasons without cluttering buyer UI.

Files:

- `frontend/src/App.tsx`
- `frontend/src/components/DecisionTrace.tsx`
- `frontend/src/types/*` if present or new typed payload definitions.

Work:

- Buyer UI:
  - concise "why this fits";
  - availability;
  - tradeoffs;
  - optional personalization disclosure;
  - "image under review" when relevant.
- Admin trace:
  - query plan;
  - adapter outcomes;
  - inventory evidence;
  - customer-context consent/freshness;
  - timing spans;
  - policy decisions.

Exit criteria:

- New fields render with null guards.
- LLM text sinks are safe-rendered.
- Playwright smoke tests pass when environment supports frontend.

### R8: Second Vertical Proof

Goal: prove the core is actually agnostic.

Work:

- Add a tiny `config/store_profiles/pharmacy.json` or `furniture.json`.
- Do not build a full new storefront.
- Prove that:
  - core decomposition works;
  - laptop specs do not leak;
  - profile questions differ;
  - no electronics brand floors apply.

Exit criteria:

- Agnostic test passes.
- Electronics stays the first production adapter.

## Recommended Commit Strategy

Current dirty tree observed before this document:

- Modified:
  - `config/security/cv_playbooks.json`
- Untracked:
  - `docs/SHOPSQUIRE_CLAUDE_HANDOFF_DAVID_OPUS48_2026-06-18.md`
  - `docs/SHOPSQUIRE_OPUS48_AGNOSTIC_COMMERCE_AI_ROADMAP_2026-06-18.md`

This document adds:

- `docs/SHOPSQUIRE_CORE_ADAPTER_DATA_PLATFORM_ROADMAP_2026-06-18.md`

Recommendation:

- Commit this roadmap with the related roadmap/handoff docs if they are intended as durable planning artifacts.
- Do not include `config/security/cv_playbooks.json` until reviewed separately; it may be an unrelated security-control change.
- Archive older roadmap drafts only after confirming they are superseded. Do not delete them in the same commit as implementation work.

Suggested commit:

```text
docs: add core-adapter data platform roadmap
```

## Tests Run During Verification

Commands:

```powershell
python -m compileall -q src/app
python -m pytest tests/services/test_finalizer_characterization.py tests/test_schema_contract.py tests/security/test_execution_gate.py -q
```

Result:

```text
18 passed
```

## Bottom Line

The next build step should be narrow:

1. Add `src/app/platform/store_profile.py`.
2. Wire only `brand_price_floors_usd` from `config/store_profiles/electronics.json`.
3. Add characterization tests.
4. Fix the ASUS safe image hint/fallback ranking with profile-backed evidence.
5. Add scatter-gather timeouts before leaning harder on V2.

Do not start with loyalty/CDP integrations. Start with the ports and local/mock adapters. Once the core contract is stable, Everyday Rewards, Flybuys, Segment, mParticle, Snowflake, Databricks, or store-specific systems become replaceable inputs rather than architectural dependencies.
