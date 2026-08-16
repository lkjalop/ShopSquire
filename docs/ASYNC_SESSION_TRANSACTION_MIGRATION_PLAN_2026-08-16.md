# ShopSquire AsyncSession transaction migration plan

Date: 2026-08-16  
Status: transitional bounded-worker isolation implemented for four async shopping-case routes;
full AsyncSession transaction migration remains outstanding. No production database authority
is implied.

## Purpose

Several `async` shopping-case handlers still use synchronous SQLAlchemy sessions. Network
research is now asynchronous, but synchronous database calls can still occupy the event-loop
thread. The safe correction is not a mechanical `Session` to `AsyncSession` replacement. Each
buyer operation needs one explicit transaction boundary, and external I/O must not keep a
database transaction open.

## Invariants

- A SQLAlchemy session is request/task scoped and is never shared across threads or tasks.
- External discovery, publisher fetches, model calls and supplier calls run outside open DB
  transactions.
- Every state-changing command carries the shopping-case revision and an idempotency key.
- Stale revisions fail visibly; retries cannot duplicate claims, offers, cart lines or outbox
  messages.
- Cancellation rolls back uncommitted DB work. Results arriving after cancellation are
  quarantined and cannot update the active case.
- V2 continues through its current compatibility facade until equivalent behavior is certified.

## Target structure

```text
HTTP route
    |
    v
typed command + identity/tenant context
    |
    v
application service
    |
    +-- short AsyncSession transaction: read + reserve revision/outbox intent
    |
    +-- external work outside transaction
    |
    +-- short AsyncSession transaction: compare revision + persist result
    |
    v
typed response projection
```

The application service owns the transaction. Repositories accept an existing `AsyncSession`;
they do not call `commit()` independently.

## Complete transaction boundaries

### 1. Research authorization and same-case reranking

Transaction A atomically validates the case revision, records buyer authorization, freezes the
research plan and marks an execution attempt pending. Commit before network work. Discovery,
official-origin retrieval, parsing and criticism then execute without a DB lock. Transaction B
reloads the case, rejects a stale/superseded attempt, stores receipts and accepted claim
observations, computes/persists the new case revision and writes the reranking event/outbox row.

### 2. Requirement-proposal acceptance

One transaction validates proposal ownership and revision, stores accepted/edited/rejected claim
decisions, updates the case requirement ledger and increments the case revision. Acceptance and
the resulting ledger can never be observed independently.

### 3. Supplier selection

One transaction validates case/offer freshness, selected quantity, substitution consent and
buyer authority, then persists the revision-bound fulfilment selection. Supplier communication
is an outbox intent, never an inline side effect inside the transaction.

### 4. Cart confirmation

One transaction claims the idempotency key and validates the case revision and pending cart
mutation. Cart lines, plan status, audit outcome and outbox record commit together. A repeated key
returns the original result; a changed revision fails without mutation.

### 5. Ingestion and Hippograph observations

One transaction stores source receipt, watermark, normalized observations, contradiction and
supersession edges, then advances the source watermark. A failed batch leaves the previous
watermark intact and writes a separate dead-letter record.

## Migration sequence

1. Introduce an `AsyncEngine`, `async_sessionmaker` and `get_async_db` alongside the existing
   synchronous dependency. Fail startup when the selected runtime profile lacks its required
   driver; do not silently fall back.
2. Add async repositories for shopping cases, requirement decisions, research attempts,
   fulfilment selections and cart mutations. Preserve the current sync repositories for V2 and
   unmigrated routes.
3. Migrate one complete application-service boundary at a time in the order listed above.
4. During transition, isolate unavoidable synchronous DB work with a bounded worker adapter.
   Pass scalar/typed data across that boundary, never a live `Session` or ORM instance.
5. Add an outbox dispatcher with retry/idempotency for supplier and other external effects.
6. Remove the synchronous route dependency only after route ownership and compatibility tests
   show no callers remain.

## Implemented transitional boundary

The public requirement-acceptance, evidence-source-resolution, publisher-approval and research
routes no longer execute a synchronous `Session` on the ASGI event-loop thread. Each operation
creates, uses and closes its session inside a bounded worker, propagates disconnect/timeout as a
cooperative cancellation signal and returns a typed 504 when the 45-second envelope expires.

This is isolation, not completion of the target AsyncSession design. In particular, the research
operation may retain a worker-owned session while governed network work executes. The target
two-transaction research workflow above remains the correct next migration: reserve/commit,
perform network work without a session, then compare-and-persist in a second short transaction.

## Concurrency controls

- PostgreSQL: use row locks for short critical sections where appropriate and retain revision
  compare-and-swap as the business invariant.
- SQLite/local tests: rely on revision compare-and-swap because row-lock behavior differs.
- Bound pool size, checkout timeout and transaction duration. Emit typed pool saturation and
  transaction timeout metrics.
- Never retry a whole transaction around non-idempotent external work.

## Acceptance tests

- cancellation before commit rolls back;
- cancellation during external research leaves a visible cancelled attempt and no accepted
  claims;
- a late provider result cannot update a newer case revision;
- two simultaneous accept/confirm requests yield one winner and one typed stale/idempotent result;
- duplicate supplier/cart confirmation applies the quantity exactly once;
- transaction failure cannot leave a claim without its case revision or a cart line without its
  plan outcome;
- pool saturation returns within the request deadline and does not silently hang;
- PostgreSQL migration and local SQLite characterization tests agree on business outcomes;
- V2/cart compatibility suites remain green throughout migration.

## Exit gate

All async shopping-case routes use async application services; no synchronous SQLAlchemy call
runs on the event loop; external I/O occurs outside DB transactions; cancellation, stale revision,
idempotency and rollback browser/API tests pass; and V2 behavior remains unchanged.
