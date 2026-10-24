# Continuity, browser images and effect authorization — 24 September 2026

This pass continues [the prior evidence report](ROADMAP_CONTINUATION_EVIDENCE_2026-09-24.md). Research continuity now passes the previously failing live sequence. Browser image handling has new full-analysis evidence. Refund approval and retries now share an expiring exact-effect permit. Real tenant market relevance and representative quality benchmarks remain unproven because the required data has not been supplied.

## Research continuity

The deterministic subject-switch boundary required a multiword title for ordinary “laptop for …” requests. Consequently, a known single-word software name such as Blender did not reliably replace the university-shopping purpose. The governed publisher manifest now supplies a bounded identity alternative after replacement grammar is recognized. Negated requests and generic university requests do not trigger this alternative. Research consent and product qualification are still separate checks.

An existing additive-workload regression also exposed terminal narration overwriting the retained-budget explanation. The terminal projection now preserves deterministic additive-workload narration while retaining the qualification hold.

The live browser test passed this sequence:

1. University laptop under AUD 1,500 creates the initial case.
2. Blender rendering creates a different case, with zero accepted research claims and no inherited consent.
3. An explicit request for official Blender requirements researches that same new case and produces an accepted claim. Commerce authority remains none.

[Browser recordings](../.artifacts/next-browser), [run log](../.artifacts/next-browser.log), and [26 passing continuity/qualification tests](../.artifacts/continuity-next-tests.xml). The initial browser run also contains a failed image subtest, discussed below; the entire original two-test run must not be described as passing.

## Mixed-model and browser-image evidence

The separate gateway soak completed **45/45 calls**, comprising 15 text → image → text cycles, approximately **348.7 seconds of recorded call time**. Every resident-model checkpoint contained one model. Exact digests, image hash and schedule receipts are preserved in [the artifact](../.artifacts/next-mixed-soak.json). This extends the earlier nine-call proof, but remains a six-minute bounded soak, not hours-long or production-load certification.

Browser testing exposed a separate raw Ollama path in `ManagedCVProvider`, with no shared model admission and an outer ten-second allowance that was shorter than observed cold vision calls. This path now uses the shared gateway, exact reviewed digest, bounded output and configured context. The local demo profile supplies a 60-second model allowance and a 65-second enclosing provider allowance. Automatic fallback to another unreviewed vision model was removed. Gateway failures propagate as degradation with their stable failure code.

The final **three browser image-upload → shopping-text cycles passed** in 1.8 minutes. Each image assertion waits for the full triage response, explicitly excluding `fast=1` previews. All three full responses report Ollama analysis, `analysis_pending=false`, `analysis_degraded=false`, clean artifacts and `authority=read_only`. Subsequent shopping turns satisfy terminal identity/budget/commerce invariants. The same existing MacBook image was reused; caches remain enabled. This is not three independent images or a model-accuracy dataset.

[Full-analysis recordings](../.artifacts/next-browser-images-full), [passing log](../.artifacts/next-browser-images-full.log), [three response summaries](../.artifacts/next-browser-images-summary.json). The screenshot shows the initial attachment turn held while its fast analysis was pending; later clean inspection does not automatically retroactively qualify a product. Complete image-driven product qualification is not claimed.

Earlier attempts are retained: an informational follow-up had no shopping-case read model, so applying the case-specific oracle to it failed; the test now follows the image with a shopping request. Another attempt initially accepted fast preview responses on cycles two and three. The final harness excludes those responses. Those earlier attempts do not count as full-analysis success.

## Refund effect authorization

Migration **20260879_refund_effect_permit** adds an exact-effect digest, authorization deadline and revocation timestamp. New approvals default to a bounded 24-hour authorization. Existing unbound queued rows fail closed; they are not silently backfilled with approval. Expired or revoked permits are not renewed by idempotent retries.

The worker verifies the effect digest and claims only the unchanged tenant/order/approval/amount/currency/intent/idempotency-key tuple with a live permit. Revocation succeeds only before dispatch is claimed; a false return does not imply that an already-started provider effect was cancelled. A stale worker cannot overwrite newer settlement because completion writes are fenced by the claim token. Missing or mismatched provider receipts cannot settle an execution.

