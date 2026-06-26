# ShopSquire — Hippograph / Intelligence Substrate Assessment + Foundation, Extraction & Frontend-Parity Plan

**Date:** 2026-06-25
**Author:** Claude Opus 4.8 (4-explorer evidence sweep: graph/memory substrate, interaction surfaces, frontend parity, large-file census)
**Companion docs:** `SHOPSQUIRE_ATTRIBUTION_BACKBONE_ARCHITECTURE_2026-06-25.md`, `SHOPSQUIRE_MERGED_ROADMAP_2026-06-25.md`

---

## 1. Verdict: build a hippograph **layer**, not a hippograph **database**

A "hippograph" (hippocampus-style knowledge graph: entity nodes + relationship edges + PageRank/embedding recall that lets intelligence *compound* and feed back) is the right architecture for the market-intel loop. But **a dedicated new graph DB is not warranted** — ShopSquire already has the substrate, mostly latent:

| Hippograph ingredient | Already exists? | Evidence |
|---|---|---|
| **A property graph of events** | ✅ **latent** | `decision_trace_events` is literally `(source_type, source_id) --event_type--> (target_type, target_id)`, sequenced, with `created_at` (`models/decision_trace_events.py:8–21`). Nodes = agents/products/users/decisions/incidents; edges = ranked/escalated/triggered |
| **A real graph DB** | ✅ wired (scoped) | Neo4j 5 + APOC + GDS, profile-gated (`docker-compose.yml:104–130`); `neo4j_graph.py:10–32`; **3-tier adapter** InMemory→Neo4j→DurableFallback in `graph_retrieval.py:32–380` |
| **A GNN** | ✅ (heuristic fallback) | GraphSAGE `FraudGNN` (`gnn_fraud_detector.py:198`), heuristic when PyG absent |
| **Semantic edges** | ✅ | pgvector product+session embeddings (`repositories/embeddings.py:36–204`); RRF hybrid (`candidate_retriever.py:63–81`) |
| **Temporal backbone** | ✅ | bitemporal `decision_logs` (valid/system time, `decision_log.py:426–429`) — replayable |
| **Episodic memory** | ✅ | `memory.py` (Redis session KV), `episodic_memory.py` (Episode/UserProfile/SessionSummary), `observation_engine.py` (Observer+Reflector compression) |
| **Reward edges (decision→conversion)** | ❌ **missing** | this is exactly the attribution backbone — the highest-signal edge for PageRank |
| **Entity resolution** | ❌ **missing** | no NER/entity-linking; "Dell"/"DELL"/"xps-123" never unified into one node |
| **Persisted relationships** | ⚠️ on-demand | `graph_retrieval` computes edges per-request; nothing stores `:BOUGHT`/`:VIEWED`/`:CONVERTED` durably |
| **PageRank / PPR recall into agents** | ❌ missing | no graph-ranked insight fed back to agent context |

> **Conclusion:** the hippograph is a **unification + ranking service** over substrate you already run — *not* a new datastore. Stand up Neo4j-as-general-relationship-store **only when multi-hop becomes hot-path** (Phase 4+). Until then, project the SQL trace + attribution + entity nodes through the existing `graph_retrieval` adapter (InMemory/Neo4j) on demand.

**The two genuinely-new primitives:** (1) **entity resolution** (canonical brand/product/user IDs) and (2) **relationship + reward persistence** (the attribution conversion edge + durable `:CONVERTED`/`:VIEWED`). Everything else is wiring existing pieces.

---

## 2. Collect → ingest (source decomposition) → feed back

### 2.1 Collect (sources, all already flowing)
- **Behavioral:** `routers/consumer_signals.py` (clickstream, PII-hashed), `services/search_events.py`.
- **Commerce:** orders/returns/inventory (`orm.py`, `inventory_*`).
- **Decision/agent:** `decision_trace_events` (the edge stream) + `decision_logs` (bitemporal facts).
- **Episodic:** Redis `session:{uid}:*` (`memory.py:10–17`), `episodic_memory`, `observation_engine`.
- **Reward (new):** `conversion_event` from the attribution backbone.

### 2.2 Ingest = source decomposition + entity resolution + projection
1. **Normalize** all sources into the `market_signal` envelope (the shared contract from the attribution/market-intel design).
2. **Decompose** — `query_decomposer.decompose()` already extracts slots/intent/constraints; this is the per-query decomposition. The **missing** step is **entity resolution**: a new agnostic `services/entity_resolution.py` (→ `_CORE_MODULES`) that canonicalizes brand/product/user mentions (data-driven from the catalog + profile `manufacturers`/`known_brands` slots — *not* hardcoded) into stable `entity_id`s.
3. **Project** — a Celery job folds `decision_trace_events` edges + `conversion_event` reward edges + resolved entity nodes into the graph via the existing `graph_retrieval` adapter (in-memory first; Neo4j when persistence is needed). Bitemporal `decision_logs` give the time axis.
4. **Rank** — Personalized PageRank (or PPR-over-embeddings) seeded from the current query/session entities → top-k related entities/edges with scores. (Neo4j GDS already available for PageRank when promoted.)

