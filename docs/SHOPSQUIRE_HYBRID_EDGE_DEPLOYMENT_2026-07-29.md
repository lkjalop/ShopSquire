# ShopSquire — Hybrid Edge Deployment Design & Resume Defensibility (2026-07-29)

*Two questions: how to deploy ShopSquire as a hybrid edge system and what is actually needed; and how
to put that on a resume in a way that survives an interview.*

---

## 1. What "hybrid edge" means for ShopSquire

For a wholesale distributor or a multi-site retailer, the topology is:

```
┌─────────────────────── CORE (their DC, their cloud, or yours) ────────────────────────┐
│  • policy & authority definitions (FX rates, UoM categories, gates, tenant config)     │
│  • model artifact registry + signed model/prompt distribution                          │
│  • canonical fact aggregation (orders, receipts, valuation) → BI, forecasting          │
│  • cross-site inventory view, transfer planning, supplier scorecards                   │
│  • audit archive of record (long-retention decision log)                               │
│  • connector hub → NetSuite / Odoo / Xero / SAP-BO                                     │
└───────────────────────────────┬────────────────────────────────────────────────────────┘
                                │  intermittent, untrusted, high-latency
                                │  (store-and-forward both directions)
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ EDGE: Store 1 │      │ EDGE: WH-2    │      │ EDGE: Store N │
│ • API         │      │ • API         │      │ • API         │
│ • local model │      │ • local model │      │ • local model │
│ • local PG    │      │ • local PG    │      │ • local PG    │
│ • local Redis │      │ • local Redis │      │ • local Redis │
│ • outbound Q  │      │ • outbound Q  │      │ • outbound Q  │
│ • site scope  │      │ • site scope  │      │ • site scope  │
└───────────────┘      └───────────────┘      └───────────────┘
   Must serve buyers, check local ATP, and draft procurement
   with the WAN down. Must never invent authority it doesn't hold.
```

**The governing principle, which falls straight out of the existing doctrine:**

> **The edge may *decide* and *draft*. Only the core may *authorize* what crosses a site boundary.**
> When the edge cannot reach the core, it degrades to what it can prove locally — and says so.

This is the abstention architecture applied to a network partition. An edge node that has lost the
core does not guess at cross-site stock or apply an unverified FX rate; it returns `unknown` with a
reason, which is behaviour the platform already implements everywhere else.

---

## 2. What already supports this (audited, not assumed)

This is the strong part, and it is genuinely unusual — most systems need edge-tolerance retrofitted.

| Capability | Where | Edge relevance |
|---|---|---|
| **Store-and-forward outbound queue** | `fulfillment/outbound_queue.py` — table with `pending\|sending\|sent\|dead_letter`, `idempotency_key` dedup, `attempts`/`max_attempts`, `next_attempt_at`, exponential `_backoff_seconds`, **claim/reclaim via `_stale_claim_seconds`**, EDI-855 `ack_status` | **Textbook edge durability.** A crashed edge worker's claim is reclaimed; nothing is lost or double-sent across a partition |
| **Optimistic-concurrency sync cursors** | `erp/connector_runtime.py` — `get_cursor_state` / `compare_and_set_cursor` with `cursor_version` + `checkpoint_json` over `erp_sync_state` | Resumable, conflict-safe edge↔core replication. This is the exact primitive needed |
| **Stalled-run recovery** | `recover_stalled_inventory_runs(stale_after_seconds=900)`, `recover_stalled_erp_outbound(...)` | Edge nodes lose power. Runs self-heal |
| **Retry-After honouring with cap** | `retry_after_seconds(value, cap_seconds=60)` | Well-behaved reconnection storms |
| **Self-healing degraded memory** | `deps.py` — `DummyRedis` fallback **that re-probes and recovers** ("memory store RECOVERED — replacing DummyRedis fallback") | Survives local Redis restart without a process bounce |
| **Event-sourced rebuildable projections** | `inventory_event_projection.py`, `inventory_projection_read_model.py` + conservation checks | An edge node can **rebuild its read model from the event log** after corruption or a bad merge — the single most valuable edge property |
| **Idempotency everywhere** | `idempotency_key` / `provider_ref` dedup across 10+ services incl. money ledger | Replay after reconnect is safe by construction |
| **BYO-model indirection** | `ROUTER_MODEL → CLASSIFIER_MODEL → certified default` (`turn_router.py:125`) | Big model at core, small model at edge — no code change |
| **DB portability** | SQLite + Postgres, 86 migrations, Postgres runtime boundary test added today | SQLite for a thin store node, Postgres for a warehouse node |
| **7 compose variants** | incl. `postgres`, `tls`, `secure`, `observability` | Deployment profiles already exist as artifacts |
| **Redis TLS + ACL enforced** | `deps.py:67,70` — `redis_acl_credentials_required`, `redis_tls_required` | Edge security posture is already fail-closed |
| **SSRF egress allowlist** | `ensure_safe_outbound_url`, `INTERNAL_SERVICE_ALLOWLIST` | Edge nodes on untrusted networks can't be pivoted through |
| **Tenant ContextVar + membership** | `platform/tenant_context.py`, `operator_tenant_membership.py` | The scoping mechanism a site identity extends |
| **Multi-location availability + transfers** | `multi_location_availability.py`, `location_id` throughout | The domain model is already site-aware |

