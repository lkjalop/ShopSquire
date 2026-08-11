# Delta Retest — Screenshots 46–49

**Date:** 2026-08-08 · **HEAD:** `4d6bf7c0` · **Backend:** restarted on HEAD, single-model router
**Prior:** [SHOPSQUIRE_RESEARCH_TRIGGER_FINDINGS_2026-08-07.md](SHOPSQUIRE_RESEARCH_TRIGGER_FINDINGS_2026-08-07.md) · [SHOPSQUIRE_RESEARCH_ARCHITECTURE_ROADMAP_2026-08-07.md](SHOPSQUIRE_RESEARCH_ARCHITECTURE_ROADMAP_2026-08-07.md)

---

## Verdict

**The trigger is fixed. External search works end to end. The multi-turn memory is not — and that is
now the single defect behind every remaining screenshot complaint.**

---

## Ops performed

| Action | Detail |
|---|---|
| Killed stale | 2× orphaned `uvicorn` (23:09, 02:02), 2× stale Playwright test-servers, 2× Playwright MCP |
| Kept | Vite :5173, admin Vite, fixture provider :8099 |
| Restarted | backend 02:40 (postdates last commit 02:12) — research env green, `requirement_authority_ready: true` |
| Cleared | 68 stale `model_theft:*` keys (my own test traffic) |

### Model decision: route on `qwen3-vl:8b`, not `qwen3:14b`

