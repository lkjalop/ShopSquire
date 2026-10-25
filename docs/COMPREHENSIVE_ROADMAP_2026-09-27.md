# ShopSquire comprehensive portfolio roadmap — 27 September 2026

## Purpose and scope

Latest implementation evidence: [continuity repairs and market-decision gaps](CONTINUITY_AND_MARKET_EXECUTION_2026-10-01.md).
This records the repairs, passing and failed runs, existing-data blockers and remaining gates.

Latest planning update: [AI/ML market-intelligence research and revised order](AI_ML_MARKET_INTELLIGENCE_RESEARCH_AND_ROADMAP_2026-10-01.md).
After the known case/recall repairs, bring forward a read-only, evidence-backed market
decision and baseline/challenger experiment. Reuse existing signal, forecast, retrieval
and graph services. Supplier/purchase actions still require approval and recovery;
research announcements do not close any measured implementation or reliability gate.
That document supersedes delivery ordering below while retaining all acceptance gates.

October 1 assessment: [platform deep dive](PLATFORM_DEEP_DIVE_2026-10-01.md)
records 123 passing focused backend/security tests and a real-API browser battery
with nine passes and three failures. Case continuity after reload and budget-scope
expectation failures move ahead of expanding demonstrations. Live external research
is disabled in the audited runtime; a copied UID accesses enabled demo cases without
credentials. See the assessment for evidence, scope limits and updated priorities.
An additional unmocked 20-turn conversation retained the case and applied quantity
corrections but failed consistent fact-projection assertions: final distinct browser
total is nine passed and four failed across 13 scenarios. This does not establish
blanket memory loss; recall presentation and reload restoration require repair.

September 29 update: [inventory expiry execution](INVENTORY_EXPIRY_EXECUTION_2026-09-29.md)
adds persisted deadlines, shipment-time expiry enforcement, atomic bounded cleanup
and buyer-visible hold deadlines. Scheduled cleanup and the remaining operational
workflows are still open. The 30-minute network diagnostic passed 39 cycles;
the historical browser buffer failure remains unexplained and no eight-hour run passed.

Latest integrity/resource update: [request replay and resource diagnosis](REPLAY_AND_RESOURCE_DIAGNOSIS_2026-09-28.md).
Changed supplier-selection requests cannot reuse an old idempotency result. The live
request-and-idle probe shows handles draining; a backend leak is not established.
Chromium network diagnostics are now available, but the buffer failure remains unresolved.

Latest September 28 update: [connected stock execution](CONNECTED_STOCK_EXECUTION_2026-09-28.md)
adds browser-tested acceptance, 30-to-40 amendment, current stock, qualification invalidation and
explicit hold release. Supplier/approval/recovery integration remains open. The instrumented soak
rerun failed after 19m38s; it is not still running and no endurance gate is closed.

September 28 update: the first eight-hour browser run stopped after 7h11m51s, with 351 successful
cycles, when Chromium reported `ERR_NO_BUFFER_SPACE`. It reached the 60-minute checkpoint but did
not pass eight hours. Requirement-load retry/cancellation and inventory reconciliation now have
regressions; a fresh eight-hour run with resource sampling has been launched. The resource-failure
cause remains unresolved. See [current execution](SOAK_RECOVERY_EXECUTION_2026-09-28.md) and
[demo and hiring narrative](DEMO_AND_HIRING_NARRATIVE_2026-09-28.md).

Execution update: see [buyer, inventory and recovery evidence](BUYER_INVENTORY_RECOVERY_EXECUTION_2026-09-27.md).
The fictional scope now has a passing positive real-API browser journey, including reload,
expiry and revocation. Inventory effects and person-bound outbound approval/recovery have
service-level evidence. Their complete authenticated operator/browser integration remains open.
An eight-hour replay of three browser journeys has been launched; consult its live status before
claiming any duration. It does not exercise model/image endurance. No real product was newly qualified.

This is the consolidated planning document. Earlier execution reports remain the evidence record; their old “next step” statements do not override this ordering. The target is a reproducible fictional electronics shop using the existing catalogue, clearly labelled synthetic operations and fake external providers. Real customers, private supplier access and commercial deployment are not completion dependencies.