### 2.3 Feed back — the injection points already exist (use them, don't invent new pipes)
The explorer mapped **19 live injection points**. The ones that matter for the hippograph:

| Channel | Where insight is injected | file:line |
|---|---|---|
| **Agent context** | `session:{uid}:kv_state` new key `intelligence_scores` / `hippograph_insights` (agents already read `mem.get_kv(uid)`) | `memory.py:142–170`, read at `recommend.py:~4965` |
| **Agent input (NQE)** | new `NQEInput.hippograph_context` field | `flows/nqe.py:59–95` |
| **Agent scratchpad** | bullets from `agent_steps` → reasoning | `recommend.py:3253–3299` |
| **A2A** | `AgentBus.publish()` payload + `agent_handoff` context dict | `agent_bus.py:75–93`, `agent_handoff.py:42` |
| **A2A (swarm)** | DAG phase results — add a ranking pass | `agent_dag_runtime.py:111–115` |
| **A2H (real-time)** | emit `hippograph_insight` trace event → frontend WS | `decision_trace_events.py:276–372`, broker `trace_broker.py` |
| **A2H (chat)** | new SSE event between `ranking` and `answer` | `chat_stream.py:51–100` |
| **H2A (feedback)** | approvals override, NQE feedback, escalation-room playbook step → become **new edges** (human-labeled) | `approvals.py:107–148`, `recommend.py:11851–11943`, `escalation_room.py:25–32` |
| **Dashboards** | `admin_bi`, `merchant_intelligence` (citation_memory), `status_summary` — new endpoints/fields | `admin_bi.py`, `merchant_intelligence.py:78–120`, `status_summary.py:21–100` |

**The loop:** signals → entity-resolved nodes + edges (incl. conversion reward + human-feedback edges) → PPR recall → injected into agent context / dashboards / chat → agents act → new trace edges → graph compounds. **Human feedback is itself a high-trust edge** (approval/rejection, NQE-helpful, escalation outcome), which is the hippocampal "consolidation" signal.

---

## 3. Foundation — what to build first (strict order)

The hippograph is **not** the first thing to build — it's the capstone that needs reward edges and entity nodes to be meaningful. Order:

1. **Attribution capture loop** (prior design, Phases 0–1) — creates the **conversion reward edge**. Without it the graph has nothing to PageRank *toward*. *Highest priority; already designed.*
2. **Entity resolution service** (`services/entity_resolution.py`, agnostic core) — the missing primitive; canonical brand/product/user IDs. Everything graph-y depends on it. Profile-driven (reads `manufacturers`/catalog), parity-tested across verticals.
3. **Graph projection read-API** over the *existing* `decision_trace_events` + `conversion_event` + entity nodes, via `graph_retrieval` (in-memory adapter first). Read-only; proves the latent graph before any persistence. Expose `/api/v1/graph/knowledge` + a PPR endpoint.
4. **PPR / embedding recall** — seed from current session entities, return top-k related nodes/edges with scores.
5. **Feedback injection** — write `hippograph_insights` to `kv_state` + emit trace events; wire into NQEInput + dashboards. **Default-OFF behind a flag** (advisory only) until bench-validated — same discipline as the attribution reward feed.
6. **(Phase 4+) Persist relationships in Neo4j** — promote from fraud-profile to general relationship store only when multi-hop recall becomes hot-path and SQL/in-memory projection can't keep up.

This sequence maps onto the merged roadmap: **#1 = Phase 1 (capture); #2–#5 = Phase 3–4 (intelligence store + analysis); #6 = Phase 4+ scale.** The hippograph *is* the market-intelligence store (M2) + analysis recall (M3), built on the substrate rather than parallel to it.

---

## 4. Extraction / excision required before continuing

Census: ~350 files / 144k lines (104 routers, 250 services, 129 security). Guardrails: 21 `_CORE_MODULES`, 13 `_PENDING_EXCISION`, 7 silent-except baselines.

**The honest answer: only ONE extraction is a true prerequisite for the hippograph path** — because the hippograph's agent-feedback half injects into the agent-context build, which lives in the orchestrator's phases, currently bundled with error handling.

| Priority | File | Lines | Action | Why now / defer |
|---|---|---|---|---|
| **MUST (before agent-feedback wiring)** | `services/orchestrator.py` | 4,009 | Split the 4 phases into `orchestrator_phase_{explore,evaluate,plan,act}.py`; consolidate the two proposal-build paths so **one** place stamps arm/variant + injects hippograph context | The intelligence layer wraps/feeds agent phases here; clean seams needed for injection + arm-stamping (also required by attribution) |
| **CONTINUE (parallel, non-blocking)** | `routers/recommend.py` | 11,980 | Keep the strangler ladder (23 `recommend_*.py` already extracted); ensure the response-assembly + capture seam (`:10238`) is clean | Attribution E0 inserts here; don't block on full shrink |
| **DEFER until touched** | `security/email_security.py` (5,108), `routers/merchant_dashboard.py` (3,488, inline HTML), `routers/admin.py` (4,168), `routers/support_complaints.py` (3,990) | extract only when a feature PR opens them | Not on the hippograph/attribution path |
| **LEAVE (good cohesion)** | `services/recommendations.py` (2,223), `routers/decisions.py` (2,565), `escalation_room.py` (1,936), `playbook_engine.py` (1,767), `framework_correlation.py` (1,386), `inventory_agent.py` (1,320) | none | Already cohesive |

