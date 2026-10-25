# ShopSquire

An evidence-governed commerce prototype: conversational buying, inventory and procurement proposals, with explicit boundaries between observations, evidence, authorization and execution.

**Start with the [engineering walkthrough](docs/portfolio/ENGINEERING_WALKTHROUGH.md), [current ASCII architecture](docs/architecture/CURRENT_ARCHITECTURE_2026-10-25.md), and [consolidated savepoint and pilot roadmap](docs/CONSOLIDATED_SAVEPOINT_AND_PILOT_ROADMAP_2026-10-25.md).** Implementation is substantially AI-assisted. This is an engineering portfolio and an unfinished product; release readiness has not been established.

The 25 October integration branch consolidates all 339 original dirty paths and adds native tenant-stream, startup-port, observability and research-continuity repairs. The integration baseline is `a9778cf8`; the repaired code/test freeze is `e56a501d`. The selected rehearsal uses mock electronics data, live consented search and reviewed draft-only supplier communications. The roadmap separates exact-source verification from the older evidence below; local integration is not a published-main or release-green claim.

Current code-freeze verification: **8,846 Python passes, 0 failures, 0 errors, 311 skips**; registered live research **2/2 pass**; focused browser **28 pass / 4 fail**. The separate broad integration baseline remains **97 pass / 58 fail / 33 skip**. Live discovery works, but the tested market answer is blocked and its exact shortfall remains unknown without an accepted SKU. These results do not qualify a release.