The final demonstration should connect buyer needs, evidence-backed product selection, optional upgrades/accessories, stock and deadline assessment, supplier enquiries, buyer amendments, approval, simulated execution and recovery. A merchant should also be able to explain a replenishment decision using consistent simulated business events.

No recommendation grants permission to send messages, change stock or move money. Historical public product observations and invented operational data retain separate provenance. Successful simulation demonstrates software behavior under those conditions, not real business returns or production readiness.

## Verified baseline and limits

The paragraphs below are historical checkpoints, not the latest completion status. Use the dated
execution updates above for subsequent positive buyer/browser, inventory and approval work.

**Latest execution:** [V2 binding, operational history and uncertain-delivery recovery](V2_HISTORY_RECOVERY_EXECUTION_2026-09-27.md) wires the outer V2 binding guard, API/trace receipts and shadow propagation; proves a scoped positive RAM-only fixture in the actual core; persists replayable fictional movements; and prevents automatic resend after an uncertain provider outcome. Two real-API browser journeys pass. The positive buyer browser journey, transactional operations, supplier conversations, distinct-person approval, operator recovery and sustained testing remain open. This supersedes the narrower “next” items in older reports, without converting unit evidence into end-to-end certification.

**Execution follow-up:** [Buyer contract selection and consumption work](CASE_CONTRACT_EXECUTION_2026-09-27.md) adds case endpoints and controls, cached-session revocation repair, case-aware projection gates and enrolled-research revalidation. It records 102 backend tests, one component test and one real-API Playwright journey passing. Stage 3 has advanced; complete top-level V2 propagation and positive product qualification remain open. The dated baseline below predates that execution; overlapping test counts must not be added together.

Evidence was reviewed on September 27; the cited tests were run September 26, not rerun during this roadmap consolidation.

- Import fixes have recorded red/green evidence: desktop categories, metadata exclusion, conflicting prices, duplicate-title observations and unsupported Thunderbolt claims.
- The isolated shop contains 98 priced catalogue snapshots and seven held records, from 105 reconciled records. These are not 98 verified/current product configurations.
- Existing commerce tables support the fixture's three locations, reservations, supplier capacity, minimum quantity, volume prices and expiring offers. All products currently receive the same illustrative stock pattern and one fictional supplier per SKU.
- The read-only browser scenario passes 30 → 40 → 100 quantity changes. Shortfalls are 15 → 25 → 85, with 60 units still uncovered in the last case after supplier capacity. It is not an accepted buyer amendment, purchase or supplier conversation.
- Latest batch: 48 backend/import/service tests and one Playwright clickthrough passed; production frontend build and targeted architecture checks passed. CI workflow additions have not been observed running remotely.
- Contract selection persistence and compiler gates have service-level evidence. Selection through the buyer API/UI and revalidation in every consuming path remain incomplete. Earlier test sets overlap and must not be added into a cumulative coverage claim.
- Timeout/transport overlap was already fixed and regression-tested. Historical research continuity and three full browser-image cycles passed, with the same image repeated. A 45-call mixed-model run lasted roughly six minutes. No sustained or overnight stability certification exists.
- The model comparison establishes no quality winner. Real-evidence Blender qualification remains unproved.

## Ordered delivery plan

### 1. Preserve and make the baseline reproducible — partial

Maintain reviewed checkpoints of code, migrations, configuration, fixture sources and evidence. Keep unrelated worktree changes intact; document which script populates which database and retire conflicting setup paths deliberately. Test installation from a clean checkout, migration, deterministic seed and startup with bounded model settings. Preserve a manifest tying every result to code, dataset, scenario clock, model digest and configuration.

**Finish:** a second environment reproduces the expected data, startup and test results using documented commands; restore succeeds. A local archive alone is not proof of off-device recovery.

### 2. Finish catalogue identity and evidence normalization — partial

Reconcile the August document with active catalogue/import paths. Bind internal SKU, exact configuration and manufacturer/retailer identifiers where available. Preserve source spans, unknowns, contradictory observations and attribute-specific timestamps. Safely migrate historical references when identities change; do not merge on title alone. Make missing-price and conflicted records visible for review rather than silently selecting values.

