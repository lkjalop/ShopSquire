# Simulated supplier conversations and amendments

`frontend/e2e/supplier-enquiry-journey.spec.ts` passes against the real isolated
API and database. `supplier-browser-v5.json` under
`.artifacts/roadmap-execution-2026-10-01/` records one passing connected journey,
zero skips/retries, with trace and durable-state attachment.

The buyer accepts 30 units using the existing stock-acceptance UI. An authenticated
operator drafts an enquiry from the server's accepted selection and current holds;
the browser cannot supply the transaction amount or an outbound address. The
requester's other credential is also rejected as an approver. Another enrolled
person approves the exact enquiry and the existing outbox dispatches it through
fake transport. Replaying dispatch leaves the durable attempt count at one.

Structured simulated replies cover partial supply, an unverified substitute,
wrong sender, expired terms, full coverage and duplicate delivery. An operator
must review usable terms. No reply and no review grants purchase authority.
Silence remains awaiting-reply; a substitute does not acquire compatibility.

Accepting 40 units advances the same buyer case revision. Old quotes become stale
when read, and old approvals fail at dispatch. A new enquiry requires new
independent approval. Its server-calculated value increases with quantity, and
the reviewed quote computes revised freight, landed cost and delivery. The test
specifically verifies that a lower unit cost can still mean higher total spend.

`supplier-precision-green.xml` records 58 passing supplier, person-approval,
outbox/deferred-send and retrieval regression tests. Additional tests prove an
already queued enquiry cannot dispatch after its case revision changes.

The browser exposed a real precision defect: the outbox truncated its clock to
whole seconds and intermittently rejected a just-issued subsecond approval. A
failing-then-passing regression now preserves clock precision through dispatch.
An earlier API integration failure also exposed the local database result
wrapper's requirement to call `mappings().all()`; the corrected route passes.
Earlier failed artifacts remain available.

Scope: local fictional identities enrolled from server-controlled credentials;
structured operator-driven supplier simulation, not an authenticated real
mailbox or free-form email understanding benchmark. Provider uncertainty,
revocation/renewal screens and broader sink recovery remain item 9. PostgreSQL
concurrency and production identity-provider integration are not certified by
this SQLite demonstration.
