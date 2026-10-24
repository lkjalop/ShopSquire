# Buyer contract execution — 27 September 2026

## Delivered

- Added case-scoped read/select/revoke endpoints. Selection requires the buyer's explicit context, the expected case revision and the contract revision the buyer reviewed. A stale writer or obsolete contract document returns a conflict. The endpoints grant no product-fit or commerce authority.
- Added buyer controls to the active-case panel and a reloadable case review surface (`?surface=case-requirements&case_id=...`). Selection is explicit, scope obligations/exclusions are visible, and changing/revoking it clears previous product/research/alternative projections and disables recommendation actions. The same component is used by both surfaces.
- Reproduced and fixed a cached-session bug: another session's revocation could be hidden by retained ORM objects. Binding and case reads now refresh stored values before consumption.
- Case-aware accepted-catalog projection now revalidates selection and evidence coverage. Revoked, stale or incomplete selections supply no executable claim set to product comparison. Coverage remains an additional gate, not a replacement for registry, source, identity or product-evidence checks. Duplicate external claim IDs cannot admit unrelated rows.
- Wired case context into interpretation, manual acceptance/corroboration, supplied-source, enrolled-source and open-world catalogue projections. Extracted a small case-projection adapter so those callers retain the binding without enlarging their functions.
- Enrolled-source research captures a binding before fetching, rechecks after the fetch and before decision persistence, filters claims under the selected contract and includes the receipt in its trace. A changed selection causes a typed conflict; raw held claims remain available as research diagnostics rather than qualified requirements.
- Added the tests to the clean-checkout CI workflow, including the case-selection browser test. Remote CI success has not been observed in this session.

## Verification

Recorded failing tests before implementation for missing endpoints/controls, cached revocation and case-aware catalogue consumption. The first cross-session test needed a fixture correction to query the case's actual primary identity; the retained red log then reproduced the intended missing revocation error.

- **102 backend tests passed**, no failures/errors/skips, across contract endpoints, binding/consumption, accepted catalogue projection, existing requirement acceptance, contract compilation and coverage. Includes an actual enrolled-research function call with a fake provider that revokes the selection during the fetch; the result is rejected with `case_contract_changed_during_research`.
- **One component test passed** for explicit selection, revision payload, revocation and parent notification.
- **One Playwright journey passed** against the running full FastAPI application and copied migrated SQLite database: create a case via the real API, open two tabs, select in one, reject the stale second writer, reload, revoke and reload again. No API responses were mocked. This verifies the shared controls through the case-review surface; it is not a full chat/research/qualified-product browser journey.
- Frontend production build, function growth ratchet, source growth ratchet, undefined-name checks and targeted whitespace checks passed. Existing oversize-file warnings remain; baselines were not raised.

One older auto-research test relied on the legacy environment override that the current policy deliberately ignores. Its fixture now explicitly selects the existing `demo-safe-auto-v1` profile. Production consent policy was not relaxed. The budget-projection test's spy was moved to the extracted adapter's consumer; its budget/quantity assertions remain unchanged.

Evidence directory: `.artifacts/contract-journey-2026-09-27/`, including `final.xml`, red/green logs, `browser-green.log` and `build.log`. Browser trace/video/screenshots are archived with the checkpoint. The isolated database is `shop.sqlite3` in that directory, copied from the prior synthetic shop using SQLite backup and checked with `integrity_check`.

## Remaining boundaries

This completes a tested selection/revocation and case-projection slice, not the entire contract or portfolio milestone.

The top-level V2 recommendation flow still requires a complete audit of persisted binding propagation and qualification receipts. Open-world and supplied-source paths now apply the gate at catalogue consumption, but do not yet have equivalent in-flight binding-change tests across their entire workflows. PostgreSQL concurrency/locking semantics are not established by these SQLite checks. A revision-bound effect receipt and dispatch-time authorization remain separate work.

Buyer endpoints retain the repository's existing tenant-header and buyer-UID ownership convention. This is not authenticated distinct-person commerce approval and must not be described as such. Future identity work needs server-controlled people, roles and membership before real effects.

No product was newly qualified. Blender applicability/compatibility evidence remains incomplete. Fixture-backed positive recommendation, live evidence qualification, persistent operational event streams, supplier conversations, approvals/recovery, sustained reliability and representative benchmarks remain open. No model winner or production readiness claim follows from this batch.