The earlier [draft repair PR](https://github.com/lkjalop/ShopSquire/pull/13) adds scoped market evidence, versioned supplier-draft review and grounded AUD/USD/EUR pricing previews. Its recorded C23 full Python profile reports **8,820 passes, 0 failures, 0 errors and 310 skips**. C23 broad browser reports **97 passes, 54 failures and 33 skips**; its included 28-case focused subset passes. Those historical results do not certify this later integration branch or published main. [Named-case deltas, screenshots, source maps and remaining gates](docs/EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md) retain failures and narrower scopes; required hosted/security gates and final-source endurance remain open.

## What it can demonstrate now

| Capability | Evidence and limits |
|---|---|
| Remember corrections across turns and reload | Named browser controls cover quantity, currency, per-unit/total budget and destination corrections. The current ledger distinguishes registered buyers, signed test buyers and operator-assisted scenarios. Indexed memory/cache erasure has separate-process controls; complete data-plane erasure and recovery remain open. |
| Prepare a stock-shortfall enquiry | A signed buyer's 40-unit request against 15 available produces a 25-unit shortfall and retained draft. The repair branch adds immutable review/edit versions and independent approval; only fictional sandbox sending is qualified. |
| Separate authority from model suggestions | Typed stages, deterministic policy and tenant/case controls; named refusal/degradation checks. This does not certify every provider or browser flow. |
| Explain evidence and commercial state | Decision Trace, procurement projections and audit records. Some navigation tests mock trace data; those passes do not prove live intelligence. |
| Compare inventory and market observations | Current-stock/event-validity controls have SQLite and native PostgreSQL checks. The repair branch adds question-relevant cited fixture/quote context; broad live coverage and citation usefulness remain open. |
| Bound untrusted attachments and workers | Named security, signing and sandbox-publisher checks. Broader browser coverage still fails, including actor/admission contracts. |

The [browser review](docs/BROWSER_CLICKTHROUGH_DELTA_AND_NEXT_STEPS_2026-10-22.md) retains complete case ledgers, source revisions, actor distinctions and a failure screenshot. Remembered quantity alone is not task completion. An unavailable-search refusal is not completed market analysis.

## Architecture at a glance

```text
 Buyer / operator browser                     Optional external providers
 React storefront + admin                    models / search / email / ERP
          | signed identity + tenant                    ^
          v                                             | scoped adapters
 FastAPI admission -> canonical case + turn state ------+ (policy gated)
          |                      |
          | model proposes       | SQL facts / inventory / accepted evidence
          v                      v
 Typed route -> deterministic validation -> retrieval -> fit/commercial stages
                                                        |
                         +------------------------------+
                         v
                 evidence adjudication
                         |
            +------------+-------------+
            v                          v
  buyer answer / trace          draft / action proposal
                                       |
                            approval + explicit effect gate
                                       |
                              outbox / signed worker
                                       |
                           sandbox / bounded adapter

 SQL: durable cases, evidence, inventory, audit   Redis: scoped cache / queues
 Hippograph: advisory relationship recall      Outcomes: trace / replay / eval
```

This maps components, not a release certification. Ordinary preference browsing without workload-qualification claims is a proposed product-contract clarification. See the [detailed map and file tour](docs/architecture/CURRENT_ARCHITECTURE_2026-10-25.md).

## Evidence snapshot

These historical profiles are separate, not an additive test total or one green release.

| Profile | Result | Source |
|---|---|---|
| Historical 23 October full Python process | 8,237 passed, 3 failed, 280 item skips; 4 additional collection skips | `a517f22e` |
| Completed broad Playwright matrix | 41 passed, 68 failed, 32 skipped; 63 specs / 141 cases | `0e177ea4` |
| Focused browser review | 12 passed, 5 failed; 17 cases | `abde83af` |
| Buyer-only memory replay | 7 passed; one test-setup overlay removes operator headers | `abde83af` |
| Frontend verification | 387 storefront + 63 admin unit passes, types/builds pass | Qualified installation at `0e177ea4` |

The [public evidence index](docs/REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md#evidence-and-reproduction) links committed ledgers. Raw `.artifacts/` directories are local run products, unavailable to GitHub readers. Hosted Actions results must be checked separately; no all-green badge is claimed.

## Reproduce a focused check

Use Python **3.11** and Node **22**. Profiles are generated from `poetry.lock`; there is no root `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/bootstrap-runtime-windows.txt
.\.venv\Scripts\python.exe -m pip install -r requirements/api-runtime-windows.txt -r requirements/test-runtime-windows.txt
.\.venv\Scripts\python.exe -m pytest tests/services/test_typed_recommendation_stage_coordinator.py tests/services/test_local_model_roles.py tests/services/test_research_policy.py -q
```

On Linux use `requirements/bootstrap-runtime.txt`, `requirements/api-runtime.txt` and `requirements/test-runtime.txt`. These scoped API/test profiles omit optional vision/model/evaluation dependencies. The broader development installation is `poetry install --no-root` from the committed lock.

```powershell
Set-Location frontend
npm ci
npm test
npx tsc --noEmit
npm run build
```

For an owned fictional browser runtime, follow the [reproduction instructions](docs/REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md#evidence-and-reproduction). Real commercial effects are disabled. Live model/search/mail/ERP activation has separate prerequisites.

## What to do next

1. Integrate remaining local cohorts and qualify one clean candidate with its required hosted checks and canonical runtime image.
2. Separate buyer explanations from privileged operator audit calls; resolve remaining browser actor, stock-fixture and semantic/provider failures.
3. Extend the demonstrated shortage/draft/quoted-intelligence slice to natural-language disclosure edits, full pack/landed pricing and real provider recovery.
4. Close all-plane privacy and legacy analytics isolation, inventory/provider contention and unresolved OS/security findings.
5. Reduce oversized ownership boundaries; qualify the same candidate for required recovery, rollback, latency and endurance.

The [current W00–W15 roadmap](docs/EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md#remaining-roadmap-and-exit-evidence) gives acceptance evidence and reasons. The obsolete storefront install manifests are [retired](docs/audits/2026-10-25-deprecated-storefront-retirement.md); its historical source remains for reference. Older strategy, architecture and demonstration documents remain historical context. No production readiness, real supplier/payment execution or business uplift is claimed.
