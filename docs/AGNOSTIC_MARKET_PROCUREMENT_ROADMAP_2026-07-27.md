# Agnostic Market Intelligence and Procurement Roadmap — 2026-07-27

## Objective

Build one vertical-agnostic commerce intelligence loop that:

1. observes authoritative market, inventory, order and communication facts;
2. converts them into evidence-backed findings;
3. proposes procurement or customer actions;
4. applies deterministic policy and human/autonomy gates;
5. communicates through durable supplier and buyer threads; and
6. measures the eventual commercial outcome.

The autonomous "brain" is not a larger prompt or a new monolithic agent. It is the typed,
auditable loop below. Models may classify, summarize and draft, but may not invent tenant identity,
availability, price, cost, supplier identity, commitment or execution authority.

```text
authoritative feeds + signed email events
                  |
                  v
 canonical facts and immutable evidence
                  |
                  v
 market findings + case context snapshots
                  |
                  v
 decision proposals (advisory, no side effects)
                  |
                  v
 deterministic policy + confidence + approval gates
                  |
                  v
 durable supplier/buyer communication outbox
                  |
                  v
 acknowledgements, replies, orders and outcomes
                  |
                  +----------> attribution and learning
```

## Non-negotiable domain contracts

Create or consolidate these small shared contracts before adding more agents:

- `CanonicalFact`: tenant, subject, fact type, value, unit/currency, event time, observed time,
  source, provenance, confidence, freshness and quality status.
- `EvidenceRef`: immutable raw reference, sanitized reference, content hash, custody state,
  retention class and access policy.
- `ConversationThread`: authoritative tenant, party type, party identity, provider subscription,
  provider thread/message identifiers, case/order/RFQ references and status.
- `MessageObservation`: direction, sender identity verdict, sanitized content, attachment evidence,
  detected intent, correlation confidence and quarantine state.
- `DecisionProposal`: decision type, facts used, assumptions, alternatives, expected benefit,
  risks, confidence, expiry and required authority.
- `ActionAuthorization`: allow, deny, needs information or human approval, with policy version,
  reasons, limits and approved content hash.
- `OutcomeEvent`: decision reference, action reference, target metric, observed result, attribution
  window and data-quality state.

These are opaque to product category. SKU, supplier, region, channel and use case remain identifiers
or taxonomy references rather than hard-coded laptop, pharmacy or retail vocabulary.

## Phase 0 — Stabilize the execution boundary

**Priority: P0. Complete before autonomy or a rollback observation window.**

### Progress in this implementation slice

- Real caller-visible deadline applied to in-process chat/V2 dispatch, with typed degradation,
  timeout trace evidence and bounded metrics.
- Shared admin API requests now have abort deadlines and caller cancellation propagation.
- `run_async_safe()` no longer re-waits during `ThreadPoolExecutor` shutdown after its deadline.
- Market refresh/state follows request tenant context; pipeline ingestion receives the same tenant;
  scheduled market analysis uses bounded authoritative tenant fan-out.
- Email evidence migrations form one Alembic chain through `20260801_email_ops`; the inspected local
  database is at that head.
- Strict Gmail/M365 subscription-to-tenant binding was confirmed as existing behavior.

1. Protect the current cutover and email work in reviewable commits.
2. Apply and validate the inbound inbox, correlation, evidence and disposition migrations.
3. Derive tenant and buyer identity from authenticated principals or signed connector
   subscriptions. Remove request-body/header-selected tenant authority from production paths.
4. Add buyer ownership checks to case, journey, confirmation and option-selection routes.
5. Enforce real deadlines on chat/V2 dispatch. Return typed timeout/degraded results and record
   timeout metrics by lane.
6. Add abort deadlines to the shared admin API client.
7. Replace the ineffective thread-based async timeout helper with a boundary that does not wait
   indefinitely during executor shutdown.
8. Move `/outbound/process` transmission to a worker trigger; the operator request should return
   an accepted/job response rather than process up to 50 SMTP calls inline.
