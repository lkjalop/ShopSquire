# Request replay and resource diagnosis — 28 September 2026

## Delivered and tested

Supplier fulfillment selection now binds an idempotency key to the complete original
request: tenant, case, buyer, revision, choice, SKU, quantity, available stock, deadline,
offers and revision mode. Reusing the key with changed intent returns a conflict rather
than silently returning the old selection. Exact retries retain the original result.
The accepted-stock adapter uses this same check. This is a generic integrity boundary,
not a product- or workload-specific qualification rule.

Migration `20260885_fulfillment_request_binding` adds the persisted request digest.
Historical rows without a digest remain readable but fail closed on replay; their
original inputs cannot safely be reconstructed. Clients must refresh current state
before issuing a new action. This migration was applied to the isolated demo database.

Evidence is under `.artifacts/resource-investigation-2026-09-28/`:

- `replay-red.log`: initial regression failures before implementation.
- `regression-final.log`: 34 supplier, accepted-stock and API tests passed.
- `stock-replay-final.log`: nine stock/API tests passed after routing stock replay
  through the shared request binding.
- `browser.log`: two real-API Playwright journeys passed: accepted quantity changes
  and fictional qualification, including invalidation and reload.
- `network-smoke/status.json`: two cycles, six browser tests, 35.204 seconds;
  both Chromium network logs parse successfully. This is diagnostic validation,
  not an endurance result. Three soak-harness tests also passed.

## Correction to the resource hypothesis

Neither historical eight-hour attempt passed: the first stopped after 7h11m51s,
the instrumented rerun after 19m38s. Both reported Chromium `ERR_NO_BUFFER_SPACE`.

Backend handle growth alone does not establish a leak. The live request-and-idle
probe recorded 1,236 handles before 30 requests, 1,703 immediately afterward,
1,242 after five idle seconds and 1,214 after ten seconds. Memory remained about
315 MB. An isolated warm probe also observed tracing objects accumulate and drain.
These observations weaken the retained-handle hypothesis; they do not identify
the Chromium failure's root cause or establish sustained stability.

The soak runner now optionally accepts `--net-log` and captures a separate Chromium
network log per cycle alongside existing process/socket/resource measurements.
No sensitive capture mode, longer browser timeout, automatic retry or weakened
assertion was introduced. Logs concern the isolated fictional shop and should remain
local diagnostic artifacts. A longer diagnostic is a reproduction attempt, not a fix.

## Remaining connected milestone

Accepted request and stock amendment work through the browser. Supplier enquiry,
fake send, reply review, independent authenticated approval and operator recovery
still need a connected API/UI journey. The complete remaining work and acceptance
criteria remain in [the comprehensive roadmap](COMPREHENSIVE_ROADMAP_2026-09-27.md).
No real product was newly qualified; no model winner or production-readiness claim
is supported by this batch.
