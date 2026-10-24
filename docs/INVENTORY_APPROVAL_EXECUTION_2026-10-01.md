# Connected fictional inventory evidence

Roadmap item 6 is complete for the local SQLite fictional-shop scope. It does not
certify real fulfilment, PostgreSQL concurrency or the complete effect-recovery
workstream. Items 8 and 9 retain their amendment-economics and other-effect gates.

Implemented and exercised:

- Receiving and transfers use idempotent document references and atomic stock
  updates. Transfers cannot consume reserved units, oversell or lose one leg.
- Accepted buyer reservations connect to operator requests for shipment,
  cancellation and partial returns. The server binds the reservation, SKU, case
  and revision; a changed revision prevents dispatch.
- The API derives requester and approver principals from authenticated credentials.
  Server-controlled synthetic enrollment maps two requester credentials to one
  person. Both are rejected as approvers; a different enrolled person can approve.
  Inventory valuation is calculated from the stored product price, not browser input.
- API/UI execution revalidates exact approval, expiry, revocation and current
  memberships. Repeated execution returns the recorded completion without another
  stock event. Completed historical receipts remain readable.
- The buyer sees live holds, shortfalls, shipped units and returned units.
  Shipping no longer misrepresents already shipped units as an unsupplied shortfall.
- Reconciliation includes opening history, reservation effects, receipts and both
  transfer legs. Seeder reset refuses to overwrite transactional movement history.
- Scheduled expiry is bounded and opt-in. A real browser test creates a short-lived
  accepted fixture hold, observes its automatic release, and checks exactly one
  durable expiry event. The fixture setup uses an internal local-only script; no
  HTTP endpoint allows a buyer to manipulate the clock.

The first live expiry run failed. Investigation found that registration via startup
hooks did not execute under the application's custom ASGI lifespan. The explicit
business-lifecycle bridge repaired this. A further startup test prevented awaiting
an already-running infinite background Task. The failed artifacts remain preserved.

Evidence under `.artifacts/roadmap-execution-2026-10-01/`:

- `inventory-connected-backend.xml`: receipt/transfer, person and scheduler regressions.
- `order-lifecycle-green.xml`: 22 accepted-order, movement and reconciliation tests.
- `operator-browser-v2.json`: independent-person receipt/transfer journey passed.
- `inventory-memory-browser.json`: both inventory browser journeys passed; the
  overall run retained one separate memory failure, subsequently repaired.
- `restart-expiry-browser-v2.json`: scheduled-expiry browser test passed; the separate
  memory isolation test failed because its tenant request hit duplicate detection.
- `lifecycle-bridge.xml` and the additional infinite-Task startup regression.

Primary implementation files:
`src/app/services/inventory_transactions.py`, `inventory_expiry_scheduler.py`,
`operator_inventory_requests.py`, `shop_operational_history.py`,
`src/app/routers/admin_inventory.py`, `portfolio_qualification.py`,
`frontend/src/components/InventoryOperationsPanel.tsx`, `StockAcceptancePanel.tsx`,
`frontend/e2e/operator-inventory.spec.ts`, `inventory-scheduler.spec.ts`.

No money, real shipment or external supplier message was sent. Enrollment asserts
fictional people for the demonstration; it is not real identity verification.