9. Resolve the `confirm-cart` contract: explicitly distinguish authoritative ATP calculation from
   an operator-approved `source_qty` override.
10. Add per-test timeouts and clean-database fixtures to the critical integration and browser packs.

**Exit gate**

- No unbounded successor-path wait.
- No client-selected tenant or unauthenticated buyer mutation.
- Migrations pass on an empty database and a production-like upgrade copy.
- A stalled dependency produces a measured degraded result rather than a silent hang.

### Buyer identity prerequisite

Do not implement ownership by comparing two client-supplied `uid` strings. Before item 4 can close:

1. authenticated buyers must resolve from a verified bearer/session principal;
2. guest buyers must receive a high-entropy, HttpOnly session or case capability whose hash—not the
   raw token—is stored server-side;
3. the principal must be tenant-bound and case/order-bound;
4. buyer-safe and operator projections must remain separate;
5. production must reject body-only identity, while an explicitly marked demo mode may retain
   compatibility behavior;
6. existing `buyer_uid_hash` rows that contain raw UIDs need a migration/backfill classification
   before the column becomes an enforcement source.

## Phase 1 — Canonical intelligence substrate

**Priority: P0. This is the foundation for both Market Intelligence and Procurement.**

1. Make the canonical fact contract the only input to consequential market/procurement policy.
2. Preserve raw source records separately; adapters normalize them into facts without overwriting
   source evidence.
3. Add source watermarks, reconciliation counts and health states:
   `available`, `empty`, `stale`, `failed` and `quarantined`.
4. Never translate a failed query or missing table into an unexplained zero.
5. Enforce tenant, subject, time, unit and currency compatibility at every fact join.
6. Record explicit missing-data findings instead of filling unknown ATP, landed cost, delivery date
   or margin with defaults.
7. Add schema/version fields to facts, proposals, policies and outcomes.
8. Use migrations for persistent tables; remove production runtime DDL from these paths.

**First authoritative feed slice**

Onboard one tenant end to end:

- orders and line items;
- inventory/ATP by location;
- returns and cancellations;
- supplier quotes and purchase orders;
- goods receipts and invoices;
- landed cost and store settlement currency.

Do not connect five partial systems at once. One reconciled tenant with watermarks is more valuable
than many adapters with no evidence that their numbers match the source system.

## Phase 2 — Governed communication fabric

**Priority: P0/P1. Supplier and buyer communication become evidence-bearing domain events.**

### Supplier inbound

1. Verify Gmail or Microsoft notification identity and bind the subscription to an authoritative
   tenant before reading message content.
2. Deduplicate by tenant, provider and provider message ID.
3. Correlate using durable outbound message/thread mappings and immutable RFQ/case references.
   Subject parsing and UUID extraction are fallbacks, not primary identity.
4. Run a bounded synchronous ingress gate: identity, replay, size, basic content safety and
   correlation. Persist and return quickly.
5. Run OCR, QR, attachment sandboxing, linked-artifact analysis and deeper threat enrichment as
   durable jobs with timeouts, retries and dead letters.
6. Route every production connector through `receive_email_reply()`; retain an architecture test
   prohibiting direct use of the low-level receive function.
7. Classify supplier replies into typed observations:
   - quote;
   - partial availability;
   - substitute offer;
   - delivery/lead-time change;
   - request for information;
   - acknowledgement;
   - invoice/attachment;
   - refusal or no-bid;
   - suspicious/untrusted.
8. A classified message may update a case only after identity, correlation and schema validation.
   Quarantined content cannot mutate quote, economics, PO or payment state.

### Supplier outbound

1. Use one durable communication outbox for RFQs, RFIs, cancellations, PO notices and
   acknowledgements.
2. Bind recipient identity to the approved supplier registry, never buyer/model text.
3. Pin the exact approved content hash and policy decision to every send.
4. Require idempotency, bounded retry, dead-letter handling and delivery/ack status.
5. Keep autonomy level and authority explicit per message type. Autonomous RFQ sending must not
   silently authorize PO, cancellation or payment messages.

