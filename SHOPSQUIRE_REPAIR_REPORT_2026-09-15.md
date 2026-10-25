# ShopSquire: five-priority repair report

Date: 15 September 2026. This records implementation and verification after the earlier audit; it does not replace the original findings.

## Outcome

The five priorities now have implemented repairs and executable contracts. Seven live Playwright contracts passed without retries. The authenticated admin click-through covered 25 views with no page errors or failed HTTP responses. Production readiness remains conditional on real catalog evidence, approved evaluation measurements, restricted PostgreSQL credentials, and hosted CI enforcement.

The positive browser journey used live Steam requirements and **a labelled synthetic configuration in an isolated database**. It proves the request-to-screen wiring, not the compatibility or availability of a real retail laptop. The original application database and services were not upgraded or replaced.

## 1. Truthful evaluation and tenant isolation

**Changed:** One evaluation contract replaces heuristic quality scores in both evaluation adapters. Missing dependencies, incomplete reference samples, evaluator errors and invalid scores have explicit statuses and null metrics. Persistence failures propagate. Legacy scores remain `legacy_unverified`; migration does not promote them to measured evidence or create an approved baseline.

The release gate requires a tenant-owned approved baseline, matching dataset/model/prompt/configuration/evaluator identities, fresh measured rows and sufficient samples. Empty windows fail. The actual isolated database produced `{"ok": false, "reason": "no_data"}` and exit code 1.

Analytics and citation reads now filter by tenant. Citation verification cannot update another tenant's claim. Session creation binds the PostgreSQL tenant setting for every transaction, including transactions after a commit. The resilience worker preserves request context when moving work to a thread. The new migration removes the permissive empty-tenant policies on the three guarded tables.

**Green contract:** A and B use the same pooled PostgreSQL connection yet see only their own rows; an unbound restricted-role session sees no rows. Foreign/unowned analytics records do not contribute. Missing or unmeasured evaluations cannot make the release gate pass.

**Main files:** [evaluation contract](src/app/services/evaluation_contract.py), [evaluation gate](src/app/services/ragas_eval.py), [migration](alembic/versions/20260875_evaluation_tenant_integrity.py), [tenant session](src/app/platform/tenant_session.py), [analytics](src/app/routers/analytics.py), [citation memory](src/app/services/citation_memory.py).

## 2. Atomic recommendation stage outputs

**Changed:** The seven post-retrieval stages work on isolated response output. Successful work publishes at the stage boundary; failed work cannot leave partially changed products, messages or nested response data. Legacy stage operations restore their response snapshot on failure. Dependency declarations are validated, and failed prerequisites block dependent stages. Failed stages do not advertise successful output artifacts.

**Green contract:** Mutation followed by an exception preserves the prior output. Isolated mutations are invisible before completion. Downstream operations do not execute after a failed prerequisite.

**Boundary:** This protects response-owned state. It is not a distributed transaction, and cannot undo external side effects or arbitrary writes through the shared request envelope. Keep side effects behind their own durable workflow/outbox boundary.

**Main files:** [stage runner](src/app/services/recommendation_core/stage_runner.py), [coordinator](src/app/services/recommendation_core/typed_stage_coordinator.py), [stage plan](src/app/services/recommendation_core/post_retrieval_stage_plan.py), [core](src/app/services/recommendation_core/core.py).

## 3. Evidence to a visible qualified product

**Changed:** The Steam parser retains explicit `SSD required` source spans. Hardware alternatives retain their individual literal spans; no newer-device equivalence is inferred. Windows architecture is retained in canonical values. Completeness follows current manifest obligations: a rejected optional extra remains rejected without invalidating six independently accepted required attributes. Missing required attributes still block qualification.

Live fetch and cache receipts now distinguish actual network execution from reuse. The normal resolved-provider chat path calls the exact-configuration evidence reducer before committing the terminal case. It uses the tenant's bounded candidate set and budget. Existing terminal authority checks remain in place. The frontend installs these terminal shelves and no longer clears them through the legacy upload handler. Budget narration uses qualified shelf configurations instead of cheaper generic SKU matches.

**Green contract:** Live provider execution → literal claims → compiler → current scope → configuration evidence → qualified shelf → visible browser item. The same reducer keeps incomplete or incompatible configurations conditional/unqualified and enforces budget limits. Held-source and unrelated-purchase browser contracts still pass.

**Proof boundary:** The synthetic configuration is `REPAIR-SYNTHETIC-NOT-FOR-SALE`. Ordinary inventory lacked some CPU/GPU/OS/storage evidence and remained conditional. Source ownership without a separate ownership receipt remains `not_assessed`; the implementation does not invent an ownership attestation from a successful fetch.

**Main files:** [Steam connector](src/app/services/connectors/steam_requirements.py), [workload grounding](src/app/services/recommendation_core/workload_grounding.py), [research outcome](src/app/services/research_outcome.py), [chat wiring](src/app/routers/chat.py), [storefront](frontend/src/App.tsx).

## 4. Trace and admin contracts

**Changed:** Procurement trace loading has explicit idle/loading/ready/not-applicable/error states, cancellation, deadlines and revision-bound installation. Old responses cannot replace a newer trace. Browser assertions reject both ellipsis variants of loading placeholders and require a settled semantic state.

Trusted claims accepts the unfiltered operator request and returns a typed envelope. BI security queries use a separately labelled seven-day window. Grafana reports unavailable when unconfigured and avoids broken iframes; proxy routes require an operator role. A saved operator API key now takes precedence over the build-time default.

