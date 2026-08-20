# Agent Orchestration — What You Built, How It Compares, How to Say It

**Date:** 2026-08-12 · Answers three questions I previously dodged

---

## 1. Is the platform useful today? Direct answer.

**Useful to one buyer type, right now: the procurement or category manager who must justify a
high-value purchase to finance, audit or a regulator.** For them the deliverable is not the
recommendation — it is the record: retained purpose, competing interpretations, which publisher
established each requirement, what remains unverified, what the platform refused to authorise, and
the before/after ranking change when evidence arrived. That artifact exists and works.

**Not useful yet** to a shopper wanting the best product (12-row evidence catalogue), a merchandiser
(ranking is sound but under-fed), or a warehouse planner (26 availability observations, no external
feed).

So: a **narrow, real capability** rather than a broad, shallow one. That is the more defensible
position of the two, but only if you say which one it is.

---

## 2. What your orchestration actually is

Measured, not remembered — `pyproject.toml` contains **no** LangChain, LangGraph, CrewAI, AutoGen,
LlamaIndex, Semantic Kernel, DSPy, pydantic-ai or smolagents. You built the runtime.

What's in it:

| Module | Capability |
|---|---|
| `orchestrator.py` | Phase-gated execution (`phase1: EXPLORE + GUARD`, …) with per-phase tracing |
| `agent_workflow.py` | **Typed `AgentContract`s** — name, phase, type, required/optional |
| `agent_types.py` | Closed `AgentType` vocabulary |
| `agent_dag_runtime.py` | DAG execution with a `TenantPoolManager` |
| `agent_bus.py` / `agent_handoff.py` | Message bus and explicit handoffs |
| `agent_budgets.py` | **Adaptive per-agent budgets** by tier, risk band and event signal — extracted as a pure, unit-testable function |
| `agent_containment.py` | Containment boundaries |
| `agent_run_event_store.py` + `agent_run_replay.py` | **Event-sourced runs with side-effect-free replay** |
| `agent_behavior_anomaly.py` | Anomaly detection on agent behaviour |
| `agentic_rag_pipeline.py` | Retrieval pipeline |

The shape is: **contract-first, phase-gated, budget-bounded, containment-scoped, event-sourced and
replayable.**

---

## 3. How that compares to the frameworks

| | Typical framework (LangGraph / CrewAI / AutoGen / DSPy class) | ShopSquire runtime |
|---|---|---|
| **Optimises for** | Capability and speed of assembly | **Provable restraint** |
| Graph/state machine | ✅ mature, well-tested | ✅ hand-built, narrower |
| Tool calling | ✅ | ✅ |
| Multi-agent handoff | ✅ | ✅ |
| Human-in-the-loop | ✅ (interrupts) | ✅ + typed authority ladder |
| **Per-agent adaptive budgets by risk band** | rare | ✅ |
| **Containment boundaries** | rare | ✅ |
| **Side-effect-free replay of a recorded run** | rare | ✅ |
| **Behavioural anomaly detection on agents** | rare | ✅ |
| **Bitemporal decision record** | ✗ | ✅ 399,612 rows |
| **Explicit refusal vocabulary + `Prevented:` ledger** | ✗ | ✅ |
| Ecosystem, docs, hiring pool, community fixes | ✅ **large advantage** | ✗ |
| Battle-tested at scale | ✅ | ✗ |

**The honest summary:** frameworks are better at everything about *making an agent do things*. Your
runtime is better at *proving what an agent was not allowed to do* — because that is what it was
built for and what frameworks generally do not prioritise.

That is a real architectural position, not a rationalisation. But it comes with a real cost: no
community, no ecosystem, and you maintain it.

---

## 4. Your current answer — what to change

Your draft:

> *"explore the latest research on agentic AI development (agentic AI swarms, bitemporal decision
> trace, interleaved thinking, spatiotemporal concepts, TemporalRAG, hippograph and others) and RAG
> architectures… BMAD method… harness engineering and loop engineering."*

**Problem: nine technologies, zero decisions.** A hiring manager hears breadth of reading, not depth
of judgment. Three specific risks:

1. **Buzzword density triggers scepticism.** Nine named concepts in one sentence invites "explain
   TemporalRAG" — and if any one answer is thin, the whole answer collapses.