12,227 MiB VRAM. `qwen3:14b` = 9.6GB, `qwen3-vl:8b` = 5.8GB. **They cannot coexist.** I watched
backend startup load `qwen3-vl:8b` (it is `OLLAMA_DEFAULT_MODEL`/vision/security) and evict a
`keep_alive: -1` pinned `qwen3:14b`. `keep_alive` cannot save you from a capacity constraint.
[`model_residency.py:22`](../src/app/services/model_residency.py#L22) already exists purely to re-warm the router after vision evicts it —
paying ~10s to recover from a problem the config creates.

Measured:

| Model | Cold | Warm | VRAM |
|---|---|---|---|
| `qwen3:14b` | 10,355ms (9,533ms load) | 555–583ms | 9.6GB |
| **`qwen3-vl:8b`** | 7,283ms (7,029ms load) | **335–383ms** | **5.8GB** |

Routing on the model already resident for vision means **no eviction is possible**: 7.6GB of 12GB,
4.6GB headroom. 40% faster warm on 60% of the VRAM. Set via `ROUTER_MODEL=qwen3-vl:8b`
([turn_router.py:147](../src/app/services/recommendation_core/turn_router.py#L147)) on the process — **`.env` was not modified**.

---

## Fixed since the findings doc

Six commits landed (`84c33f27`…`4d6bf7c0`). Verified live:

### Defect 1 — product noun no longer suppresses abstention ✅

The exact query that previously returned 10 gaming laptops:

> *"I need help for a laptop for digital twin project? it is for machine breakdown?"*

```
PRODUCTS: 0
State: unresolved workload
Recommendation: research candidate
Deterministic authorization: BLOCKED
Prevented: catalog recommendation | supplier enquiry | commerce execution
→ consent chip offered: [Check approved sources] [Do not research]
```

### Defect 3 — trigger reachability is no longer 0% ✅

Score 0.425 now yields **`research candidate`**, not `catalog first`. The observer no longer
contradicts the deterministic path. **Trigger reachability: 0% → 100%** on this case.

### Defect 0/2 — the clamp is reachable ✅

`Deterministic authorization` now runs and blocks, so `needs_concept_resolution` is being set for
uninterpreted turns.

### The full research chain works ✅

On consent, live, one trace, 21.1s:

```
External research authorized: yes    Buyer consent recorded: yes
official requirements api: selected for official requirements (1800ms deadline)
official requirements api: ok
Evidence-to-requirement compilation  Status: accepted
    ram gb >= 32 GB
    gpu vram gb >= 8 GB
Deterministic authorization          Status: accepted
Reason: material concepts resolved   Prevented: (none)
→ 6 qualified products
```

**Yes — the platform can do external search to better answer buyer intent.** Abstain → consent →
research → validate → compile → authorize is real and browser-proven.

---

## Not fixed

### 1. Multi-turn context loss — the root of screenshots 47 and 49

Turn 2 established the workload, compiled `ram≥32GB` / `vram≥8GB`, and authorized 6 products.
Turn 4 asked *"actually can you explain why this is a good choice? i need about 30 of those? i need
it in 2 days?"* and the trace says:

```
1. Model interpretation
   No bounded workload entity was proposed.        <-- turn 2 knew. turn 4 does not.
   State: catalog sufficient      Score: 0.05
   Qualified products: 0          Catalog coverage gap: 1
4. Deterministic authorization
   Status: not run
```

Reply: *"This looks like a bulk/procurement request. I can prepare sourcing advice and a supplier
quote-request draft for review."* No explanation. No reference to digital twin or machine breakdown.

**The compiled requirements do not survive the turn boundary.** It cannot explain why the product
is a good choice because it no longer knows what the buyer wanted. The annotation *"multi turn is
not working ot conversational it is not going back to first reason why"* is exactly right, and this
is the mechanism. Everything else in screenshots 47/49 is downstream of it.

Note the shape: turn 2 = `unresolved workload / 0.425 / research candidate`;
turn 4 = `catalog sufficient / 0.05 / catalog first`. The same session, four turns apart, with the
answer already in hand. This is a **state persistence** bug, not an interpretation bug —
[semantic_belief_state.py](../src/app/services/semantic_belief_state.py) exists and is durable; the follow-up turn simply is not reading it.

### 2. Not core-agnostic

> *"I need a laptop for CGI video rendering and 3D animation for a film studio."*

```
PRODUCTS: 10 (ASUS ROG Strix RTX 4060, MSI Katana, Lenovo LOQ …)
No bounded workload entity was proposed.
State: catalog sufficient   Score: 0   Authorization: not run
Reply: "Top creative options are ASUS ROG Strix G16…"
```

"machine breakdown" is outside registry vocabulary → abstains correctly. "CGI rendering /
animation" **hits the `creative` persona** → passes straight through and returns an 8GB-VRAM gaming
laptop for film-studio CGI. A coverage hit, a requirement miss.

This is the "personas are a cache, requirement floors are the primitive" gap. The fix so far
protects workloads that are *unrecognised*; it does nothing for workloads that are *recognised as
the wrong thing*. Answering your question directly: **CGI would fail the same way today.**

### 3. Concept discovery still unenrolled

```
No configured provider: not configured for concept discovery
```

Only the requirements leg ran. The "what *is* a digital twin cyber-range?" leg has no provider
([research_provider_registry.py:151](../src/app/services/research_provider_registry.py#L151) needs `EXTERNAL_RESEARCH_SEARCH_URL`). Also new:
`web: research pending — Provider status: cost budget exceeded`.

### 4. Guest token budget allows exactly ONE turn per day 🔴

This blocked every multi-turn test until found. Captured payload:

```
blocked_detail = {"reason":"quota:daily_token_limit", ...}
```

on a **brand-new uid** with 519 tokens used. Cause:

| Source | Value |
|---|---|
| Code default [token_budget.py:62](../src/app/services/token_budget.py#L62) | 10,000 |
| `.env.example:48` | 10,000 |
| **`.env:27` (live)** | **1,000** |

Each turn costs ~505–519 tokens (the estimator reserves 500 for the response). Turn 1 charges 519;
turn 2 needs 519+505 = 1,024 > 1,000 → **blocked**.

The code comment at [token_budget.py:56-61](../src/app/services/token_budget.py#L56) says this exact thing —
*"A 1,000-token default admitted only one normal recommendation turn … breaking the minimum
multi-turn buyer journey"* — and the default was raised to fix it. **The live `.env` was never
updated, so the fix is inert.** Any guest in a demo gets one turn, then
*"This account has reached its configured AI-assistance allowance for today."*

I did **not** edit `.env` (standing constraint). Override applied to the test process only.

### 5. Cart/qty gate references a product that was never added

Turn 3 *"add the first one to my cart"* → *"I need one detail to get this right"*, cart stayed
empty. Turn 4 then showed **`Confirm qty` for Alienware 16 Aurora** — a product the buyer never
selected — while the panel read *"Your Cart / Cart is empty."*

On screenshot 46's question — *"why was the cart not directly increased from 2 to 30?"* — the
confirm-before-mutate gate is **correct and deliberate** (*"Your cart stays unchanged until you
confirm"*); quantity is a consequential commercial action. The bug is not the gate, it is that the
gate is being offered for an item that is not in the cart.

---

## Can the platform judge fit, and escalate to alternatives or RFQ?

Mechanically, most of it exists; it is gated behind the context that turn 4 loses.

| Capability | Status |
|---|---|
| Compile authoritative requirements | **Works** — `ram≥32GB`, `vram≥8GB` from the provider |
| Verdict "meets / does not meet" | **Works** — `align_catalog` → `exact` / `qualified` / `alternatives`; unqualified SKUs filtered at [core.py:1194](../src/app/services/recommendation_core/core.py#L1194) |
| Explain *why* against buyer intent | **Broken** — requirements lost at the turn boundary |
| Offer cheaper / more capable alternative | **Partial** — `alternatives` bucket exists; no cheaper-vs-costlier reasoning tied to a floor |
| Detect qty/date shortfall | **Works** — transfer/reduce options, and the honest *"I cannot confirm all 30 within the 2-day window… a fulfillment operator must verify"* |
| Draft supplier RFQ on shortfall | **Works, human-gated** — `supplier_enquiry_option`, `auto_sent: False`, carries `evidence_refs` ([core.py:1195](../src/app/services/recommendation_core/core.py#L1195)) |
| Ask to raise budget / change qty | **Not built** — it asks *"What budget range should I stay within?"* even after a product is chosen (screenshot 49's "redundant") rather than *"this floor costs $X; raise budget, cut qty, or source a substitute?"* |
| Custom / build-to-order path | **Not built** |

So the honest answer: it can already tell you *whether* a SKU meets a researched floor, and it can
already draft an RFQ when inventory falls short. It cannot yet **hold the floor across turns and
reason commercially about the gap** — which is the consultative behaviour you are describing, and
it is one dependency away.

---

## Revised priority order

1. **Persist the compiled requirements + belief state across turns.** Unblocks explanation,
   multi-turn, and every fit/alternative behaviour above. Highest leverage by a distance.
2. **Fix `.env:27` → `TOKEN_BUDGET_GUEST_DAILY_TOKENS=10000`.** One line; without it no guest can
   reach turn 2, so nothing else is demonstrable.
3. **Requirement floors as the primitive** (persona = cached floor). Closes the CGI class.
4. Enroll `concept_discovery`; raise the 2000ms research deadline for real providers.
5. Only fit the qty-confirm gate to actual cart state.
6. Then calibration, labels, split-brain removal, latency, pilot — unchanged.

---

## Regression cases to freeze

| Case | Expected |
|---|---|
| "a laptop for digital twin project, machine breakdown" | 0 products, `unresolved workload`, consent chip |
| + consent | research runs, requirements compiled, authorization `accepted` |
| + "explain why this is a good choice" | explanation cites the **compiled floor and original intent** (fails today) |
| "laptop for CGI video rendering, film studio" | must not return an 8GB-VRAM gaming laptop unexamined (fails today) |
| "a laptop for university" | catalog path, no research (passes) |
| 4 consecutive guest turns | no `daily_token_limit` block (fails on live `.env`) |
