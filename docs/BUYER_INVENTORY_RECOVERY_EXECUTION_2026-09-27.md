# Buyer, inventory and recovery execution — 27 September 2026

This continues the comprehensive roadmap for a fictional electronics shop. No real product was
newly qualified; no real supplier message, payment or purchase was authorized or sent.

## Delivered and verified

| Area | Change | Evidence and limit |
|---|---|---|
| Positive buyer journey | A persisted buyer case selects `fictional-memory-lab-v1`; the actual requirement compiler and accepted catalogue projection qualify an explicitly fictional configuration linked to an existing catalogue product. UI and trace show the same binding. | Real-API Playwright selects, qualifies, reloads, expires evidence and revokes selection. This is a bounded compiler/shelf journey, not a real-publisher Blender result or a complete conversational research run. |
| Agnostic qualification | A server-selected contract supplies completeness obligations. Unbound evidence keeps the existing manifest requirements. Source data cannot select the contract. | The previous blanket six-field completeness check blocked the valid one-obligation fixture. Selected-contract coverage replaces that check only after current persisted binding validation. No brand/Blender phrase shortcut added. |
| Inventory transactions | Tenant-scoped reservation, cancellation, shipment and partial-return events update canonical stock atomically. Immutable command digests prevent changed-payload replay. | Tests cover concurrent no-oversell, replay, over-return, cross-tenant access and outer rollback. Fixture reseeding now refuses SKUs with transaction history. These remain internal services; checkout, inbound receiving, reservation expiry and reconciliation UI are open. |
| Distinct-person approval | Stable person bindings link multiple credentials to one person. Grants bind exact outbound bytes, tenant, actor and spend; dispatch rechecks membership, person mapping, tier, revocation and expiry. | One person with two credentials is rejected. Changed bytes, stripped grants, revoked memberships and expired grants are blocked. A test caught expiry during integrity scanning; elapsed time is now checked immediately before dispatch. Authenticated enrollment/request/approval routes are not yet connected. |
| Operator recovery | An authorized internal operator principal can record a provider observation for an uncertain send, with evidence reference and immutable audit receipt. | Submitted becomes `submitted_unverified`; not delivered becomes a non-dispatchable terminal state. Neither resends or acknowledges the message. Replay, conflicting observations, cross-tenant access and transaction rollback are tested. Evidence is an operator assertion, not independently fetched provider proof. UI and fresh-approval renewal remain open. |
| Supplier fixtures | Quotes retain cents and accept an explicit simulation date; historical default dates remain reproducible. | Focused tests and existing supplier/channel/quote workflow regressions pass. This is a generator repair, not completion of the multi-supplier browser conversation. |

## Verification record

Artifacts: `.artifacts/portfolio-journey-2026-09-27/`.

- `backend-regression-final.log`: 462 backend tests passed across fulfillment, inventory,
  qualification/projection, persisted contracts, V2 binding, requirement compiler and shop scenario.
- `recovery-final.log`: 8 recovery tests passed, including the additional rollback/conflicting-replay test.
- `soak-runner-green.log`: 2 duration-runner tests passed. These are harness tests, not elapsed soak evidence.
- `browser-final.log` and `browser-final/`: 3 Chromium clickthroughs passed against the real local API,
  with traces, screenshots and video. No API-response mocks in these journeys.
- `frontend-unit.log`: contract-selection component test passed.
- `frontend-build-verified.log`: Vite production build exited zero. The shared static/dynamic-import
  warning is informational; the initial PowerShell redirection misleadingly reported a command error.
- `clean-rebuild.log`: a new isolated database migrated through revision 84 and seeded 98 admitted
  source records, preserving held records in its report. The running isolated demo database also
  upgraded from revision 81 through 84 successfully.
- Function-size checks and scoped Ruff F821 passed.
- The broader run exposed an obsolete unsigned-JWT positive test. It now checks unsigned rejection
  and a properly signed positive token. Authentication was not weakened to satisfy the old test.
- Red logs preserve failures for the shelf contract, inventory, person approval, dispatch-time expiry,
  supplier quote, recovery, reseeding and duration harness changes.

## Long-run status and scope

An eight-hour run started around 21:10 Sydney time on 27 September. Its live record is
`.artifacts/portfolio-journey-2026-09-27/overnight-browser/status.json`; the launcher PID is recorded
in `overnight.pid`. The initial cycle passed. **At the time this report was written, neither the
60-minute checkpoint nor the eight-hour finish had been reached.**

Every cycle runs three browser journeys with retries disabled, a 180-second cycle timeout and
60 seconds between cycles. The runner stops on failure or a changed source fingerprint. It records
actual elapsed time, successful cycles and a 60-minute checkpoint; completion requires the requested
duration and adequate cycle count. It uses the existing isolated API on 8087 and frontend on 5177.
Closing those servers or sleeping the machine affects the run. A process that is stopped cannot be
treated as passed merely because its last status was `running`.

This replay measures browser/API continuity across these three fixture journeys. It does not cover
varied images, live mixed-model inference, cold starts, server restarts, cancellation or all effect sinks.
No claim of sustained model stability, full pilot readiness or a model quality winner follows from it.

## Remaining execution order

1. Connect transactional holds and operational event reconciliation to the buyer's accepted revision;
   ensure stock shown by the qualification fixture is not mistaken for a live post-transaction snapshot.
2. Complete one supplier enquiry/reply and the accepted 30-to-40 amendment through the existing
   fulfillment workflow and fake transport. Invalidate old offers and grants on revision changes.
3. Connect authenticated requester/approver endpoints and stable person enrollment; calculate spend
   from trusted transaction data. The current internal service takes caller-supplied authenticated
   principal hashes and spend. Keep real transport containment until the entire boundary is proven.
4. Expose recovery observations and revocation/renewal through authenticated operator UI. A confirmed
   non-delivery needs a new exact-effect approval before a replacement message; uncertainty cannot
   be retried automatically. Add reservation expiry/reconciliation and remaining sink coverage.
5. Add Playwright coverage for those connected workflows. Inspect the running browser soak and then
   run the separately defined image/model, cold-start, cancellation and restart endurance tests.
6. Derive a synthetic replenishment decision from reconciled events; finish independently reviewed
   relevance labels and held-out comparisons. Complete second-environment restore and CI/release evidence.

The full 15-stage roadmap remains in `COMPREHENSIVE_ROADMAP_2026-09-27.md`; these changes do not close
its compatibility/bundle, security-evaluation, merchant-decision, benchmark or release gates.
