# Connected buyer stock acceptance — 28 September 2026

## Delivered

The fictional qualification surface now supports explicit stock acceptance and quantity amendment
against the canonical inventory table. It reuses the existing fulfillment-selection records and
case-revision authority; it does not introduce another catalogue or order state machine.

The connected browser demonstration is:

1. Select the fictional RAM contract and qualify its configuration.
2. Accept a 30-unit stock request: hold the 15 available units and show a 15-unit shortfall.
3. Advance the case revision and invalidate the previous qualification selection.
4. Accept 40 units: release the old holds and allocate replacement holds in the same transaction.
   The case holds 15 units, not 30, and the shortfall becomes 25.
5. Reload and see the persisted 40-unit request and actual available stock.
6. Explicitly release the holds; the 15 units become available again. This releases stock,
   not a purchase or a paid order, and the requested quantity remains visible.

The API derives the SKU from the server-owned fictional configuration and stock from the database.
The client cannot submit an authoritative available quantity or price. Demo routes require the
explicit demo flag and check ownership of the retained fictional case. This uses the existing
demo buyer UID model; it is not a production identity-provider integration.

The inventory acceptance service validates buyer, tenant, SKU, quantity, revision and command key.
Changed-payload replay and stale amendments are rejected. Revision, selection and stock effects
commit or roll back together. Existing selection callers keep their default commit behavior; this
adapter opts into caller-owned commit. Full supplier/approval/purchase integration remains open.

The actual qualification projection now receives current inventory observations from its trusted
server adapter, rather than continuing to display a seeded 15-unit snapshot after reservation.
The ordinary projection path still reads its evidence tables. No new override is exposed to buyer
or model payloads. Observations remain explicitly synthetic and use the fixture's simulation clock.

## Failures found and repaired

- The new service tests initially failed because the integration did not exist.
- The first real browser run exposed SQLite `database is locked` while upgrading a deferred read
  transaction to a writer. Inventory transactions now use `BEGIN IMMEDIATE` when opening their own
  SQLite transaction. The connected browser journey then passed.
- The broader supplier API suite exposed a fixture missing `conversation_case_amendment`. Its setup
  now uses actual migrations instead of the old partial `db/schema.sql` bootstrap. Both failures passed
  after the fixture correction; application behavior was not weakened to hide them.
- A stock regression exposed stale availability from the seeded qualification observation. The
  trusted adapter now supplies current stock. Zero available stock produces no available product;
  restoring one unit per location produces the correct three-unit availability.

## Verification and artifacts

Evidence directory: `.artifacts/connected-shop-2026-09-28/`.

- `acceptance-red.log`, `release-red.log`, `live-stock-red.log`: retained test-first failures.
- `regression-final.log`: 36 tests passed across new acceptance/API, existing supplier services/API,
  inventory transactions and reconciliation, before the final release/live-stock additions.
- `stock-final.log`: 45 final focused acceptance, release, live-stock projection and inventory/API regressions passed.
- `browser-final.log`: five real-API Playwright journeys passed, including accepted 30-to-40 amendment,
  reload, qualification invalidation and hold release. The existing read-failure test injects a network
  failure; successful responses use the real API. Traces/video/screenshots are retained.
- `frontend-build.log`: production build passed. Function-size and scoped F821 checks passed.
- `shop.sqlite3`: fresh isolated database seeded from the existing source, with 98 admitted records.
  Tests release the stock they reserve; earlier failed-test evidence and databases were preserved.

## Soak remains a failed gate

The instrumented rerun failed on cycle 17 after 1,178.015 seconds (19m38s), with 16 successful cycles
and the same Chromium `ERR_NO_BUFFER_SPACE` at requirement loading. It did not reach 60 minutes.

Recorded backend handles rose from approximately 1,960 after cycle 1 to 4,700 after cycle 17.
Available host memory stayed above 6 GB in those samples; peak TCP TIME_WAIT was 511 at cycle 17.
An additional 30-request probe increased backend handles from 4,726 to 5,004. A separate in-process
probe retained handle growth after garbage collection, but also included application/mapper warmup.
These measurements support further investigation; they do not prove that a particular allocation
caused Chromium's error. Files and active TCP sockets did not account for the handle total.

No fresh eight-hour run has been launched in this batch. Next reliability work is allocation-type
and warm-baseline diagnosis, followed by a regression and an instrumented rerun. The browser
qualification/stock passes do not close the endurance gate.

## Remaining connected milestone

Stock acceptance/amendment/release is now connected. Supplier enquiry/reply and reviewed offers,
landed cost/deadline recalculation, independent authenticated approval, fake purchase dispatch and
operator recovery are still not connected into this buyer browser journey. Reservation expiry,
inbound receiving, transfers, bundles, systematic attack evaluation, merchant decisions, model/image
endurance, held-out comparisons and remote CI/release evidence remain open. No real product was newly qualified.