2. **No trade-off is stated.** Senior signal comes from what you *gave up*, not what you used.
3. **"Hippograph" is your own internal name.** Using it externally without flagging that reads as
   either jargon or an attempt to sound proprietary.

**Rule: name at most two things, attach each to a decision and a cost.**

---

## 5. Reframed answers, by what they're actually asking

### If asked: "What agent framework have you used?"

> "I deliberately didn't use one. I evaluated the graph-based frameworks, and for this problem they
> optimise for the wrong thing — they make it easy for an agent to *act*, and my hard requirement
> was proving what the agent was *not allowed* to do. So I built a smaller runtime: typed agent
> contracts, phase gating, per-agent budgets that adapt to a risk band, containment boundaries, and
> event-sourced runs I can replay with no side effects.
>
> The trade-off is real and I'd name it up front — I gave up the ecosystem, the community fixes and
> the hiring pool, and I maintain it myself. For a production team I'd probably start with
> LangGraph and add the governance layer on top. For proving the governance idea, owning the
> runtime was the right call."

That answer does four things a list can't: shows you evaluated alternatives, names a concrete
requirement, states the cost, and gives the condition under which you'd choose differently.

### If asked: "How is this different from a RAG chatbot?"

> "Three ways. Retrieval is consent-gated — nothing leaves the customer's boundary without a
> recorded human approval. Claims are bound to publisher policy, so a source is authorised for
> specific claim types and explicitly barred from others; Microsoft can state Hyper-V host
> requirements and cannot authorise VM sizing. And every decision is recorded bitemporally, so I can
> answer 'why did it decide that, on what evidence, as at that date' after the price and the stock
> have changed."

### If asked: "What have you learned from recent research?"

Pick **one** and go deep:

> "The one that changed my architecture was the finding that models often recognise ambiguity when
> asked directly, but still answer rather than ask — and retrieval makes it worse, because more
> context makes a wrong answer more confident. That's exactly what my system did: it mapped a
> cyber-range procurement to a gaming laptop and reported nothing was wrong. The fix wasn't better
> retrieval, it was adding a null class — the router has to be able to output 'I don't know what
> this is' — plus rewarding abstention separately from accuracy."

One insight, one symptom, one fix. Far stronger than nine names.

### If asked: "How do you work?" (the BMAD / harness / loop question)

Drop the labels, describe the loop:

> "I work in a tight review loop with AI doing implementation. I specify the contract, it builds,
> and my job is adversarial review — finding where it's confidently wrong. Concretely: last week a
> trace claimed research 'wasn't required'; I asked why, and the search leg turned out to be
> arithmetically unreachable — cost 5 against a budget of 3 — so it had never run once. That's the
> work. The code is cheap now; knowing which green test is lying is not."

---

## 6. Calibrate to the audience

| They are | Lead with | Avoid |
|---|---|---|
| **Hiring manager / non-technical** | The audit artifact and the refusal behaviour. "It won't claim something it can't prove." | Any framework names |
| **Engineering manager** | The no-framework decision, the trade-off, and when you'd choose otherwise | Research name-drops |
| **Architect / staff engineer** | Phase gating, typed contracts, budgets by risk band, event-sourced replay, bitemporal record | Marketing framing |
| **Security / governance (Securiti team)** | Consent-gated egress, per-publisher claim authority, PII redaction pre-model, data residency, local inference | The commerce story |

---

## 7. Three sentences to have memorised

1. **What it is:** "An AI commerce agent where the model proposes and only deterministic policy authorises — every recommendation carries provenance and every external call needs recorded consent."
2. **Why no framework:** "Frameworks optimise for making agents act; I needed to prove what an agent couldn't do, so I built a smaller runtime and accepted the ecosystem cost."
3. **What you learned:** "More retrieval makes a wrong answer more confident, not less — abstention has to be a separately rewarded behaviour, not a by-product of good search."

---

## 8. One caution

Don't claim the platform is production-ready or broadly useful. You've measured that it isn't —
12-row evidence catalogue, commercial layer behind a bug, market intel in shadow. **Say "narrow and
real" and you're credible; say "a full commerce platform" and one probing question ends it.**

The strongest version of your story is: *"I built a governance layer for AI decisions, tested it
adversarially against my own product, and found three classes of failure that most teams ship
without noticing."* That is true, checkable, and more impressive than the feature list.