### Buyer/customer inbound

Introduce a buyer communication inbox using the same generic thread and evidence contracts, but a
separate policy profile. Recognize:

- requirement clarification;
- commitment/confirmation;
- option selection;
- deadline/address correction;
- change or cancellation request;
- consent or approval;
- complaint, return or damage claim;
- status question.

Buyer identity and case/order ownership must be authenticated. Email text alone must never authorize
payment, a material scope increase or a post-send cancellation.

### Buyer/customer outbound

1. Generate status messages from case state and authoritative facts, not free-form model assertions.
2. Separate safe autonomous notifications from approval-requiring commitments.
3. Approved autonomous messages may state recorded status, request missing information, present
   already-approved options and acknowledge receipt.
4. Prices, refund promises, delivery guarantees, substitutions and changed commercial terms require
   an authoritative fact plus the relevant authorization.
5. Record delivery, bounce, reply and customer response as outcome events.

**Exit gate**

- A real provider round trip is demonstrated for one supplier and one buyer mailbox.
- Malicious trusted-domain supplier mail cannot change commercial state in a Playwright regression.
- Buyer replies cannot cross tenant/order ownership or create an irreversible action from email text.

## Phase 3 — Market sensing and findings

**Priority: P1. Run only after canonical facts and source health are trustworthy.**

1. Remove hard-coded `default` tenant execution from live and scheduled market pipelines.
2. Fan out over a bounded authoritative tenant registry with per-tenant leases and checkpoints.
3. Schedule ingestion and analysis as jobs; operator refresh should enqueue and expose progress.
4. Produce findings for:
   - demand and conversion shifts;
   - stockout and excess-stock risk;
   - supplier lead-time/reliability change;
   - competitor price movement;
   - return/complaint clusters;
   - funnel and buyer-objection changes;
   - cost/margin pressure.
5. Attach evidence references, scope, freshness, confidence and expiry to every finding.
6. Distinguish observed, estimated, simulated, insufficient and unavailable values in APIs and UI.
7. Compare forecasts with seasonal-naive and moving-average baselines before model complexity is
   allowed to influence actions.

**Exit gate**

- Each live finding is reproducible from source facts and visibly distinct from replay data.
- Source failure is visible and alertable.
- Forecast comparison runs on real history with a frozen baseline definition.

## Phase 4 — Procurement decision intelligence

**Priority: P1. Convert findings into proposals, not direct actions.**

1. Build an immutable case-context snapshot containing:
   demand finding, ATP, open orders, buyer requirements, approved suppliers, quote history,
   lead-time reliability, landed cost, margin floor and communication status.
2. Generate typed proposals for:
   - no action;
   - request missing information;
   - RFQ fan-out;
   - reorder quantity/range;
   - supplier choice;
   - substitute option;
   - split fulfillment;
   - expedite;
   - delay or decline;
   - change/cancellation handling.
3. Rank proposals using deterministic feasibility and policy first. Models may explain trade-offs,
   but may not supply missing economics.
4. Preserve alternatives and refusal reasons so the operator can see what evidence would change
   the recommendation.
5. Add proposal expiry and automatic re-evaluation when ATP, price, quote, deadline or trust state
   changes.
6. Keep proposal, authorization and execution as separate records.

**Exit gate**

- Replaying the same case snapshot and policy version produces the same bounded proposal.
- Missing cost, ATP or currency causes `needs_information`, not invented economics.
- Supplier reply updates cause controlled re-evaluation rather than ad hoc state mutation.

## Phase 5 — Bounded autonomy ladder

**Priority: P1/P2. Increase authority only from measured evidence.**

Use explicit levels per action type:

- **L0 Observe:** findings and traces only.
- **L1 Advise:** proposals shown to an operator.
- **L2 Draft:** communication/action draft, no external effect.
- **L3 Execute reversible:** approved low-risk notifications or RFQs within policy limits.
- **L4 Execute consequential:** PO, cancellation, refund or payment; retain human approval until
  separately proven safe and legally appropriate.

Promotion requires:

