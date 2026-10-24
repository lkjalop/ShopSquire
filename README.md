# ShopSquire

An evidence-governed commerce prototype: conversational buying, inventory and procurement proposals, with explicit boundaries between observations, evidence, authorization and execution.

**Start with the [engineering walkthrough](docs/portfolio/ENGINEERING_WALKTHROUGH.md), [current ASCII architecture](docs/architecture/CURRENT_ARCHITECTURE_2026-10-25.md), and [25 October execution delta and roadmap](docs/EXECUTION_DELTA_AND_MVP_ROADMAP_2026-10-25.md).** Implementation is substantially AI-assisted. This is an engineering portfolio and an unfinished product; release readiness has not been established.

The [draft repair PR](https://github.com/lkjalop/ShopSquire/pull/13) adds scoped market evidence, versioned supplier-draft review and grounded pricing previews. The latest larger local C15 Python run passed 8,701 tests with zero failures/errors and 309 skips; its 23 focused browser cases passed. Those local sources include additional WIP and do not certify the PR or published main. The later C16 broad browser profile reports 89 passes, 59 failures and 33 skips. Hosted security and endurance gates remain open.

## What it can demonstrate now

| Capability | Evidence and limits |
|---|---|
| Remember corrections across turns and reload | Quantity, currency, per-unit/total budget and destination corrections; seven buyer-only browser checks pass. Indexed memory/cache erasure has separate-process controls on the repair branch; complete data-plane erasure and recovery remain open. |
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
npm run build
```

For an owned fictional browser runtime, follow the [reproduction instructions](docs/REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md#evidence-and-reproduction). Real commercial effects are disabled. Live model/search/mail/ERP activation has separate prerequisites.

## What to do next

1. Integrate remaining local work in dependency-complete commits; reproduce one clean installation.
2. Repair browser actor/fixture contracts and candidate/qualified-result presentation while preserving evidence gates.
3. Complete case-bound evidence intake, bulk shortage presentation and cited market intelligence.
4. Close distributed privacy, inventory contention, approval identity, uncertain-delivery recovery and unresolved advisories.
5. Reduce oversized functions; freeze one source for required Python/browser/security, restore/rollback and endurance checks.

The [current roadmap](docs/REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md#remaining-roadmap) gives acceptance evidence and reasons. Older strategy, architecture and demonstration documents remain historical context. No production readiness, real supplier/payment execution or business uplift is claimed.
