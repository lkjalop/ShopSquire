# ShopSquire platform proof verification matrix

Status date: 2026-07-30

Publication branch: `agent/platform-reliability-publication-20260730`

Draft PR: <https://github.com/lkjalop/ShopSquire/pull/7>

This document separates verified engineering evidence from incomplete
production or business claims. A green synthetic, contract, or browser test
does not establish business lift.

## Verified claims

| Claim | Test or workflow evidence | Artifact / run | Verified commit |
|---|---|---|---|
| The production-shaped worker can connect to Redis, accept a job, retry bounded failures, exercise connector delivery, and recover stalled work. | `worker` job in `Procurement browser and worker isolation` | [Run 30531462072](https://github.com/lkjalop/ShopSquire/actions/runs/30531462072), `procurement-worker-evidence` (retained until 2026-08-13) | `3d924374` |
| The PostgreSQL migration chain can upgrade, report current, downgrade one revision, and re-upgrade with pgvector available. | `Create isolated database and validate migrations` | [Browser job 90834540402](https://github.com/lkjalop/ShopSquire/actions/runs/30531462072/job/90834540402) | `3d924374` |
| Storefront and admin React component contracts remain green. | 189 storefront and 39 admin component tests | `procurement-browser-evidence` in run 30531462072 | `3d924374` |
| The hosted storefront procurement journey completes all nine Playwright scenarios. | `Storefront Playwright battery` | Browser job 90834540402 | `3d924374` |
| A malicious reply from a trusted supplier is visible to the operator but cannot mutate quote, economics, PO, or payment state. | `test_procurement_malicious_reply_playwright.py` | Browser job 90834540402; test passed in 3.80 seconds | `3d924374` |
| Worker and browser logs contain no PostgreSQL aborted-transaction signature (`25P02`). | `Reject worker transaction-abort signatures`; `Reject transaction-abort signatures` | Run 30531462072 | `3d924374` |
| V2 recommendation cutover contracts pass without the archived `recommend.py` production router. | `V2 Gates (mandatory)` | [Run 30531462066](https://github.com/lkjalop/ShopSquire/actions/runs/30531462066) | `3d924374` |
| Service tests complete on isolated hosted shards. | Eight `Service tests sharded` jobs | [Run 30531462067](https://github.com/lkjalop/ShopSquire/actions/runs/30531462067) | `3d924374` |
| Changed Python files satisfy the scoped Ruff ratchet. | `Ruff changed-file ratchet` | [Run 30531462070](https://github.com/lkjalop/ShopSquire/actions/runs/30531462070) | `3d924374` |
| Security, dependency, SBOM, filesystem and PAN checks complete. | Security scan workflow jobs | [Run 30531462097](https://github.com/lkjalop/ShopSquire/actions/runs/30531462097) | `3d924374` |

## Pending proof

| Claim | Current evidence | Missing gate |
|---|---|---|
| Every Decision Trace panel projects the final authoritative V2 lane. | All panels load, but the hosted policy trace displayed an early `SEARCH` observation instead of finalized `POLICY_QUESTION`. | Publish and rerun the final-intent precedence regression. |
| The complete heterogeneous repository test tree is green under one command. | Isolated service shards and dedicated browser/worker lanes are green. | Replace or repair the legacy unisolated `CI Tests` workflow; it lacks async plugins and mixes incompatible database/browser fixtures. |
| The older generic `CI` workflow collects every Playwright security test. | Dedicated Playwright workflows collect and pass their owned tests. | Repair `tests/pw/test_sec_files_e2e.py` empty-param ID handling, then re-evaluate the generic workflow. |
| Runtime schema mutation has been removed from production code. | Experiments validate migration-owned tables without creating them. | Runtime-DDL audit found 578 matching lines in 111 files. Migrate and remove production calls subsystem by subsystem. |
| ShopSquire improves forecast accuracy, stockouts, margin, GMROI, or operator workload. | Synthetic replay, invariants, model discrimination, and UI contracts exist. | Tenant-authorized shadow data, sealed baselines, outcome windows, and measured results. |
| Public market evidence proves a product-specific supply exposure. | Governed source, provenance, licensing, revision and freshness contracts exist. | Authoritative product/component/supplier/facility/lane mappings. |
| Conversation deletion is operationally complete or legally compliant. | Tenant/session-epoch persistence and a privacy design exist. | Multi-store deletion jobs, receipts, retries, legal holds, backup expiry, provider handling, browser proof, and legal review. |
| Gmail/M365 provider activation is production certified. | Provider-independent inbox, evidence and governance contracts exist. | Real OAuth/JWT and transport round trips. Activation remains intentionally snoozed. |

## Runtime-DDL audit

The repository still contains runtime schema creation or alteration patterns in
production-reachable modules. The scan is intentionally broad and includes
compatibility helpers, so every match is not necessarily invoked in production.
It nevertheless disproves a repository-wide “migration-only schema” claim.

Priority removal order:

1. Startup and identity/security authorities:
   `supplier_domain_guard`, security event ingest, KYV, audit and email-security
   startup helpers.
2. Consequential execution:
   cart mutation, payment ledger/webhook, refund, inventory reservation and
   fulfillment retry paths.
3. Intelligence and attribution:
   market signals/findings/outcomes, human feedback, citation memory and
   recommendation learning.
4. Observability and operator tooling:
   trace, playbook, incident, SIEM and calibration tables.
5. Test/local compatibility:
   retain only behind an explicit non-production profile until fixtures use
   migrations.

For each subsystem, acceptance requires:

- an Alembic migration owns the complete schema and indexes;
- startup validates required tables/columns without mutating them;
- a missing migration fails clearly rather than silently returning empty data;
- PostgreSQL upgrade/downgrade/re-upgrade is exercised;
- SQLite-only test compatibility cannot activate under a production profile.

## Publication risk

PR #7 is a preservation branch, not a reviewable merge unit. Relative to its
old base it contains 1,195 commits, 1,736 files, 353,808 additions and 14,214
deletions. It must remain draft. Before merge, establish a current trusted base
and publish reviewable topic PRs or a documented repository cutover. Do not
squash or merge this history blindly.

The local worktree also contains user-owned configuration, documents, generated
artifacts and scratch files not included in the proof commits. They must remain
separate unless their ownership and intended publication are explicitly
reviewed.