**Rule (unchanged):** edges/features first → extract only the seam a PR touches → never "extract + add behavior" in one PR → ratchets (`test_no_flavour_in_core.py:119–132`, `test_no_silent_except_in_core.py:25–41`) must only move down.

So before continuing: **extract orchestrator phases** (the one prerequisite), keep recommend.py extraction running in parallel, defer the rest.

---

## 5. "Frontend works like the backend" — wiring + test harness

### 5.1 The contract (what the frontend actually expects)
The frontend calls **`/api/v1/chat/query`** (App.tsx:1374), not `/recommend/suggest` directly. It expects `products[]` where each item needs **`price` OR `price_cents`** (the $0 bug class we fixed), `stock_status ∈ {in_stock,low_stock,very_low_stock,out_of_stock}`, `cart_eligible`, plus `assistant_message`, `next_questions[{id,text,options[{id,label}]}]`, `needs_human_review`, `security_route`, `right_panel.anchor_sections`, and a `trace_id` (frontend falls back across `decision_trace_id`/`trace_id`/`decision_id`/`case_id` — `App.tsx:150–162`).

### 5.2 Drift risks (where frontend ≠ backend silently)
1. **price/price_cents** — must send at least one, consistent (`App.tsx:1196`, `ProductGrid.tsx:7`, `CartPanel store:87`). *Already partly fixed; needs a test to lock it.*
2. **stock_status enum** — unknown value or null → no badge / false "in stock".
3. **trace_id naming** — 5-name fallback → if all absent, trace not clickable.
4. **next_questions shape** — strings vs `{id,text,options}` objects → render crash.
5. **needs_human_review presence** — null → escalation UX never opens.
6. **Any new hippograph insight field** — must have a contract assertion or it drifts.

### 5.3 Test infra that already exists
- **Frontend:** `tsc --noEmit` (tsconfig `noEmit:true`, strict), vitest (`ProductGrid.test.tsx`, `stores.test.ts`, panel tests).
- **Browser parity:** `tests/pw/test_answer_first_parity.py:26–71` — intercepts the live response and asserts **DOM SKU set == backend SKU set** + card count. `tests/pw/test_demo_e2e_clickthrough.py` — extensive scenarios.
- **API contract:** `tests/api/test_ui_contracts.py`, `tests/test_api_contract.py`, `tests/integration/test_recommend_contract_stability.py`.

### 5.4 What's missing + how to build the parity gate
Missing: a **`/chat/query` response-shape contract test** (price/stock/trace-id/nqe), a **snapshot diff**, and **CI wiring**. Build it in three cheap layers (~2–3 h):

1. **Backend contract test** (`tests/integration/test_frontend_backend_parity.py`): fire representative queries at `/api/v1/chat/query` (TestClient), assert every frontend-required field + every product has price-or-price_cents (consistent), valid stock enum, resolvable trace_id, well-formed next_questions. *Add one assertion per new hippograph field as it ships.*
2. **Playwright price/stock parity** — extend `test_answer_first_parity.py` to compare *rendered* price text and stock-badge presence against the intercepted backend response (catches the $0/`—` rendering class end-to-end).
3. **Snapshot gate in CI** — pin the `/chat/query` response schema; fail the PR on unintended shape change. Run `tsc --noEmit` + vitest + the Playwright parity test in CI.

**Principle:** the backend is the source of truth; the frontend must render exactly what it sends, and **every new field added to the response (attribution, hippograph insight, availability allocation) gets a contract assertion in the same PR.** That is what "frontend works like backend" means operationally — a gate, not a vibe.

---

## 6. Bottom line

- **Hippograph:** build it as a **unification + entity-resolution + PPR-recall service** on the existing substrate (decision_trace edges + attribution reward edges + Neo4j + pgvector). **No new DB.** Promote Neo4j to general relationship store only when multi-hop goes hot-path.
- **Foundation order:** attribution capture (reward edges) → entity resolution (the missing primitive) → graph projection read-API → PPR recall → feedback injection (flagged advisory) → Neo4j persistence later.
- **Extraction gate:** the **one** must-do-first is **orchestrator phase separation** (clean seams for agent-context injection + arm-stamping); recommend.py strangler continues in parallel; defer the rest until touched.
- **Frontend parity:** the contract test + Playwright price/stock parity + CI snapshot gate; every new response field ships with its assertion.
