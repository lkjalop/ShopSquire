# The target architecture — ending the "screenshot → add deterministic text" treadmill

**Date:** 2026-07-08 · **The problem in one line:** every edge case you screenshot becomes another
hand-coded rule in `suggest()`/`recommend.py`. That treadmill is infinite — buyer intent (payment plans,
$20k orders, deficits, swaps, spec questions) is an unbounded space you can never fully hand-code.
**The cure:** an LLM that *decomposes + orchestrates + narrates* over bounded tools, with guardrails so it
never hallucinates. This doc is the demarcation + the plan.

---

## 1. The demarcation line (the thing to "surface")

The deciding question for ANY buyer turn:

> **Is the answer a FACT/ACTION with one correct value — or does it need DECOMPOSITION, JUDGMENT, or SYNTHESIS?**

| | DETERMINISTIC (keep, fast, exact) | LLM-ORCHESTRATED (smart, grounded) |
|---|---|---|
| **When** | one correct value or one defined effect | decompose intent · judge fit · synthesize across sources · narrate a nuanced/gap answer |
| **Examples** | policy text, a price, stock count, add-to-cart, set-qty, submit-return, routing | "is $3500 enough for training?", "swap the Dell for a Lenovo", "do you do payment plans?", "am I ok waiting for a reorder?" |
| **Latency** | <100ms | ~2–15s (only this tier pays it) |
| **Proven by** | the E2E sweep — FAQ×5, cart ops, returns governance, sourcing all pass and are instant | the A/B — grounded model narration beats the hand-coded templates |

**The load-bearing rule: the LLM never KNOWS the facts. It DECIDES WHAT TO FETCH, then NARRATES over what
the tools returned.** Facts come from tools (RAG / search / inventory / policy / memory). That split is the
entire anti-hallucination guarantee — the model can't invent a price or a payment plan it was never handed.

---

## 2. The three "gather information" mechanisms the LLM orchestrates

You named RAG + external search + context. Here's each, and *when* the orchestrator reaches for it:

| Mechanism | Answers | Tool | When the LLM picks it |
|---|---|---|---|
| **RAG (internal grounding)** | our facts: catalog, specs, KB fit-floors, stock, policy | catalog_search · kb_requirements · inventory_check · policy_answer · pgvector · graph | almost always — the buyer is asking about OUR store |
| **External search** | VOLATILE facts we can't know: today's market price, competitor undercut | web_research (N3, consent-gated) | "is this competitive right now?" — freshness only, never domain knowledge the model already has |
| **Conversation memory** | context: prior cart, confirmed slots, the shortlist, "make it 20" | session_memory (Redis) + recent_messages | every follow-up / amendment |
| **Capability registry** *(NEW)* | what we CAN'T do: no payment plans, no financing, laptop/monitor/desktop only, $20k → human | capabilities() | any "do you offer X?" / high-value / off-capability ask |

The orchestrator's intelligence is in the **selection** — a fit question fans out to kb_requirements +
catalog_search; a "competitive?" adds web_research; a "make it 20" reads memory + calls cart_mutate; a
"payment plans?" hits the capability registry and answers honestly.

---

## 3. The capability registry — the artifact that ends the treadmill

**This is the specific fix for your pain.** Today, "we don't have payment plans" is a hand-coded string you'd
add after screenshotting it. Instead, declare the boundary ONCE:

```json
// config/store_profiles/electronics.json → "capabilities"
{
  "sells": ["laptop", "monitor", "desktop", "tablet", "accessory"],
  "does_not_offer": ["payment_plans", "in_house_financing", "leasing", "trade_in"],
  "autonomy_limits": { "max_autonomous_order_value_aud": 20000 },
  "fulfilment": { "backorder": true, "typical_reorder_days": 7 }
}
```

The orchestrator is **grounded on this**, so for ANY phrasing — "do you do payment plans?", "can I pay
monthly?", "financing options?" — it answers honestly: *"We don't currently offer payment plans or
financing."* You never hand-code the message; you declare the capability boundary, and the LLM narrates it
for infinite phrasings. Same for the $20k case: over the autonomy limit → *"For an order this size I'll bring
in a human account manager"* + escalation, honestly stated.

**That is how you stop taking screenshots.** A new gap = one line in the registry, not a new `if` in
`recommend.py`.

---

## 4. How this handles your exact cases