**Assessment: roughly 70% of the hard parts exist.** The durability, idempotency, resumability and
rebuild primitives — the things that are painful to retrofit — are already built and tested.

---

## 3. What is genuinely missing

Seven gaps. Ranked by whether they block a working edge deployment.

### 🔴 G1 — Redis is a hard-fail dependency in non-dev
```python
# deps.py:119
raise RuntimeError("redis_unavailable_in_non_dev")
```
An edge node whose Redis is down **dies in production mode**. Today that's correct (Redis is local
and its loss is a real fault); at the edge it must be survivable.

**Fix:** a third mode — `REDIS_MODE=required|degraded|local`. In `degraded`, the node serves
stateless turns with an explicit `session_memory: unavailable` flag in the response and the trace.
**Effort: S.** The self-heal machinery already exists; only the policy needs to change.

### 🔴 G2 — No site identity
`tenant_id` exists; `site_id` / `node_id` does not. Every edge-originated record needs to say which
node produced it, or you cannot reconcile, audit, or resolve conflicts.

**Fix:** `site_id` as a ContextVar mirroring `tenant_context.py` (the pattern is proven), stamped on
every event, every decision trace, and every outbound message. **Effort: M** — it touches many write
paths, which is exactly why it must be done before anything else, not after.

### 🔴 G3 — No bidirectional sync protocol
`erp_sync_state` handles **connector→ShopSquire pull**. There is no **edge↔core** replication: no
push of edge-generated events to core, no pull of core policy to edge, no conflict resolution.

**Fix:** two channels, both built on the existing cursor primitive.
- **Up (edge→core):** append-only event shipping. Events are immutable and idempotent, so this is
  at-least-once delivery with dedup on `(site_id, event_id)` — **no conflict resolution needed.**
  This is why event-sourcing was the right call.
- **Down (core→edge):** versioned policy bundle (FX authorities, UoM categories, gates, tenant
  config, taxonomy, prompts) — **signed**, monotonically versioned, atomically swapped.

**Effort: L.** The largest single item, and the one that defines the architecture.

### 🟠 G4 — No authority TTL / staleness enforcement at the edge
`currency_authority` already rejects stale FX (`fx_authority_stale_or_future`). But there is no
policy for *"the edge has been offline for 6 hours; which authorities have expired?"*

**Fix:** every distributed authority carries `valid_until`. On expiry the edge **refuses the
dependent operation** rather than using a stale rate. Surface `authority_age` in the trace.
**Effort: S** — the refusal mechanism exists; it needs a clock and a bundle version.

### 🟠 G5 — No offline capability manifest
The edge must *know and declare* what it can still do while partitioned. Today it would discover
failures one call at a time.

**Fix:** a declared matrix, enforced and surfaced in the UI:

| Operation | Offline? |
|---|---|
| Browse / recommend from local catalog | ✅ |
| Local-site ATP | ✅ |
| Cross-site ATP | ❌ `unknown: core_unreachable` |
| Cart / draft order | ✅ (queued) |
| Payment capture | ❌ never at the edge |
| Draft supplier RFQ | ✅ (queued, unsent) |
| **Send** to supplier | ❌ human gate + core authority |
| FX-dependent comparison | ✅ only while authority is fresh |
| Decision trace write | ✅ local, shipped later |

**Effort: M.** High demo value — this table *is* the edge story.

### 🟠 G6 — No model/artifact distribution
BYO-model resolves from env. There is no signed distribution or version pinning of model + prompt +
taxonomy across nodes, so two edges can silently answer differently.

**Fix:** treat the model+prompt+taxonomy as one versioned, signed bundle; record its version in every
decision trace. **Effort: M.** This also closes a real audit hole: *"which model produced this
decision?"* should be answerable from the trace.

### 🟡 G7 — No edge observability aggregation
Prometheus exists per-node; no fleet view, no per-node partition/lag/queue-depth metrics.

**Fix:** remote-write to core with `site_id` labels; add `edge_partition_seconds`,
`outbound_queue_depth`, `policy_bundle_version`, `authority_age_seconds`. **Effort: S.**

---

## 4. Build plan

| Phase | Items | Effort | Proves |
|---|---|---|---|
| **P0 — Two-node local proof** | G1 + G2 + minimal G3 (up-channel only) | **~1 week** | An edge node serves buyers with the core unreachable, queues its events, and reconciles on reconnect |
| **P1 — Policy plane** | G3 down-channel + G4 + G6 | ~2 weeks | Authorities distribute, expire, and refuse when stale |
| **P2 — Operability** | G5 + G7 | ~1 week | Fleet is observable and the offline matrix is declared and enforced |
| **P3 — Field hardening** | clock skew, cert rotation, disk pressure, bounded local retention, partition >24h | ~2 weeks | Survives the real world |

**P0 is the one that matters** — see §5.

---

## 5. The resume question — and the honest answer

### The problem with the question as asked