**Finish:** repeat imports are idempotent; all source blocks are accounted for; no category bleed, accidental duplicate identities, overwritten conflicts or fabricated attributes. An identity migration preserves dependent orders, evidence and approvals.

### 3. Connect buyer contracts to the real journey — partial

Expose explicit subject/version/platform/workload selection through the buyer API/UI. Persist tenant, buyer, case revision, contract revision and binding identity. Include these in compilation receipts and qualification projections. Revalidate applicability, freshness and revocation at evidence consumption, including after asynchronous research and before effect dispatch where relevant.

**Finish:** select/reload/revoke works; case or contract changes invalidate old conclusions; stale writers and cross-tenant access fail; API, UI and trace show the same state. A failed binding cannot fall back to unbound qualification.

### 4. Deliver one qualified recommendation — incomplete

Choose a small reviewed subset of the existing catalogue. Trace each required obligation to accepted evidence and an exact product fact, then show a positive fixture-backed result alongside insufficient, conflicting, stale and wrong-scope cases. Label synthetic qualification explicitly. Continue the bounded Blender gap report separately; refresh/enroll the specific missing evidence rather than widening context or introducing speculative derivations.

**Finish:** at least one scoped positive journey and its negative controls agree across response, shelf, API and trace. Any claim of real-publisher Blender qualification has its own current, accepted evidence. Price and availability validity are checked separately from product suitability.

### 5. Turn the stock fixture into an operational shop — partial

Add varied per-SKU/per-location stock, reservations, damaged/unavailable units, confirmed inbound purchase orders and receipt dates. Connect SKU-level sales, shipments, cancellations, returns and restocks to persistent events. Keep supplier availability distinct from shop inventory and confirmed inbound orders. Reuse existing commerce and market schemas after verifying their tenant and transaction boundaries.

**Finish:** events replay to the same balances; opening stock plus receipts and accepted restocks minus shipped/disposed units reconciles to on-hand; reservations affect availability without pretending goods have shipped. Concurrent reservations cannot oversell. Cancelling releases stock once; retrying a return does not restock twice. Transfers and inbound goods cannot promise an impossible deadline.

### 6. Build governed supplier conversations — foundations exist

Use multiple fictional suppliers with different capacities, cost/freight, minimum orders, quantity breaks, delivery times and quote expiry. Draft an enquiry from exact SKU, quantity, location and deadline; send only through an approved fake outbox. Parse replies into proposals with source evidence. Handle partial offers, substitutions, counteroffers, silence, duplicates, late replies and sender mismatch. Authenticate the simulated sender/channel separately from interpreting message content.

**Finish:** an enquiry, reply and accepted quote stay bound to the correct tenant/case/revision; stale replies cannot overwrite newer requirements. A reply never grants purchase authority. Missing evidence and unavailable suppliers produce truthful outcomes.

### 7. Complete accepted quantity changes and alternatives — read-only arithmetic exists

Connect the 30 → 40 amendment to actual buyer state, stock holds, supplier enquiries, price tiers, freight, budget and approvals. Distinguish expanding the buyer's order from increasing the merchant's replenishment purchase. Show partial delivery, transfers, alternate configurations and waiting only when their conditions are supported.

**Finish:** explicit acceptance advances the case revision; obsolete quotes/approvals become unusable; holds reconcile; total landed cost and delivery are recomputed. Lower unit price cannot be presented as lower total spend when the total rises. Unaccepted suggestions do not mutate the order.

### 8. Add justified upgrades, cross-sells and bundles — incomplete

Model reviewed compatibility and applicability for monitor ports, display capabilities, bag dimensions, accessory interfaces and other demonstrated category needs. Keep merchandising tags separate from fit evidence. Explain the buyer benefit, incremental price and total budget impact; include cheaper sufficient options. Avoid invented performance gains or compatibility inferred from a common marketing name.