| Buyer says | Orchestrator plan | Honest, grounded answer |
|---|---|---|
| "training LLM, $3,500?" | kb_requirements + catalog_search | fit verdict, names the 16GB gap, offers step-up (grounded — no invented specs) |
| "make it 20" | session_memory + cart_mutate (qty) | "Updated to 20 — 14 ship now, 6 sourced (~7 days)" (policy gate authorizes the mutation) |
| "swap the Dell for a Lenovo" | session_memory + catalog_search + cart_mutate | resolves "the Dell" from memory, swaps the line, confirms |
| "what's 8GB vs 16GB for AI?" | kb_requirements + (web_research if consented) | domain answer grounded on the KB, cite if external |
| "screen cracked, options?" | returns tools + policy | governed damage/severity/repair (already built) |
| "spend $25k, payment plans?" | capabilities() | "No payment plans; and for a $25k order I'll bring in a human" — HONEST, from the registry |
| "need 50, you have 14, ok to wait?" | inventory_check + fulfilment | "14 now, 36 reordered ~7 days — want me to proceed on that basis?" |

Every one of these is the SAME machine: decompose → pick tools → gather → narrate honestly. None needs a new
hand-coded branch.

---

## 5. The guardrails (why it won't hallucinate)

Four gates, three already in the platform:

1. **Plan validation** — the LLM emits a STRUCTURED plan (intents + tool calls), validated against a schema
   (allowed tools, allowed slots) before ANY execution. Prompt-crafting can't invent a tool or an action.
   *(same schema-forced pattern as the multi-intent binder / query planner already shipped.)*
2. **Grounded synthesis** — the answer is written ONLY from tool outputs. No tool returned a price → the model
   can't state one. This is the anti-hallucination core.
3. **Capability registry** — honest about gaps (payment plans, $20k) instead of inventing capabilities.
4. **Policy gate on ACTIONS** — any cart mutation / refund is *proposed* by the model, *authorized* by
   deterministic policy, *recorded* in the trace. The bounded-autonomy spine you already run for pricing/refunds.

---

## 6. Keeping conversation context (your last point)

Two layers:
- **Session memory** (Redis: `session:{uid}:*`) already carries the shortlist, confirmed slots, cart lines —
  the orchestrator reads it so "make it 20" / "the Dell" resolve.
- **The silent-context-loss fix (Option C, in-process):** today chat→suggest serializes context through a
  query-string bottleneck and *silently drops* anything not mapped. In-process passes the FULL context object,
  so nothing is lost. This is why Option C matters for "keep context" — it's the same doc
  (N7_INPROCESS_SUGGEST_DESIGN).

---

## 7. What maps to what (we already have most of it)

| Target piece | Already built | Gap to build |
|---|---|---|
| Scatter-gather substrate | R2 `evidence_orchestrator.py` (legs) | expose legs as tool schemas |
| Cart mutation | multi-intent planner | expose as `cart_mutate` tool |
| RAG grounding | catalog + KB + pgvector | kb_requirements tool (RK1 makes it truthful) |
| External search | N3 web leg (consent-gated) | keep scoped to volatile facts |
| Context | Redis session memory | Option C (kill silent loss) |
| Authorization | policy gate | unchanged |
| **Capability registry** | — | **NEW — the honesty artifact** |
| **Orchestrator loop** | tier ladder + planner | **NEW — LLM plans → validate → scatter → synthesize** |

---

## 8. Migration (no big-bang; each step flag-gated + parity-tested)

1. **Fix the grounding first** — RK1 (KB-floor truth) + the non-laptop retrieval bug (E2E found it). The
   orchestrator is only as honest as the facts it's fed.
2. **Capability registry** — declare `capabilities` in the profile; a `capabilities()` tool. Small, high-value,
   ends the "payment plans" class of hand-coding immediately.
3. **Tool interface** — wrap the R2 legs + retrieval + cart_mutate as schema'd tools. No behavior change.
4. **Orchestrator loop** — LLM plans → validate → scatter-gather → grounded synthesis. Flag
   `ORCHESTRATOR_LANE_ENABLED` default OFF, running SHADOW beside the deterministic path (compare, don't route).
5. **Route the hard tier to it** — high-complexity queries go to the orchestrator; battery green; deterministic
   path is the fallback.
6. **Delete the hand-coded narration** in `suggest()`/`recommend.py` piece by piece behind parity tests — the
   actual monolith reduction.

**Net:** the deterministic FACTS + ACTIONS stay (fast, correct). The deterministic NARRATION is replaced by
grounded model narration. New buyer intents are absorbed by the orchestrator + one-line capability
declarations — **not** new screenshots and new `if` branches. The treadmill stops.
