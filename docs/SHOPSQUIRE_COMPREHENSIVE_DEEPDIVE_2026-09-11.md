# ShopSquire — Comprehensive Deep Dive: Loop & Harness, Subsystem Wiring, Demo and Pilot Readiness

**Date:** 2026-09-11 · **HEAD:** `a0218c26` · **Working tree: clean**
**Overnight delta:** 2 commits, 44 files, **+1,711 / −94**
**Method:** import-graph reachability from the chat turn, live API probes against the warm stack,
live decision-trace inspection, source/AST inspection, full backend sweep. No cart, supplier,
approval or payment action was taken.

---

## 0. Verdict

Three things are true at once, and holding all three is the whole picture.

1. **The governance engine is genuinely good and getting better fast.** Overnight the compiler
   went from 2 to 4 accepted claims on Baldur's Gate 3, the tree is clean and the size guard passes.
   (The backend sweep did pick up **2 fresh regressions** from the overnight work — see §8.)
2. **No workload journey can currently show a qualified shelf.** I tested Baldur's Gate 3 *and*
   Cyberpunk 2077 — mainstream titles with complete published requirements. Both returned
   `accepted=4, completeness=partial, authority=blocked, **0 products**`. The refusal is honest and
   well-worded. It is still a refusal, every time.
3. **What you have is a single-pass staged pipeline, not an agent loop.** That is a defensible
   design — deterministic, traceable, bounded latency — but "loop engineering" and "agent chain"
   are currently labels on something that runs once, top to bottom, with one recorded agent.

**For recording a demo, point 2 is the binding constraint.** The demo's implied promise — *tell me
what you want to run and I'll find the right machine* — cannot be delivered on camera today. §5
sets out what can.

---

## 1. Overnight delta

| | Value |
|---|---|
| Commits | 2 (`2f1592f2`, `a0218c26`) |
| Files / lines | 44 · **+1,711 / −94** |
| Tree | **clean** |
| `chat.py` | 5,011 lines — size guard **exits 0** |
| Backend sweep | `tests/services` + `tests/integration` + `tests/architecture` — see §8 |

Substantive: evidence receipts, bounded acceptance, turn continuity, `generic_requirement_extractor`
(+32), `workload_grounding` (+31), `research_outcome` (+26), `structured_requirement_claims` (+21),
`terminal_research_reconciliation` (+21), and a new `turnOracle` frontend test.

**Measured effect:** BG3 accepted claims went **2 → 4**. Completeness is still `partial`. Progress
on the blocker, not closure of it.

**My D6 remains open** — I reproduced it again this morning on this HEAD: a turn says *"I resolved
Kingdom Come: Deliverance II … qualified 1 catalog configuration"* while carrying the question *"I
identified kingdom come deliverance 2, but no enrolled authoritative provider returned current
requirements."* **D8** (publisher ranking) is also unchanged.

---

## 2. Loop engineering — what is actually there

### 2.1 There is no loop

I searched the recommendation core and the chat router for any iteration construct — `while`,
bounded retry, `max_steps`, `max_iterations`. **There is none.** The live decision trace confirms
it from the other direction:

```json
"agent_chain": [{"agent": "Recommendation_Core", "duration_ms": null}]
"evidence": {"agent_chain": [], ...}
```

One agent, no chain, no duration recorded. The execution shape is:

```
request → interpretation stage → route+intent → evidence stage → catalog research gate
        → retrieval → fit → post-retrieval stages → response stage → terminal projection
```

Each stage runs **once**. There is no observe → re-plan → re-act cycle. When research needs to
happen, it is a *second phase of the same turn* (the two-phase in-progress/complete envelope), not
a loop iteration.

**Is that wrong?** No — and I would not add a loop to chase the label. For a commerce turn with a
hard latency budget, a governed evidence ladder and a bitemporal audit requirement, a single-pass
pipeline is the *easier* thing to make correct and to prove. But two things follow:

