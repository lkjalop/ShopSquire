# ShopSquire — Cloud-Native Deployment, Azure, and Data/Messaging Technology Decisions (2026-07-29)

*Answers: what an Azure deployment actually needs, how AI Foundry fits without breaking the sovereign
thesis, what the marketplace play is, and — decisively — which of MongoDB / TiDB / Kafka / Flink /
RabbitMQ you should adopt.*

## 2026-07-29 correction and execution order

This section supersedes later wording where it differs.

- **Local C0 is now implemented and tested.** `/healthz` is dependency-free
  liveness; `/readyz` is readiness and is wired into compose health. Celery
  beat holds a renewable token-bound Redis lease. Azure Key Vault, Blob and
  Foundry adapters sit behind provider-neutral service contracts, cloud SDK
  imports are confined to `src/app/providers`, and LLM results expose
  model/prompt/policy versions. Fifteen focused tests, Ruff and compose
  validation pass. This is protocol/local proof, not Azure certification.
- The isolated local PostgreSQL/Redis/Celery/browser battery is green:
  migrations, worker ping, 9/9 React journeys and 3/3 live SPA/security
  regressions. GitHub-hosted execution is still blocked by unauthenticated
  `gh`; Azure deployment is additionally blocked because the Azure CLI and an
  authorized subscription are absent.
- Use **Azure Managed Redis**, not Azure Cache for Redis. The latter is in
  retirement and is not a suitable target for a new deployment.
- Azure Container Apps workload-profile VNet integration does not universally
  require `/23`. Size from the current service rules and revision/replica
  envelope; `/24` is the pilot default, while `/27` is the technical minimum
  for the relevant workload-profile shape.
- Start with two required subnets: Container Apps infrastructure and private
  endpoints/data. A management subnet exists only when Bastion or management
  compute is actually deployed. Private DNS and controlled egress are required.
- Azure AI Foundry is now **Microsoft Foundry**. It is an optional, certified
  model endpoint behind ShopSquire's existing provider contract, never the
  orchestration, fact, policy or authority substrate. Foundry Agent Service is
  not adopted merely because ShopSquire uses agents.
- A Managed Application does not automatically remove data-processor,
  security-review or support obligations. Prefer customer-managed access or
  just-in-time publisher access. Marketplace pricing and publisher access need
  their own commercial, privacy and legal review.
- Do not claim exactly-once replication. The edge contract is **at-least-once
  transport with deduplicated, idempotent application effects**.
- The core defines and signs authority. An edge may exercise only fresh,
  explicitly delegated authority within its tenant, site, action, value and
  expiry envelope. `site_id` is authenticated workload identity, never a
  request-selected header.

The corrected delivery order is:

1. Land the current tenant, communication, Decision Trace and Hippograph work
   as reviewable changes and pass its local contract/browser gates.
2. Prove migrations, Redis workers and browser behavior on hosted,
   production-shaped infrastructure.
3. Add portable cloud prerequisites: split liveness/readiness, scheduler lease,
   provider-neutral secret/object/model ports and traceable model/prompt/policy
   versions.
4. Deploy one minimal Azure core using Container Apps, PostgreSQL Flexible
   Server with `vector`, Managed Redis, Blob WORM, Key Vault, ACR and
   OpenTelemetry/Azure Monitor.
5. Introduce signed tenant/site/node identity and a two-node partition harness
   with per-site sequence, gap/dedup checks and abstention.
6. Add signed capability/policy bundles, expiry and atomic activation, followed
   by clock-skew, disk-pressure, certificate-rotation and corrupt-bundle tests.
7. Package a customer-managed Marketplace offer only after the deployment and
   support boundaries are proven.

Do not add AKS, MongoDB, TiDB, Kafka, Flink or a read replica until a measured
trigger demonstrates a problem that the existing Postgres/event/outbox design
cannot solve.

---

## 0. TL;DR — the answer is "less than you think"

