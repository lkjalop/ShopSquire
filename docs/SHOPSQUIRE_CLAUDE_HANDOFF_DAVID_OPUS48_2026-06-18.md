# ShopSquire Claude Handoff: David Decks + Opus 4.8 Reconciliation

Date: 2026-06-18  
Inputs reviewed:

- `C:\Users\leoma\Downloads\Machine-Operated-Retail-Enterprise.pdf`
- `C:\Users\leoma\Downloads\Autonomous-Retail-Candidate-Physical-Architecture.pdf`
- `C:\Users\leoma\.codex\attachments\94e6b4b8-4123-4009-aedc-5198cc01153a\pasted-text.txt`
- `docs/SHOPSQUIRE_OPUS48_AGNOSTIC_COMMERCE_AI_ROADMAP_2026-06-18.md`
- Current ShopSquire codebase anchors from the 2026-06-18 deep dive.

## The Message To Give Claude

Claude, please pressure-test and then help implement the reconciled ShopSquire roadmap below. Do not treat this as a green-field autonomous retail rebuild. The conclusion from David's two architecture decks, the Opus 4.8 review, and the current codebase is:

> ShopSquire is not the whole retail enterprise. ShopSquire should be the policy-bounded AI Decision + Control layer that plugs into commodity ecommerce, payment, shipping, support, analytics, identity, and cloud infrastructure.

The core rule is:

> AI infers and recommends. Deterministic policy decides. Execution services act. Audit records the full chain.

This maps directly to David's Five-Step Execution Gate:

1. Intent extraction
2. Policy evaluation
3. Authorization validation
4. Execution service
5. Audit logging

Anything consequential must pass this gate: refunds, reshipments, order edits, supplier purchase orders, discounts, bundle commitments, inventory reservations, cancellations after payment, fraud dispositions, privacy exports, and any supplier/customer email that can be interpreted as a binding commitment.

## What We Agree On

We agree with David's architecture on the control boundary:

- AI can talk, recommend, clarify, classify, rank, summarize, and propose.
- AI must never directly execute privileged commerce actions.
- Policy and authorization must sit between AI output and execution.
- Every action must be replayable through logs, policy evaluation, evidence, actor, timestamp, and outcome.

We agree with Opus 4.8 on sequencing:

- P0 determinism first.
- P1 expand the existing finalizer, do not create a duplicate.
- P2 schema hardening before V2 fusion.
- P3 move NQE/use-case refinement out of `recommend.py`.
- P4 apply CaMeL-style text/RAG/memory gates.
- P5 ports/adapters and StoreProfile.
- P6 V2 parity metrics before customer-affecting cutover.
- P7 commerce GraphRAG only where relationships matter.
- P8 personalization behind consent and privacy boundaries.
- P9 bounded autonomous exception outcomes after the gate is proven.

We agree with the codebase finding:

- Most building blocks already exist.
- The work is not "invent capabilities."
- The work is "assemble existing pieces behind a clean commerce core, a single execution gate, and an agnostic product schema."

## What To Build

Build only the differentiating core:

1. Commerce intelligence core
   - Query decomposition.
   - Product recommendation ranking.
   - Evidence bundle.
   - Grounded "why recommended" explanation.
   - Text-only and image+text interpretation.
   - V2 retrieval fusion and parity metrics.

2. Policy and control plane
   - Unified execution gate.
   - Authorization engine.
   - Action authority matrix.
   - Policy evaluation log.
   - Exception recovery controller.
   - Human review only when policy requires it.

3. Decision logging and audit
   - Bitemporal decision trace.
   - Evidence bundle snapshots.
   - Policy version.
   - Model/provider metadata.
   - Retrieval source metadata.
   - Final answer contract.

4. Agnostic catalog and inventory adapters
   - CatalogPort.
   - InventoryPort.
   - CustomerContextPort.
   - KnowledgePort.
   - ModelPort.
   - VisionPort.
   - PolicyPort.
   - PromotionPort.
   - SupplierPort.
   - TracePort.
   - GraphPort.

5. StoreProfile
   - Store vocabulary.
   - Product type rules.
   - Taxonomy mapping.
   - Attribute mapping.
   - Brand aliases.
   - Pricing, promo, margin, discount rules.
   - Supplier/reorder rules.
   - Model/vision provider choices.
   - Privacy and consent defaults.

6. Inventory and supplier intelligence
   - Stock confidence.
   - Availability explanation.
   - Reorder recommendations.
   - Supplier scoring.
   - Purchase order proposal.
   - Supplier inquiry draft.
   - Never direct supplier payment.

7. Commerce GraphRAG
   - Compatibility.
   - Bundles.
   - Substitutes.
   - Prior purchase accessory fit.
   - Supplier risk.
   - Fraud/ring signals.
   - Policy relationship lookups.

