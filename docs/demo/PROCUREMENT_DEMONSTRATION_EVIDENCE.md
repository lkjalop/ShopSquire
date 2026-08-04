# Procurement demonstration evidence index

## Certified integration base

- Pull request: `#8` (`agent/conversation-escalation-foundation-20260804`)
- Certified head: `e526239b2d81eeb0d0d482457916e52c41e09c33`
- Integration merge: `d3d7af7e45986c6da1870c46624e0766d0d61450`
- Hosted browser/worker run: <https://github.com/lkjalop/ShopSquire/actions/runs/30873927351>
- Result: browser, worker, PostgreSQL migration/rollback/re-upgrade and transaction-abort
  gates passed.

The hosted run retains:

- `procurement-browser-evidence` (artifact `8878992268`): screenshots, videos and traces for
  buyer flow, context retention, five-section Decision Trace, temporal contact, procurement
  journey, fulfillment and temporary-chat isolation; PostgreSQL migration logs; SIEM handoff;
  transaction-abort gate.
- `procurement-worker-evidence` (artifact `8878931445`): worker logs, JUnit result for 12
  connector/outbound tests, migration evidence and transaction-abort gate.

The transaction-abort gate found zero `SQLSTATE 25P02`/aborted-transaction signatures. The
hosted database was at migration `20260855_case_escalation`.

## Current topic branch proof

- Implementation commit: `3695ebdd`.
- Focused projection/semantic tests: 12 passed.
- Combined targeted backend suite: 84 passed.
- Expanded conversation/cache/evidence suite: 41 passed.
- Procurement trace component suite: 18 passed.
- SQLite full migration chain, rollback and re-upgrade: passed at
  `20260856_escalation_projection`.
- New 20-turn rendered browser regression: passed locally; Playwright trace, screenshot and
  video retained under `frontend/test-results/` and intentionally not committed.

## Certified escalation and semantic-proposal slice

- Pull request: `#9` (`agent/escalation-projection-semantic-evidence-20260804`)
- Certified head: `81eae09e5d30be2eb4de3b4ea887ef3fd3a26841`
- Integration merge: `06910779f36b3640ff0e786b4372f6ccbd5d8c00`
- Hosted browser/worker run: <https://github.com/lkjalop/ShopSquire/actions/runs/30875656813>
- Browser artifact `8879579241`; worker artifact `8879526887`.
- PostgreSQL migration, rollback and re-upgrade reached
  `20260856_escalation_projection`.
- Runtime transaction-abort gate passed with zero matching signatures.
- The hosted storefront battery retained videos and traces for the 20-turn conversation,
  temporary-chat isolation and procurement journey.

## Recording sequence

1. Ask for a named SKU and quantity, then amend destination, deadline and quantity without
   losing the canonical case anchor.
2. Show confirmed local/network ATP separately from supplier-unconfirmed shortfall.
3. Open Commercial Journey: allocation pressure, consolidated sourcing and the human-gated
   RFQ draft.
4. Open the canonical escalation projection: source adapter, queue SLA and operator state.
5. Amend the case and show the old calculation/cache generation superseded rather than
   silently reused.

Use the hosted procurement journey video as reproducible evidence. Record the polished
narrated demonstration only after the current topic PR's PostgreSQL, worker and browser checks
are green.