You asked how to *confidently* put a hybrid edge deployment on your resume. The honest answer is:
**right now, you can't put "deployed" on it, because you haven't deployed it.** An interviewer who
does edge work will ask "how many nodes, what was your worst partition, what broke" and the answer
would be "none, none, nothing" — and everything else on the resume becomes suspect. Given that your
entire differentiator is *not overclaiming*, this is the one place you cannot afford to.

**But the fix is small, and it is the same insight as everywhere else in this project:** don't ask
how to word the claim — **build the smallest artifact that makes the claim literally true.**

### The smallest artifact: P0, about one week

```yaml
# docker-compose.edge.yml — two nodes + a partition switch
services:
  core:     { … api, postgres, redis, connector hub … }
  edge-1:   { … api, postgres, redis, local model, site_id=STORE-01 … }
  toxiproxy: { … the WAN between them, switchable … }
```

Then a test suite that proves the interesting properties:

```
test_edge_serves_recommendations_while_core_unreachable
test_edge_returns_unknown_for_cross_site_atp_when_partitioned
test_edge_queues_outbound_and_sends_nothing_during_partition
test_edge_replays_queued_events_exactly_once_on_reconnect     ← idempotency proof
test_edge_refuses_fx_comparison_when_authority_expired        ← authority TTL proof
test_core_policy_bundle_version_swaps_atomically
test_partition_of_6_hours_reconciles_without_duplicate_orders
```

That is **seven tests and a compose file.** With them, every claim below becomes something you can
put on screen in an interview.

### Resume lines by evidence tier

#### ❌ Tier 0 — Do not write these (you cannot defend them)
- ~~"Deployed ShopSquire across N retail edge locations"~~
- ~~"Managed edge fleet in production"~~
- ~~"Reduced store latency by X% via edge inference"~~

#### ✅ Tier 1 — True today, before you build anything
> **Designed an offline-tolerant hybrid-edge architecture** for a governed commerce platform —
> event-sourced edge nodes with store-and-forward outbound queues (idempotent dedup, crash-claim
> reclamation, exponential backoff), optimistic-concurrency sync cursors, and rebuildable local
> projections; edge decides and drafts, core authorizes anything crossing a site boundary.

Every clause maps to code that exists: `outbound_queue.py`, `connector_runtime.compare_and_set_cursor`,
`inventory_event_projection.py`. **Defensible today.**

#### ✅✅ Tier 2 — True after P0 (~1 week) — *this is the target*
> **Built and verified a hybrid-edge deployment model** (core + site nodes) for a 400k-line
> event-sourced commerce platform: nodes serve buyers and draft procurement through simulated WAN
> partition, queue outbound messages durably, and reconcile **exactly-once** on reconnect —
> proven by an automated partition-injection suite (`toxiproxy`) covering 6-hour outages, duplicate
> replay, and expired-authority refusal.

Note the verbs: **built and verified**, not deployed. Note the proof: a named tool and named
scenarios. That is a claim an interviewer can probe and you can answer for an hour.

#### ✅✅✅ Tier 3 — Only after a real site runs it
> "Operated N edge nodes across M sites; p95 partition recovery X; zero duplicate orders over Y
> transactions."

### The line — state it as a rule
> **You may claim what you built and can demonstrate. You may not claim scale, duration, or
> production operation you have not had.**
>
> "Designed" and "built and verified" are honest and strong. "Deployed" and "operated" are claims
> about the world, not about your code, and they require the world to have happened.

### How to make the interview *better* than the resume line

When asked *"have you run this in production?"*, the strong answer is:

> "No. I built it and I proved the failure modes in a partition-injection harness — six-hour outage,
> duplicate replay, expired authority. What I haven't faced is the things a harness can't simulate:
> clock skew across sites, certificate rotation during a partition, and disk pressure from a queue
> that never drains. Those are the three I'd want to design for first with someone who has operated a
> fleet."

That answer is **more impressive than a yes**, because it demonstrates you know the boundary of your
own evidence — which is the exact quality the rest of this platform is built to demonstrate. It also
turns the weakness into the strongest signal you have.

### The general principle for the whole resume
Your differentiator across every artifact in this project is that **you record what you cannot
prove.** The archive manifest records `36 failed`. The quality harness reports `gates_pass: False`.
The forecast layer refuses to publish a number below its evidence threshold.

**Your resume should be built the same way.** A resume that concedes exactly one thing — *"no
production traffic yet"* — while everything else is verifiable, is far more credible than one that
blurs it. The concession is not a weakness in the document; it is the document's proof of accuracy.

---

## 6. Recommendation

**Do P0.** One week, seven tests, one compose file. It converts your strongest architectural story
from an assertion into a demonstration, and it upgrades a resume line from Tier 1 to Tier 2.

**Sequencing note:** P0 is genuinely worth doing *before* the remaining pilot items, for one reason —
a hybrid-edge proof is also the most credible thing you can show a wholesale design partner. A
distributor with three warehouses and unreliable links does not want to hear about your model. They
want to know what happens when the link drops. **The P0 harness answers their first question and
your interview question with the same artifact.**

---

*Design and assessment only. No code changed. Audited at HEAD `b07beaf9`.*