| Question | Answer | Why |
|---|---|---|
| MongoDB? | **No** | 1,076 raw SQL `text()` calls. There is no SQL in Mongo. Multi-month rewrite, zero benefit |
| TiDB? | **No** | TiDB speaks MySQL. Your 67 `ON CONFLICT` upserts and pgvector index don't exist there |
| Kafka? | **No** | You have zero throughput justification. Postgres + your outbound queue already gives durable ordered delivery |
| Flink? | **No** | Stream processing for volumes you are three orders of magnitude away from |
| RabbitMQ? | **No** | Redis+Celery works, and you built durability at the *application* layer already |
| Plain Postgres? | **Yes — and it's not close** | 25 pgvector sites, 67 ON CONFLICT, 55 dialect branches, 86 migrations |
| AKS? | **No** | Container Apps. AKS is a platform team you don't have |
| Read replica? | **Not yet** | You have no measured read pressure and no read/write split in the code |
| Azure Marketplace? | **Yes — and it's the strategic unlock** | Managed Application deploys into the *customer's* subscription — see §5 |

**The one-line version:** deploy the boring thing (Postgres + Redis + containers), spend the saved
effort on the Managed Application listing, because that is the only item on this list that changes
your commercial position.

---

## 1. What the codebase actually is (audited)

| Property | Measurement | Consequence |
|---|---:|---|
| Raw SQL via `text()` in services | **1,076 calls** | Not ORM-portable. You are married to SQL |
| `ON CONFLICT` (Postgres upsert) | **67** | MySQL/TiDB syntax differs; Mongo has no equivalent |
| `pgvector` usage | **25 sites** | A Postgres extension. No direct equivalent in Mongo/TiDB |
| `JSONB` | 7 | Postgres-typed |
| `FOR UPDATE` / `RETURNING` | 3 | Postgres row-locking + upsert-return |
| Dialect branches (`dialect.name`) | **55** | Already carrying SQLite↔Postgres cost. A third dialect triples it |
| Migrations | **86** | Every one written against SQLAlchemy + these dialects |
| Kafka / Mongo / TiDB / Flink / RabbitMQ / ClickHouse | **0 files each** | Nothing to migrate *from*. Every one is pure net-new cost |
| Broker | Celery over `REDIS_URL` | Works today |
| OTLP exporter | **already wired** (`observability/init.py`) | Azure Monitor is a config change, not a project |
| In-process caches (`lru_cache`, executors, globals) | **136 sites** | Scale-out constraint — see §4.3 |
| `chat.py` sync vs async routes | **48 sync / 6 async** | Real concurrency ceiling — see §4.3 |

**Read that table as a whole:** this is a SQL-native, Postgres-coupled, event-sourced application with
its durability implemented in application code. Every "modern data stack" component on your list
would be added *alongside* something that already works, not instead of something that doesn't.

---

## 2. Why the specific "no"s — with the honest counter-argument

### MongoDB — no
- **Cost:** rewriting 1,076 SQL statements, 86 migrations, and losing transactional guarantees that
  your money ledger and inventory conservation checks depend on.
- **The steelman:** your `payload` / `checkpoint_json` / evidence bundles are document-shaped, and a
  document store would model them naturally.
- **The rebuttal:** Postgres `JSONB` already gives you that with indexes *and* transactions. You are
  using it. There is no problem here Mongo solves.

### TiDB — no
- **Cost:** MySQL wire protocol. `ON CONFLICT … DO UPDATE` (67 sites) is `ON DUPLICATE KEY UPDATE`;
  pgvector doesn't exist; `RETURNING` doesn't exist.
- **The steelman:** HTAP + horizontal scale, genuinely good for multi-tenant analytics at scale.
- **The rebuttal:** you have 134 SKUs and no customers. Scaling is not your problem; validation is.
  Revisit only if a single tenant exceeds what one Postgres instance handles — which, for mid-market
  wholesale, is roughly never.

### Kafka — no
- **Cost:** an operational component with brokers, partitions, consumer-group semantics, retention
  policy and a whole failure surface. In a **self-hosted** product, every component you add is a
  component your customer's IT team has to run.
- **The steelman:** you are event-sourced. Kafka is the canonical event log.
- **The rebuttal — and this is the important one:** **your event log is the database, and that is the
  correct choice for your architecture.** Events in Postgres are transactional with the projections
  they feed. In Kafka they are not — you'd introduce dual-write and eventual consistency between the
  log and the read model, and then you'd have to *defend* that in an audit. You built conservation
  checks and rebuildable projections precisely so the log and the state can never disagree. Kafka
  would break the property you spent a month building.
