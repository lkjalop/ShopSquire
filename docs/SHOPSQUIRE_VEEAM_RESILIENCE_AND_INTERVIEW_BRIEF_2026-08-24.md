# ShopSquire, Veeam resilience and Agent Commander brief

Date: 24 August 2026

## Executive position

ShopSquire is not a backup product and should not be presented as a replacement for
Veeam, Veeam Kasten, Recovery Orchestrator or Securiti Agent Commander. It is a
case-bound decision and evidence system for commerce: it turns buyer language into a
revisioned procurement case, adjudicates research and operational observations, proposes
allocations, and withholds external/commercial authority until explicit gates pass.

The clean segue is:

> ShopSquire demonstrates the application-side half of recoverable agentic operations:
> bounded authority, identity, evidence, revision history, replay and compensating
> workflows. Veeam and Kasten supply the protected recovery points and recovery
> orchestration; Agent Commander supplies estate-wide discovery, identity/data/agent
> context and AI-risk controls. Together they connect *what an agent intended and changed*
> with *what data can be safely restored and how recovery is verified*.

This is an architecture proposal, not a claim that ShopSquire is currently integrated
with those products.

## What the products own

| System | Primary responsibility | What it must not be confused with |
| --- | --- | --- |
| ShopSquire | Buyer intent, evidence adjudication, decision trace, procurement case revisions, advisory allocation and human approval gates | Backup media, universal AI governance, or infrastructure DR |
| Veeam Kasten for Kubernetes | Kubernetes-native application backup/restore, DR and mobility | Reversing non-Kubernetes external side effects |
| Veeam Backup & Replication | Protection repositories and recovery operations, including management of Kasten exports/snapshots through the Kasten integration | Understanding the business meaning of a ShopSquire decision |
| Veeam Recovery Orchestrator | Tested recovery plans, dependency sequencing, isolated DataLab verification and reports for supported protected workloads | Kubernetes application-aware business logic or agent intent adjudication |
| Veeam DataAI Agent Commander / Securiti Data Command Center | Agent/model inventory, data/identity/permission graph, runtime controls, action timelines and targeted recovery coordination | A guarantee that every external action is technically reversible |

Official product anchors:

- [Veeam Kasten overview](https://helpcenter.veeam.com/docs/vcsp/refguide/kasten.html)
- [Veeam Backup & Replication Kasten operations](https://helpcenter.veeam.com/docs/vbr/userguide/kubernetes.html)
- [Recovery Orchestrator isolated testing](https://helpcenter.veeam.com/docs/vro/userguide/testing_recovery_plans.html)
- [Agent Commander product overview](https://www.veeam.com/solutions/agent-commander.html)
- [Agent Commander architecture description](https://www.veeam.com/blog/agent-commander-ai-risk-solution.html)

As of this review, the public Agent Commander page still asks users to request early
access and no supported public integration API was found. Do not promise an implemented
connector until Veeam/Securiti supplies a supported API, event schema and test tenant.

## Codebase findings that matter to resilience

ShopSquire already has useful application-layer primitives:

- `ProcurementCaseState` provides immutable, revisioned buyer intent.
- `AgentRunEvent` and replay contracts bind model/tool activity to an execution history.
- `EvidenceSynthesisLedger` binds consent, sources, hashes, claims, contradictions,
  freshness and case revision without granting commerce authority.
- Operational connector contracts separate enrollment from observations and keep
  credentials as secret references.
- Procurement disturbance projection rejects stale case revisions, prevents future
  evidence from leaking into replay, and recomputes only affected stages.
- Allocation conflict arbitration preserves objective disagreements and remains advisory.
- The Helm chart supplies restricted containers, probes, migrations, an API deployment,
  a sync worker and external Postgres/Redis configuration.

Important recovery gaps:

1. The Helm `dbBackup` CronJob is not a production recovery proof. With no S3 bucket it
   writes only to pod-local `/tmp`, which disappears. When S3 is configured, the declared
   `postgres:16` image is not evidence that an AWS CLI is present. It needs a supported,
   tested backup image/workflow or should be disabled in favour of the managed database's
   native PITR plus governed export.
2. Production values use external Postgres and Redis. A Kasten namespace policy alone
   would not protect an external database. Postgres needs native snapshot/WAL/PITR or a
   supported Veeam protection path; Redis must be explicitly classified as durable or
   reconstructable.
3. No Kasten policy, Location Profile, immutable export target, restore test or RPO/RTO
   result is currently committed.
4. No supported Agent Commander connector is implemented.
5. A database restore is insufficient by itself: evidence artifacts, audit/WORM material,
   secrets, connector enrollments, object storage and model manifests need declared owners
   and recovery order.

## Proposed ShopSquire recovery design

### Protection groups

1. **Kubernetes application:** Deployments, Services, ConfigMaps, permitted Secrets,
   service accounts, ingress and persistent volumes. Protect with Kasten policy and export
   to a separate, immutable failure domain.
2. **Postgres system of record:** Use application-consistent managed snapshots plus WAL/PITR
   appropriate to the required RPO. Capture the Alembic revision and application image
   digest in every recovery point receipt.
3. **Redis:** Prefer reconstruction from Postgres/outbox for derived queues and caches. If a
   queue is business-durable, protect it separately and test duplicate/idempotent replay.
4. **Object evidence:** Version and protect certificates, provider receipts and audit
   artifacts. A database pointer without its immutable object is not recoverable evidence.
5. **External side effects:** Email, RFQ, payment, reservation and carrier calls are not
   fixed by restoring a database. Reconcile each provider by idempotency key and use
   system-specific compensation or human review.

### Recovery sequence

1. Declare the incident cutoff and quarantine external/commercial actions.
2. Preserve logs, AgentRun events, provider receipts and confirmed/possible impact sets.
3. Select a trusted recovery point at or before the cutoff; record RPO exposure.
4. Restore into an isolated namespace or recovery environment.
5. Restore Postgres consistently, then verify schema revision `20260874` (or the release's
   pinned revision), constraints and tenant isolation.
6. Restore/rebuild Redis according to its declared durability class.
7. Start workers disabled; validate API health, evidence hashes, case revisions and outbox
   idempotency before enabling consumers.
8. Reconcile provider-side effects. Never resend an action merely because local state was
   rolled back.
9. Run the production-shaped browser certificate against the restored environment.
10. Reconnect integrations gradually, record achieved RPO/RTO, and seal the recovery report.

### Integration event contract

ShopSquire should export a vendor-neutral event first, then adapt it to a supported
Agent Commander/Veeam interface when one is available:

```json
{
  "schema_version": "shopsquire-agent-impact.v1",
  "tenant_id": "tenant-ref",
  "agent_run_id": "run-ref",
  "case_id": "case-ref",
  "case_revision": 12,
  "actor_identity": "deployment-and-model-ref",
  "action": "write|delete|send|reserve|purchase",
  "object_refs": ["opaque-object-ref"],
  "observed_at": "timezone-aware timestamp",
  "idempotency_keys": ["provider-key"],
  "evidence_receipt_hashes": ["sha256"],
  "authority_receipt": "human-or-policy-gate-ref",
  "reversibility": "restore|compensate|irreversible_or_unknown"
}
```

Agent Commander could contribute confirmed and possible impacted-object sets plus policy
findings. Veeam/Kasten could return recovery session, restore point, target, timestamps,
malware status and verification results. ShopSquire would attach those receipts to its
case/agent trace; it would not declare success merely because an API returned `200`.

## Honest interview articulation

### The 60-second answer

> I built ShopSquire as a governed agentic commerce system. The interesting part is not
> product search; it is authority and recoverability. Buyer language becomes an immutable,
> revisioned case. Model output is only a proposal, while deterministic services validate
> quantity, money, time, evidence, allocation and permissions. Every provider observation is
> source- and revision-bound, and stale or contradictory facts fail closed. That maps well to
> Veeam's direction: Agent Commander establishes data, identity and agent context; Veeam and
> Kasten provide trusted recovery points; ShopSquire shows how an application can expose the
> intent, affected objects, idempotency keys and validation needed for precise recovery. I
> have lab and implementation depth here, but I would not claim enterprise Kasten production
> operations I have not performed.

### Strong technical demo narrative

1. Enter the held-out two-turn laptop request and show live-router model identity/latency.
2. Show the canonical case revision changing while quantity, budget, workloads and deadline
   remain stable across the allocation amendment.
3. Show consent before research, source receipts and a contradiction/gap blocking authority.
4. Show stale inventory or quote evidence invalidating only dependent decision stages.
5. Show two feasible allocations with cost/deadline/cover/risk disagreement and the critic.
6. Show that cart mutation, supplier send, reservation and purchase remain false.
7. Finish with the recovery architecture: impact receipt -> isolated restore -> schema and
   evidence validation -> provider reconciliation -> sealed browser certificate.

### Boundaries to state clearly

- “I have a Kubernetes deployment chart and production-shaped Kind/browser gates; I have
  not operated ShopSquire as an enterprise Kubernetes service.”
- “I understand Kasten's application-aware protection problem and restore diagnostics; I
  have not completed a supported Kasten backup/restore lab for this application yet.”
- “Agent Commander publicly describes action history, risk context and precise recovery.
  I would not claim universal undo: sent messages, completed payments and arbitrary external
  API effects may require compensation rather than restore.”
- “I use AI to accelerate hypotheses, then verify against current vendor documentation,
  telemetry and controlled restore tests.”

## Next lab that creates credible Veeam evidence

1. Create a disposable Kubernetes cluster separate from the existing certification cluster.
2. Install a supported Kasten trial/version and record its exact build.
3. Deploy ShopSquire with an in-cluster disposable Postgres solely for the recovery lab.
4. Define a Kasten policy and immutable/export Location Profile.
5. Seed a case, evidence ledger and queued idempotent job; record the recovery-point time.
6. Inject namespace deletion and a database consistency disturbance.
7. Restore to a new namespace with storage-class mapping.
8. Verify database integrity, migration revision, evidence seals, API/browser scenario and
   absence of duplicate external effects.
9. Record achieved RPO/RTO and every manual step.
10. Present it as a lab certificate, not production experience.

Do the Agent Commander integration only after obtaining a supported preview/GA tenant and
API contract. Until then, the vendor-neutral impact/recovery receipt is the right boundary.