- **Stop calling it an agent chain in the trace.** `agent_chain` with one entry and a null duration
  is a field that promises something the system does not do. Either record the real stage sequence
  there or rename it.
- **The one place a loop would genuinely help** is the evidence gap in §5.2: when completeness comes
  back `partial` with named missing attributes (`cpu_model`, `gpu_model`, `os`, `storage_type`), a
  bounded second retrieval pass targeted at exactly those attributes is the natural fix. That is a
  *bounded, attribute-targeted* retry — one extra pass, not an open loop.

### 2.2 The harness is the strong part

`recommendation_core/stage_runner.py::run_guarded_stage` is well built:

- every stage is **additive** and cannot corrupt a valid shelf (it tracks `_msg_priority` before
  and after);
- **cancellation is checked before and after** each stage;
- failures are caught, statused `error`, and recorded rather than propagated;
- stages declare `input_artifact_refs`, `output_artifact_refs`, `dependency_stage_ids` and a
  `stage_id` — the vocabulary for a real dependency graph is already in the signature.

That last point matters: **the harness already has the shape of a DAG runner, but nothing uses the
dependency fields to schedule.** Stages run in hard-coded source order. Populating
`dependency_stage_ids` and scheduling from it would give you parallelism and a truthful
`agent_chain` from the same data. That is the highest-value harness work available, and it is
additive.

---

## 3. Subsystem wiring — measured, not assumed

Import-graph reachability from `src.app.routers.chat` (**439 modules transitively reachable**),
cross-checked against the live trace and the demo launcher's flags.

| Subsystem | Module | Reachable from chat? | Actually exercised on a turn? |
|---|---|---|---|
| **TemporalRAG** | `vector_store` | ✅ | 🟡 `VECTOR_SEARCH_ENABLED` defaults **0** |
| | `temporal_authority` | ✅ | ✅ |
| | `temporal_invalidation` | ✅ | ✅ |
| | `taxonomy_embedding_index` | ✅ | ✅ (classifier path) |
| | `agentic_rag_pipeline` | ❌ **not reached** | ❌ |
| | `graph_retrieval` | ❌ **not reached** | ❌ |
| **Bitemporal trace** | `decision_log` | ✅ | ✅ **real** — see below |
| | `decision_time_travel` | ❌ (separate router — correct) | ✅ via its own endpoint |
| **NLP replies** | `llm_provider`, `terminal_research_narration` | ✅ | ✅ |
| **Product recommendation** | `recommendation_core.core`, `recommendation_facade` | ✅ | ✅ |
| **Market intelligence** | `market_intelligence_agent`, `market_analysis` | ✅ | ❌ **no `MARKET_*` flag in the demo launcher** |
| | `market_facts`, `hippograph_market_projection` | ❌ not reached | ❌ |
| **Procurement** | `fulfillment.draft`, `fulfillment.workflow` | ❌ not reached from chat | ✅ via `fulfillment_cases` router |

### 3.1 Bitemporal decision trace — real, and the best-wired subsystem

Live trace `fa613600-2097-441e-bcbf-6064cda8e74b`:

```json
"bitemporal": {
  "valid_from": "2026-09-11T00:55:33.530630",
  "system_from": "2026-09-11T00:55:33.530630",
  "valid_to": "infinity",
  "system_to": "infinity"
}
```