Refund approval previously called Stripe directly and marked the execution settled regardless of provider status. It now uses the same permit-checked execution path as retries. The approval ledger event and durable execution are committed together: if permit persistence fails, the approval and reservation roll back and no provider call occurs. Pending provider refunds return `refund_submitted`; successful ones return `refund_executed`, while webhook ledger reconciliation remains separate.

The PostgreSQL race test uncovered another runtime issue: repeated `CREATE INDEX IF NOT EXISTS` calls inside `ensure_table` held a lock that blocked a competing update. Existing tables/indexes are now inspected without issuing redundant DDL. Missing schema still follows the existing compatibility bootstrap path; production migration remains required.

Tests cover expired/revoked/modified/unbound effects, cross-tenant revocation denial, unchanged-key retry, payload mutation between read and claim, duplicate settlement, stale workers, missing receipts, pending provider responses and approval-persistence failure. No live payment or supplier message was sent. This strengthens refunds plus the previously covered outbound/cart boundaries; it does not certify every effect sink. Historical refund backfill, an operator revocation workflow, authorization renewal/reconciliation for held financial reservations, and provider ambiguity after dispatch remain separate work.

## Current-catalogue benchmark and market data

`scripts/benchmark_current_catalog_contracts.py` freezes current product facts and independently derives brand/budget filter expectations from them. It ran **52 cases × 3 repetitions = 156 observations**, including 48 cases with expected matches and four expected-empty cases. All passed, with a **3.735 ms median** for this local SQLite retrieval path.

[Results](../.artifacts/next-current-catalog.json) and [hashed catalogue snapshot](../.artifacts/next-current-catalog.catalog.json) contain the actual SKUs and expectations. The snapshot has 175 products, of which **116 lack structured brand and category fields**. The benchmark covers populated brand fields and price filtering; it does not establish semantic relevance, independent buyer utility, stock freshness, tenant isolation or graph/vector infrastructure improvement. No model or retrieval promotion follows from it. The prior larger model comparison still establishes no quality winner.

The user was asked for an actual tenant/SKU or supplier-to-destination lane and the location of current sales/supplier data. No answer arrived during this pass. The prior read-only audit still found no verified market mappings or purchase history. No invented tenant mapping, demo finding or public weather observation was represented as a real operational market decision. Representative quality/forecast benchmarking still requires current independently reviewed labels and attributable outcome history.

## Verification and operations

| Group | Passing tests | Evidence |
|---|---:|---|
| Continuity, literal identity and terminal qualification | 26 | [JUnit](../.artifacts/continuity-next-tests.xml) |
| Vision budgets, admission, triage and runtime authority | 31 | [JUnit](../.artifacts/next-vision-tests.xml) |
| Refunds, PostgreSQL effect races, returns and reconciliation | 32 | [JUnit](../.artifacts/next-effects-final.xml) |
| Final continuity, gateway binding and approval rollback additions | 21 | [JUnit](../.artifacts/next-final-delta.xml) |
| Final API pending/succeeded provider distinction | 8 | [JUnit](../.artifacts/next-payment-api-final.xml) |

Groups overlap and are not a unique total. The earlier broader PostgreSQL group passed 28 tests, including ten real PostgreSQL integrity/effect tests: [JUnit](../.artifacts/next-postgres-tests.xml). The latest effect group reran the five PostgreSQL effect tests after the worker and approval changes. Undefined-name checks, function-size ratchet and whitespace checks passed. These are targeted checks, not the whole repository suite.

The temporary backend, frontend and dedicated Ollama processes were stopped; the owned Redis and PostgreSQL containers were removed. Existing user services were left untouched. Proof databases and recordings remain for review. No commit, deployment or external financial/supplier effect was performed. Existing unrelated workspace changes were preserved.

## Codex usage in VS Code Insiders

The installed extension is `openai.chatgpt-26.5917.62051-win32-x64`. Its shipped composer implements `/status` with the description “Show chat ID, context usage, and rate limits.” Type `/status` in the Codex chat composer and select **Status**. This is based on the locally installed extension, rather than assuming the old “Work locally” footer remains.

Account allowance is separate from the current conversation's context capacity. The official [usage guidance](https://learn.chatgpt.com/docs/pricing#where-can-i-see-my-current-usage-limits) links to the [Codex usage dashboard](https://chatgpt.com/codex/settings/usage) and documents `/status` for CLI sessions. The dashboard is the fallback when the extension cannot fetch limits; use the same signed-in account. The local extension also contains a context-window display preference that defaults off, but no setting was changed during this task.
