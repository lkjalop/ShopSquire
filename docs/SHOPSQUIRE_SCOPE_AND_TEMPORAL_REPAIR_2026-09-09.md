# Scope and temporal-query repair — 2026-09-09

## Recoverability

Before edits, saved HEAD.zip plus an overlay of modified and untracked files under `C:/AI/ShopSquire-checkpoints/scope-trace-20260909-145021`. This is a local recovery checkpoint, not a clean-checkout certificate or Git commit. Existing files were not reset/deleted. The worktree is still uncommitted.

## Changes and verification

- `routers/shopping_cases.py:2180`: load the server case catalog candidate set once; pass its selected taxonomy root into open-world research.
- `services/shopping_case_open_world_research.py:226`: accept product scope; carry it into both initial structured lookup and canonical-identity retry (315, 474). Missing live scope is empty, not an implicit electronics fallback.
- `recommendation_core/workload_grounding.py:249`: preserve product scope through canonical lookup and provider-kind fallback. Older direct callers retain compatibility defaults; those are not proof of universal revision-bound scope.
- `routers/chat.py:3706`: preflight compilation uses server decision product type; missing type fails scope resolution.
- `routers/decisions.py:530`: return successful temporal query results immediately, including empty results. Previously an empty result could activate other database/fallback queries that omit system-time filters.

The new temporal-empty regression failed before repair. Scope retry regression checks the same server product type reaches every provider attempt. Final selected suite: **57 passed, zero failures/errors/skips**, including scope, grounding, open-world discovery, audit compatibility, audit-chain persistence and decision-run tests. Receipt: `C:/AI/ShopSquire-checkpoints/pilot-review-20260909/temporal-scope-green.xml`.

## Bitemporal verdict: not end-to-end certified

The audit-trail endpoint exposes timestamped rows/events; this does not establish point-in-time historical reconstruction. `/decisions/query` uses range filters, not a two-coordinate as-of contract. Failure-path compatibility fallbacks remain to audit: repairing successful-empty handling does not certify schema-error handling. The old `tests/test_decision_bitemporal_query.py` directly overwrites tracked feature flags and tests timestamp presence only; it was inspected, not run. It needs isolated fixtures and meaningful retroactive-correction assertions.

Required next tests: a fact valid at T1, learned at T2, corrected at T3; query both knowledge coordinates with the same valid time; retain earlier evidence and policy/manifest revisions; reject cross-tenant access; verify every browser tab binds to the selected historical revision. Keep read-time illustrative hash chains distinct from persisted tamper-evidence verification.

## Still unfinished

No restart or new browser certification was performed. Typed CPU/GPU compatibility, exact source/manifest/case authority propagation beyond product type, terminal trace reconciliation, positive shelf delivery, independent budget/stock sourcing journeys, clean-checkout/PostgreSQL/hosted certification and independent source reviews remain open. No supplier, cart or source-approval actions occurred. No claim that the whole platform or dirty tree is green is warranted.
