# Electronics shop execution — 26 September 2026

## Delivered and verified

Implemented catalogue boundary fixes with recorded failing tests first, followed by a synthetic stock/supplier assessment using existing commerce tables and a browser-accessible read-only scenario.

- The legacy parser distinguishes all-in-one, mini-PC and desktop-tower entries, excludes the document's metadata sections, holds explicit and repeated-title price conflicts, and retains raw observations with hashes. It no longer invents Thunderbolt 4 support from any mention of the word.
- Repeated titles are provisional identity matches. Differing observations remain held; they are not authoritative variant reconciliation. These changes do not replace a full exact-configuration importer or automatically migrate historical SKU references.
- The isolated database was created through Alembic to `20260880_case_contract_selection`. Of 105 reconciled snapshot records, 98 have an admissible snapshot price and seven remain held. This does not make historical prices current or product facts manufacturer-verified.
- The configurable fixture uses existing `inventory_level`, `price_book_entry`, `suppliers`, `supplier_products` and `supplier_offer` tables. Stock derives from opening/sold/returned counts and reservations: 15 unreserved units across three locations. Supplier costs, minimum quantity, volume pricing, expiry, immediate quantity and later quantity are explicitly synthetic.
- Real migration testing found the older supplier-products `id` schema differed from the service's minimal composite-key schema. Added a failing regression test and reused the existing schema-compatible insertion helper.
- Requests for 30 and 40 units produce shortfalls of 15 and 25, different request digests and updated totals. A 100-unit request leaves 60 units uncovered after the supplier's capacity is exhausted. Future arrivals are never counted as immediate stock. Expired supplier offers are excluded by the existing supplier-cost reader.
- Added `GET /api/v1/demo/electronics-shop`, gated by `ENABLE_DEMO_ROUTES`, restricted to the fixed synthetic tenant and seeded scenario SKUs. It replays the declared fixture clock and cannot send, buy, reserve or approve anything.
- Added the frontend `?surface=electronics-shop` scenario view. Editing quantity clears the old result; recalculation shows stock, shortage, pricing, partial supplier capacity and explicitly unconfirmed delivery.

## Reproduction

Create a new database (existing paths are refused):

```powershell
.venv/Scripts/python.exe -m scripts.seed_electronics_shop --database .artifacts/my-electronics-shop.sqlite3
```

Point both `DATABASE_URL` and `DATABASE_URL_RO` at that database, enable demo routes, and launch the application with `APP_ENV=local`. Configure the frontend API target to that backend. Visit `/?surface=electronics-shop` and assess 30, 40 and 100 units. No model or external supplier service is required for this read-only arithmetic scenario.

Local verification used backend `127.0.0.1:8087`, frontend `127.0.0.1:5177`, and `.artifacts/inventory-roadmap-2026-09-26/shop-v2.sqlite3`. The first `shop.sqlite3` is a preserved failed schema-integration attempt, not the successful dataset. Seeding resets scenario quantities and must not be called mid-journey.

## Evidence

- **48 tests passed** across import boundaries, seed-source consistency, the API gate, scenario behavior and existing commerce/supplier services: `.artifacts/inventory-roadmap-2026-09-26/final.xml`.
- **One Playwright clickthrough passed**, covering 30 → 40 → 100 against the running full FastAPI app and seeded database, without API route mocks: `.artifacts/inventory-roadmap-2026-09-26/browser-final.log`; trace/video/screenshots in `frontend/test-results` and the checkpoint archive.
- Frontend production build, function-size ratchet, undefined-name checks and targeted diff whitespace checks passed.
- Red evidence retained for import behavior, missing scenario implementation, migrated supplier schema, API route, browser view and supplier capacity. Sets overlap; do not add their counts to the final 48.
- Clean-checkout CI now includes the new regressions, migrated fixture creation and the browser test with failure artifacts. This workflow has not yet been observed running remotely.

## What remains open

This is an integrated, read-only supply assessment foundation, not the whole buyer-to-purchase showcase. It deliberately grants no fit or commerce authority.

The fixture currently repeats the same illustrative stock pattern across products and uses one fictional supplier per SKU. Sales/returns are conserved fixture inputs and stored in offer provenance; a transactional order/return/cancellation event stream is not implemented here. Incoming quantities are supplier observations, not confirmed purchase orders. Compatible bundles, substantiated upgrades, actual supplier message/reply workflows, accepted quantity changes, reservations, person-bound approvals and timeout/retry recovery still require their own integration and tests.

Persisted buyer contract API/UI integration and consumption-time enforcement, full effect coverage, injection tests, varied sustained/overnight testing and representative quality benchmarks remain open. The browser result is one arithmetic clickthrough, not a full buyer journey or reliability soak. Keep the existing bounded Blender qualification gap visible; synthetic inventory does not close its evidence obligations.