- **Revisit when:** you need fan-out to multiple independent consumers across organisational
  boundaries, or >10k events/sec sustained. Neither is on the horizon.

### Flink — no
Stream processing needs a stream. You have `market_analysis.py` detectors running as scheduled batch
over Postgres, which is right for daily/weekly planning cadences. Flink solves sub-second windowed
aggregation over high-volume streams. **Wrong tool, wrong scale, wrong cadence.**

### RabbitMQ — a defensible "not yet"
- **The steelman is real:** Redis-as-broker can lose messages under specific failure modes; RabbitMQ
  has proper acks and durable queues. This is the strongest case on the list.
- **The rebuttal:** you already implemented durability *above* the broker — `outbound_queue.py` has a
  durable table, `idempotency_key` dedup, claim/reclaim on `_stale_claim_seconds`, exponential
  backoff, `max_attempts`, and dead-lettering. **The critical path does not trust the broker.** Celery
  is used for scheduling and best-effort work; the things that must not be lost go through your own
  queue.
- **Revisit when:** you have work that must not be lost *and* is not already routed through
  `outbound_queue`. Audit that before adopting a broker.

---

## 3. Minimal Azure design

```
┌─ Resource Group ─────────────────────────────────────────────────┐
│                                                                   │
│  Azure Container Apps Environment  (VNet-injected)                │
│    ├─ shopsquire-api        (HTTP, scale 1→N)                    │
│    ├─ shopsquire-worker     (Celery, KEDA queue-length scaling)   │
│    └─ shopsquire-beat       (scheduler, replicas=1 ALWAYS)        │
│                                                                   │
│  Azure Database for PostgreSQL — Flexible Server                  │
│    • pgvector extension enabled (supported)                       │
│    • private endpoint only · no public access                     │
│    • PITR backups · zone-redundant HA only if the SLA demands it  │
│                                                                   │
│  Azure Managed Redis  (private endpoint, TLS, ACL)                │
│  Azure Container Registry  (managed-identity pull)                │
│  Azure Key Vault  (secrets; workload identity — no secrets in env)│
│  Azure Blob Storage  (evidence bundles, image artifacts, WORM)    │
│  Azure Monitor + App Insights  ← OTLP, already wired              │
│                                                                   │
│  VNet: apps / data (PE); management only when actually required  │
└───────────────────────────────────────────────────────────────────┘
```

### Why Container Apps, not AKS
AKS is the right answer when you have a platform team, multi-service orchestration needs, or
node-level control. You have three workload types and one maintainer. **ACA gives you scale-to-zero
for workers, KEDA scaling, VNet injection, managed certs, revisions and blue/green — without a
control plane to operate.** Choosing AKS here is choosing a second job.

### Subnets — two required, management only when justified
- **apps** — Container Apps infrastructure subnet (ACA requires a dedicated one; sizing matters, use
  a `/23` for workload profiles).
- **data** — private endpoints for Postgres, Redis, Key Vault, Blob. **No public network access on
  any data service.**
- **management (optional)** — only when Bastion or management compute is
  actually deployed.

Do not build a hub-and-spoke, Azure Firewall, or forced-tunnelling topology for a pilot. Add them
when a customer's security review asks for them — and they will tell you exactly what they want.

### Read replicas — not yet, and here's the trigger
You have **no read/write split in the code**. Every service opens `db_session()` against one engine.
Adding a replica requires a routing layer, and stale-read semantics would interact badly with your
conservation checks and cursor CAS logic.

**Adopt when:** primary CPU > 70% sustained *and* profiling shows reads dominate. **Then** add a
replica and route only the genuinely-safe consumers: `admin_bi.py`, `market_*` analytics,
`bi_intelligence`. **Never** route ATP, cursors, reservations, or money reads to a replica — a stale
ATP is exactly the failure your architecture exists to prevent.

### Azure Monitor — nearly free
`observability/init.py` already prefers an OTLP exporter. Azure Monitor ingests OTLP. Set the
connection string, add `site_id`/`tenant_id` as resource attributes, and your existing Prometheus
metrics and traces land in App Insights. **Config, not code.**