**Green contract:** Hook tests cover errors and late A-after-B responses. The authenticated 25-view browser pass had zero page errors and zero HTTP failures, including the former BI/trusted-claims failures.

**Main files:** [trace hook](frontend/src/hooks/useProcurementTrace.ts), [trace component](frontend/src/components/DecisionTrace.tsx), [admin client](src/frontend/admin-react/src/api/client.ts), [BI](src/frontend/admin-react/src/components/MerchantBIPro.tsx), [trusted claims](src/app/routers/merchant_intelligence.py), [Grafana](src/app/routers/admin_grafana_proxy.py).

## 5. PostgreSQL, recovery and CI

**Changed:** Category budget approval uses a tenant/category advisory lock held across the workflow's internal commits. Invalid and unknown spend cannot select an automatic tier. When category-cap enforcement is enabled, unsupported SQLite execution fails closed. Committed spend queries no longer truncate at 100 cases or silently substitute zero for query failure.

Audit jobs restore tenant context, validate durable payload identity, and enter retry/dead-letter handling on validation or persistence failure. The decision writer recognises an already persisted same-tenant decision; insertion/commit failure no longer reports success.

**Green contract:** Concurrent 600-cent commitments against a 1,000-cent cap admit one. Crash injection occurs after the real PostgreSQL decision writer commits; stale-job recovery and replay finish with one decision row. A foreign tenant cannot claim that decision. The new migration itself runs on PostgreSQL and preserves legacy status. This is not a full fresh-install PostgreSQL migration-chain certification.

CI now enforces the async database scanner and includes the PostgreSQL release contracts. Flagged database blocks moved off the event loop; cancellation during session startup closes the eventual session. The scanner also stops misclassifying nested synchronous helpers. Locked-dependency audit failures are no longer swallowed in the changed audit steps. Node 18 workflows move to Node 22 to match installed Vite engine requirements. Python 3.10 has an explicit `StrEnum` compatibility implementation.

[Evaluation release workflow](.github/workflows/evaluation-release-gate.yml) is callable or manually runnable and fails if its evaluation database is missing or the measured-quality gate fails. It needs `EVALUATION_DATABASE_URL` and the tenant input. It does not create or approve measurements.

## Verification receipts

Evidence directory: `C:/AI/ShopSquire-checkpoints/audit-2026-09-15`.

| Verification | Result | Receipt |
|---|---|---|
| Broad targeted backend regression | 293 passed | `repair-regressions.log`, XML |
| PostgreSQL contracts plus provider/delivery regressions | 35 passed | `repair-postgres-final.log` |
| Terminal, cancellation and migration follow-up | 49 passed | `repair-final-backend.log` |
| Final tenant/admin/narration contracts | 28 passed | `repair-last-contracts.log` |
| Session-entry cancellation | 2 passed | `repair-session-cancellation.log` |
| Decision writer, tenant and legacy-schema regressions | 11 passed | `repair-decision-writer.log` |
| Storefront tests and build | 391 passed; build passed | `repair-frontend-final.log` |
| Admin tests and build | 50 passed; build passed | `repair-admin-final.log` |
| Live Playwright contracts | 7 passed, 0 skipped, 0 retries | `repair-browser-final.json`, traces/videos |
| Latest positive delivery recheck | 1 passed | `repair-browser-latest.json` |
| Authenticated admin navigation | 25 views, no errors/failing responses | `repair-runtime/admin-clickthrough-normal-login.json` |
| Real evaluation release check | Correctly blocked: no data, exit 1 | `repair-evaluation-gate.log` |

These runs overlap; do not add their counts to claim unique test coverage. This was targeted verification, not every test in the repository. Local Python execution used 3.11; the compatibility fallback was tested, but the hosted 3.10 matrix was not run. Changed workflow YAML parsed and `git diff --check` passed. Hosted CI, vulnerability scans and branch-protection configuration were not executed or verified remotely.

`repair-source-index.csv` lists source symbols and line numbers. `repair-working-tree-files.csv` inventories current changed/untracked files with physical line counts; it includes pre-existing user work and is not an attribution list. Existing changes were preserved. No commit or deployment was made.

## Next hierarchy: keep autonomy constrained

1. **Real configuration evidence:** Choose a small saleable catalog cohort. Ingest exact MPN/configuration, dated CPU/GPU/OS/storage observations, price and stock. Add reviewed equivalence rules only where evidence supports them. Repeat the positive browser contract with this real cohort; remove synthetic data from any deployment dataset.
2. **Approved evaluation dataset:** Review reference answers and coverage, freeze dataset/model/prompt/configuration identities, run the actual evaluator, approve a baseline and pass the measured release workflow. Include unsupported workloads, held sources, hostile source text, tenant boundaries and missing evidence. Test the release workflow's failure as well as success.
3. **Deployment database proof:** Exercise the entire migration chain and restore drill against a production-shaped PostgreSQL instance using a non-owner application role. PostgreSQL owners/superusers bypass ordinary RLS. Repeat concurrency through the actual HTTP approval endpoint and test process death around every external-effect boundary.
4. **Hosted enforcement:** Run the changed workflows, resolve dependency findings, and make the required checks non-bypassable in repository settings. Add the reusable evaluation job to the actual autonomy/deployment workflow. Local green is not proof of branch protection.
5. **Only then expand autonomy:** Start with bounded read-only or draft work. Keep approval, provenance, tenant isolation, idempotency and rollback/recovery evidence mandatory as external actions are introduced.

The isolated review services use API `18082`, storefront `25174`, admin `23002`, PostgreSQL `55433` and Redis `6383`. The labelled fixture exists only in the cloned SQLite review database. Existing user services on their original ports were preserved.
