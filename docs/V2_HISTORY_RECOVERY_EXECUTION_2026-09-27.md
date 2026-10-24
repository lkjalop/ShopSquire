# V2 binding, fictional-shop history and uncertain delivery — 27 September 2026

This execution advances the comprehensive roadmap; it does not close the complete shop demonstration or reliability gates. No real product was newly qualified and no external supplier message was sent.

## Implemented

### V2 case binding

The outer V2 recommendation boundary reads the database-owned tenant/buyer/case selection, checks the supplied case revision, and revalidates after execution. Missing, stale or revoked bindings hold the result without allowing a compatibility fallback to unbound qualification. A selected contract also requires a matching successful compiler receipt. The semantic evidence stage receives the selected contract and context from storage rather than provider fields.

The API adapter now carries the binding receipt, and execution traces include the same receipt. A revocation during a turn reports the newly observed revoked state. Holds retain prior failure reasons and stage timings. Unbound exceptions retain their original core failure classification. Shadow jobs now carry canonical case state through serialization.

Existing read-only procurement status/summary operations remain usable with a valid selection and no compiler run. A negative control proves that adding a product to such a response still triggers the compilation guard. Revision and revocation checks continue to apply.

Compiler receipt and trace-stage projection helpers were extracted without raising function-size baselines. These are generic identity, revision and evidence checks; no new application-name, SKU or keyword qualification rules were added.

### Positive qualification evidence and its limit

An isolated test now selects and persists a fictional version/platform/workload contract requiring 32 GB RAM. It runs the actual V2 core with controlled router/provider outputs, the actual registry compiler and catalogue comparison, and the actual API adapter. The 32 GB fixture product passes; the 16 GB candidate does not. An expired claim blocks the selected-contract result. The binding and compiler revision agree, with commerce authority remaining none.

This uses a RAM-only test contract and test catalogue. It is not Blender qualification, a refreshed manufacturer configuration, an independent review of source evidence, or a completed positive browser journey. The real buyer showcase remains open.

### Operational history

Migration `20260881_synthetic_shop_history` persists immutable synthetic history snapshots per tenant/SKU/scenario. They contain opening, sale, return and reservation events with sequence, fixture source and observation time. Replay derives location balances. Duplicate seeding is idempotent; conflicting history requires a new scenario identity. Malformed or impossible balances are rejected before recording. History reads do not create tables or change stock.

The existing August inventory seeder now records history alongside the existing commerce balances. A newly migrated isolated database contains the same 98 priced snapshots; seven records remain held. The API and browser show the replayed movements and location balances alongside the quantity assessment.

These are explicitly reconstructed fictional observations, not executed orders. Transactional reservation/cancellation/return processing, concurrency, transfers, varied per-SKU demand and confirmed inbound purchase orders remain unfinished. This is not a replacement operational ledger for production inventory.

### Uncertain supplier delivery

New failing tests demonstrated that provider exceptions and unknown results were automatically retried. A timeout after possible provider acceptance could therefore duplicate a message. The queue now moves these outcomes to `reconciliation_required`, with no automatic resend or completion claim. SMTP distinguishes failures before transmission from errors after starting the send. Known pre-send failures retain their existing retry behavior.

This closes that duplicate-send path. It does not supply the operator reconciliation/renewal workflow, prove provider-side exactly-once delivery, reconcile stock reservations or complete distinct-person approval. The default transport selector still blocks real SMTP delivery pending independent-person approval. Adapter tests use fake providers.

## Verification

Evidence directory: `.artifacts/v2-contract-2026-09-27/`.

- Red/green records cover binding bypass/revocation, dropped API receipts, lost failure/timing details, operational-history creation, missing browser history, and unsafe retries after uncertain sends.
- `final.xml` / `final.log`: 343 tests passed, zero failures/errors/skips, in the combined V2, contract, scenario, API, transport and recovery regression run. Earlier focused runs overlap this total.
- `positive.log`: three actual-core compilation scenarios, including the selected-contract positive fixture and expired-evidence negative control.
- `browser-final.log`: two Chromium clickthroughs passed in 4.9 seconds against the restarted full API and migrated isolated database. They cover two-tab selection/reload/stale-write/revocation and 30 → 40 → 100 quantity assessment with operational history. No API mocks.
- `browser-red/`, `browser-green/` and `browser-final/`: recorded browser artifacts.
- `seed.log`, `shop.report.json`: clean schema upgrade to migration 81 and fresh catalogue/scenario seed, without overwriting an existing database.
- `build.log`: production frontend build passed. Function/source growth checks passed without baseline increases; existing oversize warnings remain. Targeted undefined-name checks passed.
- CI smoke configuration includes the new binding and history tests. No remote CI execution is claimed.

The browser checks are short integration checks. No new 60-minute or overnight result is claimed. The earlier 45-call mixed-model run remains roughly six minutes and establishes neither sustained stability nor a quality winner.

## Remaining execution order

1. Carry the scoped positive fixture through the actual buyer case, research consumption, product-fact projection, shelf and browser trace. Keep real Blender gaps separate. Verify supported read-only case operations and amendments remain usable under selected contracts.
2. Replace reconstructed movements with transactional reservation/order/return/cancellation workflows and reconciliation, using existing catalogue identities.
3. Connect shortfall enquiries, independently attributed simulated replies, quote expiry, substitutions and accepted 30 → 40 amendments. Require fresh approval when the accepted effect changes.
4. Map authenticated credentials to stable people and enforce tenant, spend tier and separation at dispatch, including two credentials belonging to one person. Complete approval revocation/renewal and operator recovery from uncertain provider outcomes.
5. Run the connected browser workflows through cold starts, cancellation, failure and restart scenarios; then the predefined 60-minute and overnight mixed-model/browser-image runs. Preserve actual elapsed time, failures, model digests and image diversity.
6. Complete a traceable replenishment decision, held-out comparisons and release/rollback evidence. No real customer access is required for the fictional-shop milestone.