## What To Commoditize Or Treat As Adapter Add-On

Do not build these as core differentiators:

- Storefront engine: Shopify, WooCommerce, Adobe Commerce, BigCommerce, commercetools, custom headless.
- Checkout, tax, coupons, cart primitives: platform-owned unless policy needs a guard.
- Payments and refunds rail: Stripe or equivalent.
- Shipping labels and carrier abstraction: Shippo/EasyPost/AfterShip or equivalent.
- 3PL fulfillment: ShipBob, warehouse APIs, ERP/WMS.
- Support channel UI/runtime: Intercom Fin, Zendesk, Gorgias, Ada, or custom chat only as a shell.
- Analytics warehouse: Snowflake/BigQuery/Redshift.
- BI dashboard: Looker/PowerBI/Grafana.
- Identity: Auth0/Entra/Cognito.
- Observability: Datadog/Grafana/CloudWatch.
- Cloud substrate: AWS/GCP/Azure managed queues, workflow, storage, DB.
- LLM and VLM providers: OpenAI, Ollama, Anthropic, Gemini, local BYO model.
- Vector/search infrastructure: OpenSearch, pgvector, Pinecone, Weaviate depending on deployment.

ShopSquire should integrate with these through adapters and policy gates. The store can bring its own ecommerce platform, trained model, vision weights, customer data source, supplier feeds, and business policy. ShopSquire's moat is the control and evidence layer that makes those pieces safe and useful.

## Where ShopSquire Sits

David's conceptual layers map to ShopSquire like this:

| David layer | ShopSquire role |
|---|---|
| Experience | Mostly buy/adapt. ShopSquire can provide embeddable UX widgets, not own the storefront. |
| Business execution | Mostly buy/adapt. Stripe, Shopify, Shippo, ShipBob, ERP/WMS execute. |
| AI decision | Build. This is ShopSquire's product recommendation, NQE, evidence, personalization, RAG, graph, supplier/inventory intelligence. |
| Control | Build. This is the moat: policy, authorization, audit, exception recovery, decision trace. |
| Data and insight | Hybrid. ShopSquire owns decision/evidence/audit data; warehouse and BI can be commodity. |

So the positioning is:

> ShopSquire is the policy-bounded AI Decision and Control layer for machine-operated commerce. It plugs into existing ecommerce infrastructure and makes recommendations, inventory answers, support actions, supplier actions, and exceptions auditable, bounded, and useful.

## Did We Waste Time?

No. The work was not wasted. The codebase already has non-trivial assets that map directly to David's target architecture:

- `authorization_engine.py`: policy/authorization gate foundations.
- `action_authority_matrix.py`: bounded autonomy rules.
- `recommend_response_finalizer.py`: existing finalizer to expand.
- `recommend_pipeline.py`: V2 scatter-gather shape.
- `candidate_retriever.py`: DB/vector/caption retrieval.
- `product_embedding_text.py`: canonical rich product embeddings.
- `product_captioner.py`: safe caption enrichment.
- `image_feature_gate.py`: safe image-hint boundary.
- `commerce_request_guard.py`: request security boundary.
- `semantic_cache.py`: safe cache primitives.
- `memory.py` and privacy routes: session/personalization substrate.
- `inventory_agent.py`: reorder, supplier scoring, approval, PO evidence.
- `inventory_rules.py`: stock, bundle, promo, price-match rules.
- `vertical_pack.py` and `config/store_vocab.json`: store/vertical agnostic direction.
- `graph_retrieval.py`: graph adapter foundation.
- `recommendation_bandit.py` and `recommendation_als.py`: personalization foundations.
- `data_residency.py` and provider boundary: privacy/provider controls.

What was not yet finished is assembly. The current architecture is a strong prototype with scattered seams, not a clean productized core. That is normal at this phase, but the next phase must reduce sprawl rather than add more features.

## Where To Be Proud

ShopSquire already has differentiators that generic chatbots and many ecommerce SaaS products do not:

- Suspicious multimodal input can be quarantined without blocking the shopping path.
- Image-derived signals are gated before influencing recommendations.
- Product recommendations can be explained and traced.
- Inventory/reorder/supplier workflows already have policy hooks.
- Privacy and data residency are represented in code, not just docs.
- The platform can talk in terms of decision trace, policy, evidence, bitemporal logs, and replay.
- The model ladder and products-first strategy reduce dependence on big LLM calls.
- The architecture is already moving toward "rules/catalog fast path first; models only when justified."

That is the delta to capitalize on:

> Not "AI chat for ecommerce," but "safe machine-operated commerce decisions with evidence."

## What To Reconsider