**Finish:** upgrades meet a stated need; complementary products have supported compatibility; incompatible and unknown cases abstain. Optional items require acceptance. No automatic cart addition, hidden budget expansion or fabricated warranty claims.

### 9. Enforce distinct-person approval — incomplete

Use server-controlled synthetic principals with stable person identity and tenant membership. Multiple credentials can represent one person. Start with a second authorized person for each demonstrated external effect; put illustrative spend tiers in configurable policy. Bind approval to exact payload, recipient, configuration, quantity, amount/currency, case revision and expiry. Recheck at dispatch.

**Finish:** self-approval using the same or different credentials is denied; wrong tenant, insufficient role, changed payload, expiry and revocation fail. A valid separate-person approval permits only its exact fake action. Client-submitted role/person fields are not identity authority. Real login-provider integration is an optional later extension.

### 10. Finish effect lifecycle and recovery — partial

Inventory all effect sinks: supplier/outbound messages, order/purchase creation, payments/refunds, stock reservations/releases, inventory changes, connector writes and scheduled retries. Add missing common enforcement and operator review/revoke/renew/reconcile flows. Separate queued, dispatched, acknowledged, uncertain and confirmed-complete states.

**Finish:** crash/retry tests before and after provider acceptance cause no duplicate effects, lost reservations or false completion. An uncertain result is reconciled using provider identity/receipts, not blindly retried. The approval and recovery stages are prerequisites for the action-bearing supplier and purchase milestones above.

### 11. Validate governed search and prompt-injection containment — partial

Research unresolved obligations with scoped consent, bounded calls, approved sources, contradiction handling and explicit stopping conditions. Treat user input, search snippets, pages, email, images/OCR and cached memories according to their authority. Restrict data disclosure and exact effects independently of model behavior. Test redirects, URL/query exfiltration, fake approvals, cross-turn poisoning and malicious supplier replies with canary data and fake providers.

**Finish:** successful, empty, denied, unavailable, cancelled and stale research are truthful; attacks cannot enlarge authority, leak protected canaries or produce unauthorized effects. Measure benign refusals as well as attack success. A classifier score or a refusal sentence alone does not satisfy this gate.

### 12. Demonstrate useful market intelligence — foundations exist

Use the operational events from stage 5 to answer one decision: replenish, wait or choose another supplier. Retain exact SKU mapping, tenant, region, currency, observation time, decision-time availability and expiry. Replay seasonality, supplier delay, stale signals, contradictory offers and revoked mappings. Compare against a documented simple reorder baseline.

**Finish:** an inspectable decision shows which evidence changed the action, or why no change was justified; stale/out-of-scope evidence is rejected at use. Synthetic history supports controlled evaluation, not claims of real demand prediction or realized customer ROI.

### 13. Complete browser and integration coverage — limited evidence exists

Test the actual buyer, merchant and operator journeys through real application APIs and a migrated isolated database, with fake external providers explicitly identified. Assert durable state and effect counts in addition to visible text. Cover reload, double-click, concurrent tabs, cancellation, network loss, restart, permission denial and changed requirements.

**Finish:** repeatable Playwright journeys for selection/research, positive and refused qualification, bundle acceptance/refusal, bulk shortfall, supplier response, accepted amendment, approval, withdrawal and recovery; retain traces, screenshots, backend logs and state evidence.

### 14. Establish sustained reliability — incomplete

Predeclare thresholds for end-to-end latency, queue versus transport time, failures, stale-result rejection and resource usage. Require zero unauthorized effects, duplicate effects and unsupported qualification in the evaluated run. Derive performance thresholds from measured baseline behavior rather than inventing favorable numbers afterwards. Coordinate varied image/browser/model work with bounded runtime settings, cold/warm starts, cancellation, source failures and process restarts.

**Finish:** a repeatable 60-minute run followed by an explicitly timed overnight run (for example, eight hours), with every failure retained and analyzed. Record model residency, memory and relevant driver events. A short soak or repeated identical image does not substitute for this evidence.

### 15. Benchmark quality and finish CI/release evidence — partial