Alert on the things that actually matter here, not CPU:
`outbound_queue` depth and dead-letter count · `gates_pass` false · `unauthorized_rate` > 0 ·
`v2_unavailable` rate by lane · connector circuit-breaker open · `authority_age_seconds` ·
migration drift.

---

## 4. Cloud-native gaps to close first

### 4.1 Secrets — locally implemented; cloud certification outstanding
Key Vault references and workload identity are now supported through the
provider boundary. Existing configuration remains environment-driven for
portable self-hosting, while secret values can resolve through Key Vault.
Azure identity, rotation and outage behavior still require deployment proof.

### 4.2 Health/readiness split — implemented
`/healthz` is lightweight liveness. `/readyz` validates the runtime contract,
database and required serving state; optional deep dependency diagnostics stay
separate. Compose now uses `/readyz`.

### 4.3 The real concurrency ceiling — 🟠 measure before you scale
**`chat.py` is 48 sync routes vs 6 async.** FastAPI runs sync routes in a bounded threadpool, so your
concurrency limit is threadpool size, not async capacity — and each request holds a thread for the
full model call (~7s p95). That is roughly **40 concurrent turns per replica**, regardless of CPU.

Consequences:
- Scale **horizontally** (more replicas), not vertically. ACA does this well.
- Ollama does not batch. **For real concurrency you need vLLM/TGI or a hosted endpoint** — this is
  the same conclusion the latency work reached months ago, now with a deployment shape attached.
- **136 in-process cache sites** must be read-only-derived-from-DB. Any write-cache breaks across
  replicas. Audit `lru_cache` usage before scaling past one replica.

### 4.4 Beat singleton — locally implemented
Beat now starts only after acquiring a renewable Redis lease whose
renew/release operations compare the owner token. Lease loss terminates beat.
Keep replicas at one for the pilot anyway, and retain task idempotency.

---

## 5. Azure AI Foundry — and the thesis tension

**Name the tension honestly:** your differentiator is *"runs in your perimeter, on your model."* AI
Foundry is a managed, Microsoft-hosted model service. Making it the substrate contradicts the pitch.

**The resolution is already in your code.** `turn_router.py:125`:
```python
return (os.getenv("ROUTER_MODEL") or os.getenv("CLASSIFIER_MODEL") or "qwen3:14b")
```
The model is an *endpoint*, and the clamps mean a model cannot break the system because breaking it
isn't in the output space. So:

> **AI Foundry is a supported backend, never the substrate.** It is one entry in a matrix that
> includes Ollama, vLLM, and a customer's own endpoint.

**What it genuinely buys you:**
- Batching and real concurrency without operating vLLM — solves §4.3 for a cloud tenant.
- Content-safety filters as an *additional* layer (never a replacement for your guard).
- Enterprise buyers who already have Azure commitments can spend them on you.

**What to hold firm on:**
1. **Every model backend passes the same clamps and the same shadow replay.** Certify it like any
   provider (§B.9 in the semantics spec: protocol tests vs provider certification).
2. **Record the model + prompt + version in every decision trace.** *"Which model produced this?"*
   must be answerable — and that's an audit requirement, not a nicety.
3. **Never let a hosted model become a hard dependency.** If Foundry is down, degrade to local or
   refuse — the same posture as every other authority.

**One caution:** if a prospect's data cannot leave their perimeter, Foundry is off the table for that
deal. Keep the local path first-class so you never have to say "our product requires sending your
catalog to Microsoft."

---

## 6. Marketplace-agnostic — the actual strategic move

### The portability rule
```
Application layer   → cloud-agnostic contracts. Cloud SDK imports are allowed
                      only in src/app/providers and guarded by an architecture
                      test. Domain/policy services consume provider ports.
Deployment layer    → cloud-specific. Bicep/Terraform per cloud, containers identical.
```
You are close to this already — the only Azure references in `src/app` are incidental
(`geoip.py`, `recruiting_pipeline.py`). **Keep it that way, and add a CI ratchet asserting no cloud
SDK imports under `src/app/` outside a `providers/` directory.** That's the same ratchet pattern that
already works for `no_flavour_in_core`.