1. David's "no human closure required" is a north-star, not an immediate implementation rule.
   - Today: fail closed to human review is correct.
   - Future: replace repeated manual review categories with bounded autonomous outcomes.
   - Do not ship full autonomy before the gate and recovery controller are proven.

2. Event-driven architecture is the scaling direction, but not the first refactor.
   - David's stack uses EventBridge/SQS/Step Functions.
   - ShopSquire is currently FastAPI/Celery/local services.
   - First extract clean services and contracts; then move selected workflows to events.

3. Intercom Fin and Shopify should be integration targets, not dependencies baked into the core.
   - The same ShopSquire core should work with Zendesk, Gorgias, WooCommerce, Magento/Adobe, BigCommerce, custom ERP, and direct API.

4. BYO model must not mean BYO policy.
   - Stores may bring model weights, VLM, embeddings, and RAG corpus.
   - ShopSquire must still enforce policy, action gate, evidence contract, and privacy boundaries.

5. GraphRAG should not replace catalog filters.
   - Use graph for compatibility, bundles, substitutes, customer journey, supplier risk, and policy relationships.
   - Use SQL/rules/vector for ordinary product retrieval.

6. Constrained decoding is worth adding, but only at module boundaries.
   - Use schema-constrained output for `QueryPlan`, `EvidenceBundle`, `Why`, and `ActionProposal`.
   - Do not over-constrain private reasoning or ranking exploration.

## Exact First Implementation Request For Claude

Claude, please implement only P0 and P1 first. Do not start P2-P9 yet.

### P0: Determinism Harness

Work files:

- `tests/conftest.py`
- `src/app/deps.py`
- New `scripts/determinism_check.py`
- `pyproject.toml`

Requirements:

- Add an autouse shared-state isolation fixture for test DB state.
- Reset or flush `DummyRedis` and `_lazy_redis` safely between tests.
- Clear relevant module caches: product classifier vocab, catalog profile cache, use-case KB, query/NQE caches.
- Add a script that can run a test file alone and in a sequence, then report order-dependent failures.
- Do not mask failures by deleting state needed by a test. Scope isolation to known shared tables and caches.

Acceptance:

- Existing focused tests still pass.
- `tests/test_recommend.py` can be run alone and after inventory/NQE tests without hidden state leakage.

### P1: Expand Existing Finalizer

Work files:

- `src/app/services/recommend_response_finalizer.py`
- `src/app/routers/recommend.py`
- `src/app/services/answer_composer.py`
- `src/app/services/product_claim_guard.py`
- `tests/test_recommend_finalizer.py`
- `tests/services/test_finalize_answer.py`
- `tests/services/test_product_claim_guard.py`

Requirements:

- Do not create a new finalizer. Expand the existing `recommend_response_finalizer.py`.
- Move or delegate these helpers from `recommend.py` into the finalization path:
  - `_ensure_result_prices`
  - `_compose_compound_if_needed`
  - `_maybe_apply_security_challenge`
  - `_build_security_challenge_text`
  - `_annotate_type_and_price_integrity`
  - `_dereference_product_labels`
  - `_demote_off_category`
  - `_finalize_answer`
- Keep the call site near `recommend.py:14228-14237` as the single authoritative final exit.
- Preserve trace behavior and existing response contract.
- Run the product claim guard on LLM narration before final output.
- Add tests for invented product, invented price, invented spec, QR/URL leakage, no-products recovery, image-under-review plus products, and normal product result.

Acceptance:

- `recommend.py` shrinks.
- Final response shaping has one owner.
- Existing behavior remains stable except documented intentional differences.
- Unsupported LLM claims are suppressed or replaced with grounded deterministic prose.

## Next After P0/P1

Only after P0/P1 are stable:

1. P2 schema: add `product_type`, `brand`, `category`, `attributes`, and autonomy-support tables.
2. P3 NQE: centralize use-case resolution and `NQEInput`.
3. P4 text/RAG/memory gates.
4. P5 ports and StoreProfile.
5. P6 V2 parity/fusion.

## Final Strategic Recommendation

Build ShopSquire as the control-intelligence layer for autonomous commerce:

- It should not compete with Shopify, Stripe, Shippo, Intercom, Snowflake, Looker, Auth0, or Datadog.
- It should make those systems safe to operate under AI-driven workflows.
- Its wedge is product recommendation + inventory/supplier/action control with evidence and audit.
- Its long-term differentiation is the execution gate, evidence bundle, store-agnostic adapters, and bounded autonomy.

The product line should be:

1. Recommendation intelligence layer.
2. Multimodal safe input boundary.
3. Commerce decision trace.
4. Policy/action gate.
5. Inventory and supplier autonomy.
6. Store-agnostic adapter framework.
7. Governance dashboard.

That is a defensible moat. The prototype was not wasted; it found the right moat. The next task is to consolidate it.