Freeze held-out buyer, product, supplier and adversarial cases across categories. Review labels independently where possible; otherwise disclose self-review. Measure supported qualification, abstention, compatibility, business-decision correctness, latency and operational failures. Compare baseline and candidate under the same data/runtime budget. Do not declare a model winner from small repeated smoke cases.

Run import/service/security/browser checks automatically; observe actual remote CI results, review required branch checks, archive artifacts and prove clean release/rollback locally or in staging. Packaging/container publication and production deployment are different claims.

**Finish:** reproducible comparison with declared criteria, passing automated release checks and an observed restore/rollback. New retrieval, graph, model or forecasting infrastructure requires a measured failure and held-out benefit first.

## Architecture discipline throughout

The active recommendation flow is V2 through the compatibility facade. Follow live callers before editing similarly named V1/V3 files. Extract responsibilities under behavior tests rather than adding another recommendation stack. Keep generic identity, tenant, revision, money, quantity, time, authorization and replay checks in the core. Keep electronics attributes, publisher parsers and workload-specific contracts in adapters/data with explicit semantics.

Deterministic arithmetic, freshness, revocation and permission checks are essential. Brittle rules are inferred intent, brand-to-capability shortcuts, category labels treated as certification, and fixture phrases promoted into policy. Moving those guesses to JSON does not fix them. Include non-laptop examples and unfamiliar synthetic subjects to detect accidental overfitting; electronics variety alone does not prove universal domain independence.

## Milestones and dependency order

| Milestone | Included work | Demonstration |
|---|---|---|
| M0 — reproducible foundation | 1–2 and current read-only fixture | Import/hold records, restore database, inspect 30/40/100 arithmetic. Partly delivered. |
| M1 — trustworthy recommendation | 3–4, focused 8, relevant 11/13 | Explicit buyer scope, supported recommendation and optional compatible bundle; negative cases remain truthful. |
| M2 — simulated commerce lifecycle | 5–7 and 9–10, relevant 11/13 | Shortfall → governed fake enquiry/reply → accepted revision → distinct-person approval → fake purchase → recovery. |
| M3 — useful merchant decisions | 5 and 12 | Replenishment decision from a reconciled transaction history and current scoped observations. |
| M4 — tested portfolio release | 13–15 plus reproducibility/architecture checks | Full recorded journeys, sustained evidence, held-out comparisons and reproducible CI/release artifacts. |

Testing accompanies each stage, not only milestone M4. Test-first behavior changes follow red → green → refactor; retain targeted regressions and expand testing when integration introduces new risks. Browser tests check complete workflows; unit tests do not substitute for them, and browser passes do not establish financial/authorization correctness by themselves.

## Exact next coding sequence

1. Extend the implemented selection and V2 binding checks through a complete positive buyer/browser journey, including read-only case operations and accepted amendments.
2. Connect the passing scoped core fixture to governed product-fact projection and shelf/trace presentation, with stale, conflicted and wrong-scope controls. Keep real Blender evidence gaps explicit.
3. Extend the new immutable fictional movement history into transactional reservations/order/return/cancellation events and varied supplier fixtures on the existing catalogue.
4. Connect one shortfall enquiry and parsed reply using fake transport; complete identity/approval and recovery checks before dispatching simulated purchases.
5. Extend browser coverage as each slice lands, then run the predeclared sustained and comparative evaluations.

Do not block this sequence waiting for customers, add more products merely to raise counts, or build a general derivation/graph platform before a demonstrated need. Genuine commercial operation, private data onboarding, real payments and claims of real business impact remain a separate optional roadmap.

## Evidence references

- [Electronics execution report](ELECTRONICS_SHOP_EXECUTION_2026-09-26.md)
- [Inventory assessment](ELECTRONICS_SHOP_ROADMAP_2026-09-26.md)
- [Contract compiler execution](CONTRACT_COMPILER_EXECUTION_2026-09-26.md)
- [Agnostic core and research review](AGNOSTIC_CORE_AND_RESEARCH_REVIEW_2026-09-26.md)
- [Portfolio scope and experience wording](PORTFOLIO_ROADMAP_2026-09-26.md)

The original consolidation made no implementation claims. The linked execution update records subsequent changes and their verification limits.