Then one container image ships to:
- **Azure Marketplace** — Container Offer or Managed Application
- **AWS Marketplace** — container/AMI
- **GCP Marketplace** — container
- **Direct self-hosted** — the compose files you already have

### 🎯 Azure Managed Application — the unlock

This is the item on this page that changes your commercial position, and it is not obvious:

> **An Azure Managed Application deploys into the *customer's own subscription*, in *their* tenant,
> on *their* network — while you retain a publisher-managed identity for updates and support.**

That means you get **Marketplace distribution, billing, and procurement legitimacy** *without*
becoming a data processor. It resolves the tension that has run through this entire analysis:

| | Multi-tenant SaaS | **Managed App** | Pure self-hosted |
|---|---|---|---|
| Data residency | yours (liability) | **customer's** ✅ | customer's |
| Distribution | your sales | **Marketplace** ✅ | your sales |
| Billing | you build it | **Microsoft bills** ✅ | you invoice |
| Enterprise procurement | full vendor review | **can draw on Azure commit** ✅ | full review |
| Update control | you | **you (publisher identity)** ✅ | customer |
| SOC 2 needed to start | yes | **not to the same degree** ✅ | no |

It also solves a problem I flagged as structural earlier: **"enterprise buyers won't buy from a solo
author."** Marketplace transaction, Microsoft-billed, deployed in their own subscription, with no
data leaving — that is a *dramatically* smaller procurement decision than signing a SaaS contract with
an unknown vendor.

**And it composes with the hybrid-edge design** from the previous doc: the Managed Application is the
**core**; edge nodes are the customer's own containers. Same artifact, two roles.

### Minimum to list
1. Container image in ACR, versioned and signed.
2. Bicep/ARM template + `createUiDefinition.json`.
3. Managed-app definition with the publisher access model.
4. Partner Center account + tax/banking.
5. Ops docs: sizing, backup/restore, upgrade, rollback, support boundary.
6. **The migration rollback rehearsal you already have** — this is a listing asset, not just hygiene.

---

## 7. Sequenced plan

| Phase | Work | Effort | Why |
|---|---|---|---|
| **C0** | Key Vault + workload identity; liveness/readiness; leased beat; version trace | **locally done** | Hosted/cloud certification remains |
| **C1** | Bicep: ACA + Postgres Flexible (pgvector) + Redis + ACR + KV + Blob + 3 subnets, private endpoints | **~1 week** | The deployable artifact |
| **C2** | OTLP → Azure Monitor; alerts on queue depth, gates, unauthorized, breaker | **~2 days** | Mostly config; exporter exists |
| **C3** | **Postgres migration rehearsal on Flexible Server** (86 migrations, up/down/re-up) | **~2 days** | SQLite-proven ≠ Azure-Postgres-proven. **Highest technical risk on this page** |
| **C4** | Cloud-SDK-free ratchet + `providers/` boundary | **~1 day** | Locks portability in as a test |
| **C5** | AI Foundry as a certified backend (protocol + certification split) | **~3 days** | Solves concurrency for cloud tenants |
| **C6** | **Azure Managed Application listing** | **~2 weeks** | The commercial unlock |
| — | Read replica · Kafka · Mongo · TiDB · Flink · RabbitMQ · AKS | **don't** | No trigger has fired |

**C0→C3 is about two weeks and produces a deployable, observable, migration-proven Azure artifact.**
C6 is the one with commercial leverage.

---

## 8. The through-line

Every analysis in this series has converged on the same thing, and this one does too: **the platform
does not need more capability, it needs outside contact.**

The technologies you asked about — Mongo, TiDB, Kafka, Flink, RabbitMQ — are all answers to problems
of *scale*, and you do not have a scale problem. You have a *validation* problem. Adding any of them
converts engineering time into operational surface with no movement on the only metric that matters.

The Azure work is different, but only partly: **C0–C3 are worth doing because they make the system
verifiable by someone else** — the same reason hosted CI and the Postgres rehearsal mattered. And
**C6 is worth doing because it is a distribution channel that doesn't require you to become a data
processor or pass an enterprise vendor review as a solo author.**

Everything else on the list is a way to keep building instead of shipping.

---

*Design and assessment only. No code changed. Audited at HEAD `b07beaf9`.*