A proper bitemporal quad — valid-time and system-time, both open-ended. This is genuinely
differentiating and it works. Caveats: `policy_gates` was `null` on that turn, and the
`/decisions/{id}` projection returned **0 events**, so the 15 trace panels are reading from other
endpoints — worth confirming they all agree on one revision (that is the reviewer's §7 point).

### 3.2 TemporalRAG — half-wired, and the half that is missing is the interesting half

The **temporal** side is real and reachable: `temporal_authority`, `temporal_invalidation`,
`temporal_cache_producers`, `temporal_conflicts`. Evidence freshness, cache invalidation and
as-of authority all work.

The **retrieval** side is largely not on the buyer path. `agentic_rag_pipeline` and
`graph_retrieval` are **not reachable from chat at all**, `VECTOR_SEARCH_ENABLED` defaults to `0`,
and the trace records:

```json
"rag_context": {"products_retrieved": 2, "benchmarks_used": null, "user_context": null}
```

Two products retrieved, **no benchmarks, no user context**. So retrieval today is the Postgres
bag-of-words + taxonomy path, with the temporal authority layer on top. Calling that "TemporalRAG"
overstates it: it is temporal evidence governance over conventional retrieval.

### 3.3 Market intelligence — built, reachable, and off in every demo

`market_intelligence_agent` and `market_analysis` are reachable from chat, but
`scripts/start_recording_stack.ps1` sets **no** `MARKET_*` or `HIPPOGRAPH_*` flag. `config.py:286`
records the history plainly: *"market intelligence was OFF in every live run of the arc."*

**If market intelligence is meant to be in the demo, this is a one-line launcher change plus a
rehearsal — it is not a build.** If it is not meant to be in the demo, remove the admin panels from
the demo script so nobody clicks into an empty surface on camera.

---

## 4. The blocker, precisely

| Query | accepted | completeness | authority | products |
|---|---:|---|---|---:|
| *"laptop under AUD 5000 to play Baldur's Gate 3"* | 4 | partial | **blocked** | **0** |
| *"laptop for cyberpunk 2077 under AUD 4000"* | 4 | partial | **blocked** | **0** |

> *"For Baldur's Gate 3, research accepted 4 requirement claims, but requirements coverage remains
> partial. I cannot confirm full compatibility or qualify a product until the missing requirements
> are established."*

The manifest requires `cpu_model`, `gpu_model`, `os`, `storage_type`. The structured provider
yields RAM, storage and a *translated* VRAM figure. CPU and GPU **model** predicates cannot be
compiled from publisher prose without the typed CPU/GPU comparison work that is still unfinished —
and the compiler correctly refuses to invent them.

**So the gate is right and the evidence is short.** Two ways forward, and only one of them is
honest:

- ✅ **Complete the evidence** — typed CPU/GPU model parsing plus a reviewed equivalence table, so
  `cpu_model`/`gpu_model` can be satisfied. Needs your independent reviewer (§7).
- ❌ **Relax the manifest** so partial coverage qualifies. Do not do this. It would make every
  screenshot contradiction return.

A legitimate third option for the demo specifically: **a narrower manifest for a category where
the published evidence genuinely is complete.** If a vertical exists whose publisher data covers
its full obligation set, that vertical can demo positive delivery honestly today.

---

## 5. Recording a live demo — what works, what doesn't, what I need from you

### 5.1 Camera-safe today (all verified live by me)

| Journey | Result |
|---|---|
| *"Laptop under AUD 3,000"* | 10 options, budget band correct |
| *"gaming laptop under AUD 3000"* | 2 qualified configurations, scope `el-6-11-2` |
| **Category switch** — laptop → *"a computer chair under AUD 400"* | Honest refusal, budget 400, no inherited hardware requirements |
| **Off-catalog storage** — *"disaster recovery like a raid 5"* | *"we don't stock Storage Devices > Hard Drive Arrays > Portable RAID Enclosures"* — resolved by the model, clamped by the taxonomy |
| **Bulk stock economics** — *"25 gaming laptops…"* | Local ATP / transferable / supplier shortfall reconcile exactly |
| **Decision Trace** | Bitemporal quad, 6 sections / 15 leaves |
| **Procurement operator view** | Draft cage, redaction, gates — via admin |

That is a strong, honest demo: *this system knows what it does not know, and refuses correctly.*

### 5.2 Will break on camera

| Journey | What the audience sees |
|---|---|
| Any *"what laptop for &lt;game&gt;"* | Research succeeds, then **0 products** and a refusal |
| Kingdom Come Deliverance 2 | **D6** — two contradictory messages in one turn |
| Any "approve a publisher source" | **D8** — seven aggregators ranked above the real publisher |
| Emulate3D | 16 held claims, 0 products — blocked on your Rockwell review |
| Market intelligence panels | Empty — flags not set |

### 5.3 What I need from you to make a demo recordable

**Decisions (blocking):**

1. **Demo narrative.** Choose one: **(a) governed refusal** — "watch it refuse correctly five
   different ways", recordable today; or **(b) qualified delivery** — needs §4 first. I recommend
   (a) for a first recording and (b) as the milestone.
2. **Independent reviewer** for source authority and CPU/GPU equivalence. This is now the single
   longest pole — it gates §4, the Rockwell hold, and the derivation ledger. A name and an hour of
   their time unblocks more than any code change on this list.
3. **Market intelligence in or out?** If in, I add the launcher flags and we rehearse it. If out,
   we cut those panels from the script.

**Actions (mechanical, ~30 minutes):**

4. Pre-load `qwen3:14b` and confirm `/api/ps` shows it resident **before** recording — a cold load
   mid-take is a 20-second dead air and has twice bugchecked this machine.
5. `docker start shopsquire-searxng-1`, then confirm `/health` shows
   `external_search.live = true`. Without `-LiveDemo` you will record the mock model.
6. Decide whether the recording includes **any** durable action (cart confirm / sourcing request).
   If yes, we rehearse it on an isolated tenant first — it writes real records.

**One rehearsal request:** run §5.1 end to end once, with the Decision Trace open, before the real
take. Every one of those journeys passed for me this morning; I would rather find a regression in
rehearsal than on camera.

---

## 6. Pilot production grade — ready vs needs polish

| Area | Grade | Ready | Needs polish |
|---|---|---|---|
| **Procurement FSM & draft cage** | **A−** | 55 typed transitions, 372 tests green, fail-closed autonomy, redaction | SoD (approver ≠ requester) still unenforced — **top pilot blocker** |
| **Bitemporal trace** | **B+** | Real quad, time-travel endpoint, 15 panels | PostgreSQL writes, retroactive corrections, panel-to-revision agreement |
| **Evidence governance** | **B+** | Manifest scope, unit/operator validation, derived ≠ observed, receipts | The derivation ledger — gates everything in §4 |
| **Budget & acceptance** | **B** | Literal anchors preserved, explicit stretch consent | Multi-turn/bulk/currency matrix |
| **Catalog scope** | **B** | Model proposes, deterministic clamps, honest off-catalog refusal | Purchase-object vs workload (my N2: Emulate3D turn scoped to *Software*) |
| **Security & tenancy** | **B+** | 142 security test files, `/readyz` clean, redaction verified | Shared-PG certification |
| **Money path** | **B** | Ledger, attempts, reconcile, idempotency keys | Real-PG row-lock concurrency run |
| **NLP narration** | **B** | Honest, specific, no invented qualification | D6 contradiction; count agreement (N1) |
| **Product delivery** | **D** | — | §4 — never green |
| **Market intelligence** | **C** | Built and reachable | Dark in every run; needs a decision |
| **TemporalRAG** | **C+** | Temporal authority real | Retrieval side not on the buyer path |
| **Loop/agent architecture** | **B−** | Excellent guarded-stage harness | No DAG scheduling; `agent_chain` overstates |
| **UI/UX** | **C** | Status pills, trace depth | §7 |
| **Clean-machine / hosted** | **F** | — | Not attempted |

**Shortest path to pilot:** SoD enforcement → derivation ledger (needs your reviewer) → positive
delivery gate → clean-PG certification. Everything else is polish.

---

## 7. UI/UX assessment

Grounded in your five screenshots and the component inventory (48 buyer + 14 trace + 36 admin = 98
components; `DecisionTrace.tsx` 4,358 lines and `App.tsx` 4,348 — two files are 19% of the
frontend).

### What is genuinely good

- **The status pill strip** — EXECUTION / AUTHORITY / FRESHNESS / COMPLETENESS / UNCERTAINTY /
  SIMULATION. Scannable, colour-coded, honest. This is the best design element in the product and
  it should become the primary buyer-facing trust signal, not a trace-panel ornament.
- **Read-only verified values with editable unverified ones** in the review card — the
  affordance correctly encodes the authority model.
- **"Honest answer: we don't stock X"** — plain language where it matters.

### What needs design work

1. **Four surfaces compete for the same screen.** Storefront grid, chat panel, right panel and the
   floating Decision Trace are all visible simultaneously, and the trace **occludes** the right
   panel — in every screenshot the research status text is clipped mid-sentence ("Automatic
   governed research is ready and…"). Nothing tells the buyer where to look.
2. **The same block is rendered twice.** "Discovery / Fetch / Parsed / Held / Accepted / Rejected"
   appears in the right panel *and* in the trace's Research Breakdown, with identical wording, on
   screen at once.
3. **Operator vocabulary in the buyer surface.** `catalog authority: unknown · commerce authority:
   none · transition NEW_CATEGORY · role RUN_SUBJECT_ON_PRODUCT` is audit language. Buyers need
   *"I can't recommend yet — here's what's missing"*; auditors need the rest, behind the trace.
4. **Competing calls to action.** One screen offers *Upload requirements*, *Use official link or
   vendor*, *Enter specifications*, *Retry approved research*, plus five *Use for this case*
   buttons. There is no primary action.
5. **Absence is rendered as a negative claim.** The trace says "no result" during hydration before
   events arrive; it should say *loading / not yet available*.
6. **Two product presentations.** Storefront cards and shelf cards use different layouts and price
   formatting for the same catalogue.

### Recommended direction

- **One primary surface per turn.** Chat answers; the right panel shows *one* thing (shelf **or**
  evidence gap **or** refusal); the trace is a deliberate drawer, not an always-on overlay.
- **Promote the pill strip** into the buyer answer as a single trust line, and move the raw
  authority vocabulary behind "Why?".
- **One primary CTA per state**, with the rest under "Other ways to resolve this".
- **Split the two 4,300-line components.** They are the reason a panel can render a stale shelf:
  too much state in one place. This is a UX fix as much as an engineering one.

---

## 8. Test state and limits

**Backend sweep completed: 2 failures — a regression from yesterday's 0.**

```
FAILED tests/services/test_recommendation_core_brain.py::test_budget_only_revision_overrides_incorrect_model_switch
FAILED tests/services/test_recommendation_core_brain.py::test_budget_only_revision_preserves_answered_scope_when_model_is_unavailable
        AssertionError: assert None == 'el-6-6'
```

Both tests are **pre-existing and unmodified** (added in `107102a8`, untouched by the last two
commits), and the sweep on the preceding HEAD `ad65cee4` was clean. So the behaviour moved
underneath a stable assertion: **a budget-only revision now returns no scope where it previously
preserved the answered category.**

The likely cause is the overnight change described as *"unresolved replacement purchases now get a
fresh clarification and empty scope"* — correct for a replacement, over-applied to a budget-only
refinement. Buyer-visible shape: *"gaming laptop under 3000"* → *"actually make it 2000"* drops the
category.

This is worth noting as evidence for §0 of the companion TDD document: an **invariant-shaped test**
(scope survives a budget-only revision) caught a regression that none of the live journeys I ran
this morning would have found, because none of them issued a budget-only follow-up. The size guard
exits 0 on this HEAD. Every finding above rests on live execution, the live trace, the import graph and
source inspection — not on that suite.

**Not certified by anything here:** clean checkout, PostgreSQL, hosted deployment, WORM retention,
or independent source/equivalence review.

**No cart, supplier, approval or payment action was taken, and no durable sourcing record was
created.**