- minimum sample size;
- acceptable false-action and refusal rates;
- no tenant/ownership violations;
- bounded latency and failure behavior;
- successful kill-switch and rollback rehearsal;
- per-action budget, supplier, category and confidence limits.

Do not use one global "autonomy enabled" switch. Authority is granted to a specific action type,
tenant, policy version and limit.

## Phase 6 — Outcomes and learning

**Priority: P2. This makes the system more intelligent without letting it self-authorize.**

1. Close the loop from findings and proposals to:
   - supplier response rate and time;
   - quote competitiveness;
   - fill rate and lead-time accuracy;
   - stockout and excess inventory;
   - gross margin and landed-cost variance;
   - cancellation/return rate;
   - buyer acceptance and satisfaction;
   - manual override and quarantine rates.
2. Attribute outcomes to immutable decision and action references.
3. Separate policy evaluation from policy changes. Learning produces a proposed policy adjustment;
   governance approves and versions it.
4. Run shadow and controlled cohorts against agreed baselines.
5. Preserve the ability to explain why a proposal changed between two policy/model versions.

## Phase 7 — Recommendation V1 retirement

**Priority: supporting refactor, parallel with Phases 0–2; not the product roadmap's center.**

1. Keep the V2-backed `/recommend/suggest` compatibility router through the sunset/traffic window.
   Rename the `main.py` alias to `recommend_compat_router` for clarity.
2. Fix the V2/chat timeout boundary before observing production cutover.
3. Move the 13 remaining legacy-private-helper tests to V2 contracts, compatibility contracts or
   frozen characterization evidence.
4. Adjudicate remaining reference, follow-up, multimodal/bulk and golden failures.
5. Require zero production imports, zero legacy private-helper test imports, acceptable degraded and
   timeout rates, and a successful artifact rollback rehearsal.
6. Archive/delete `recommend.py`; remove the compatibility route later, only when traffic reaches
   zero or the published compatibility obligation ends.

## Refactoring map

### Refactor now

- Split `fulfillment_cases.py` into thin routers:
  `procurement_cases`, `procurement_buyer`, `procurement_supplier_comms`,
  `procurement_purchase_orders`, `procurement_market` and `procurement_operations`.
- Keep workflow/state transitions in the fulfillment domain, not in routers.
- Extract one communication application layer shared by supplier and buyer channels, while keeping
  separate identity and authorization policies.
- Split email security by concern: connector identity, ingress gate, evidence custody, enrichment,
  correlation, disposition and threat policy.
- Consolidate tenant resolution into authenticated principal/subscription dependencies.
- Replace best-effort empty returns in intelligence paths with typed result/health objects.
- Create one job control surface for accepted/running/retrying/dead-letter/completed state.
- Rename misleading compatibility symbols; do not rename or move stable V2 core modules without need.

### Do not build

- A new all-knowing `BrainAgent` class.
- A shared free-form memory blob that supplier, buyer and market agents can all mutate.
- Direct LLM writes to case, quote, PO, payment or market-fact tables.
- A second orchestration framework before the typed contracts and jobs above work end to end.
- More vertical-specific rules in the agnostic core.

## Recommended delivery slices

1. **Safety and identity slice:** Phase 0 plus provider/tenant binding.
2. **Supplier loop slice:** outbound RFQ → verified reply → quote observation → quarantine/browser proof.
3. **Buyer loop slice:** authenticated status/clarification thread → option response → ownership proof.
4. **Truth slice:** one tenant's orders, ATP, returns, costs, receipts and invoices reconciled.
5. **Intelligence slice:** market findings → procurement proposal → human decision → outcome.
6. **Autonomy slice:** one reversible message type at L3 with limits and rollback.
7. **Retirement slice:** V1 archive after compatibility and rollback gates.

This order concentrates effort on the defensible product: evidence-backed commercial decisions and
governed action. Recommendation parity remains necessary, but it should no longer consume the roadmap
ahead of authoritative facts, communication custody, procurement outcomes and tenant-safe autonomy.
