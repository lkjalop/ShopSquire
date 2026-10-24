# Inventory expiry execution — 29 September 2026

This batch closes the persisted deadline and consumption-enforcement slice of the
operational inventory roadmap. It does not complete the conversational research,
supplier, approval or recovery journeys.

## Behavior

- New accepted stock requests create holds with a server-controlled 30-minute
  deadline. The internal adapter accepts a bounded duration policy; the buyer cannot
  submit a deadline or clock. Product-specific rules were not added to the core.
- Migration `20260886_inventory_expiry` persists optional UTC deadlines and indexes
  tenant/status/deadline. Existing holds retain no deadline; there is no invented
  historical expiry or automatic release of legacy reservations.
- Shipment independently rejects an expired hold, even before cleanup runs.
  A replay of a shipment already recorded as successful remains a replay.
- Tenant-scoped `expire_due` releases a bounded batch through the existing atomic
  inventory event ledger. Retries and concurrent workers cannot release stock twice.
  The caller owns authorization and commit; rollback restores both stock and events.
- A fresh accepted request cleans up a bounded batch of due holds in its tenant.
  Expiry cleanup is not yet scheduled continuously. Idle stock may remain reserved
  until explicit release, another accepted request or authorized maintenance.
- The stock API excludes expired holds from usable held quantity. Reads do not
  release stock. The buyer UI shows the persisted deadline and permits explicit
  release, including after expiry. Unreserved availability remains conservative
  until release actually commits.

## Evidence

Artifacts: `.artifacts/inventory-expiry-2026-09-29/`.

- `red.log`: four expiry regressions failed before implementation.
- `acceptance-red.log`: the accepted-hold deadline regression failed before wiring.
- `regression-final.log`: 28 tests passed across expiry, stock transactions, accepted
  requests, reconciliation and API behavior. Includes concurrent cleanup, bounded
  batches, deadline replay conflicts, wrong tenant, rollback and shipment replay.
- `browser.log`: two real-API Playwright journeys passed, including persisted
  deadlines, accepted quantity changes, reload, hold release and qualification
  invalidation. These browser tests do not simulate 30 minutes of server time;
  controlled-clock service tests cover the deadline boundary.
- `migration.log`: isolated demo database upgraded to migration 86.
- `architecture.log`: function-size check passed.

The prior diagnostic is now complete: 30 minutes, 39 cycles of three browser
journeys, passed. This did not reproduce or explain the historical Chromium
`ERR_NO_BUFFER_SPACE` failure. No eight-hour pass or model/image endurance claim.

## Still required

1. Connect conversational requirements and governed research to the fictional
   qualification presentation, keeping real-product evidence claims separate.
2. Schedule and observe scoped expiry cleanup; complete inbound receiving,
   transfers, and connected shipment/return workflows.
3. Connect supplier enquiry/reply, accepted quote and amendment cost/delivery
   consequences through fake transport.
4. Complete authenticated distinct-person approval and operator recovery UI.
5. Continue the remaining bundle, injection-evaluation, market-decision,
   benchmark, endurance and release gates in the comprehensive roadmap.

No real product was newly qualified, no real supplier was contacted, and no model
quality winner is established.
