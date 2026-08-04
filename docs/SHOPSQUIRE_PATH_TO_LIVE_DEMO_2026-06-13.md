# ShopSquire — Path to Live Demo: Roadmap & Readiness
**Date:** 2026-06-13  ·  **Goal:** a confident, honest LIVE demo that proves the bounded-autonomy thesis  ·  **Companion to:** [backlog](SHOPSQUIRE_BACKLOG_2026-06-11.md), [NQE/speed roadmap](SHOPSQUIRE_NQE_SPEED_PIPELINE_ROADMAP_2026-06-11.md)

> This answers two questions: **what to do next**, and **what's actually needed before you can stand up and demo this live.** It's organized as a critical path, not a wish list.

---

## 1. Where we are — readiness scorecard

| Dimension | Status | Note |
|---|---|---|
| Backend capability | ✅ Ready | decomposer, grounding ladder, security membrane, claim grounding — all wired |
| Quality / anti-hallucination | ✅ Ready | eval: grounding 100%, faithfulness proxy clean |
| Security membrane | ✅ Ready | eval: precision 100% / recall 100% / FP 0% |
| Proof artifacts | ✅ Ready | `eval/run_eval` scorecard + `demo_bounded_autonomy.py` |
| Decision trace (the hero) | ✅ Ready | renders every new agent event generically |
| **Speed (live)** | ⚠️ **Needs prewarm** | warm prose ~12s; **prewarm the demo queries → 0.5s** |
| **UI visibility** | ❌ **The one real gap** | storefront renders the answer + security badge + clarifying Q, but NOT the structured evidence (`breach_assessment`, `grounded_tier`, `recognized_product`) |
| **Data realism** | ⚠️ **Verify** | seeded catalog must look real (names/prices/specs) |
| **Environment repro** | ⚠️ **Verify** | full stack (8080 + 5173 + Ollama + PG + Redis) must come up clean |
| **Narrative / rehearsal** | ⚠️ **Draft → rehearse** | 3-act script exists; unhappy path not rehearsed |

**Bottom line:** capability and proof are done. The gaps are **presentation-grade**: visibility, speed-on-the-day, data realism, and rehearsal — not engineering depth.

---

## 2. The fork that decides your timeline

There are two viable demos. Choose deliberately — it changes the effort by ~10x.

### Option A — **Trace-driven demo (fast path, ~2–3 days)** ← recommended first
Make the **Decision Trace the hero**. It *already* renders every agent event (grounding ladder, breach assessment, query-plan filters, knowledge answer). The storefront already shows the answer, the "Image Security" badge, and the clarifying question. So you can demo a coherent story **today-ish** with only prewarm + rehearsal + data realism.
- **What the audience sees:** a great answer in the storefront → you open the trace → the multi-agent reasoning + security mapping + the grounding decision are all there.
- **Why it works:** for *assessing* the platform, the trace is the most convincing artifact. It proves "real engineering, not a wrapper."

### Option B — **UI-driven demo (polished path, ~1–2 weeks)**
Wire the storefront to render the structured evidence as panels (breach assessment, grounded-confidence badge, recognized product, knowledge answers). Richer, but it's frontend work that doesn't change *what's true* — only how pretty it looks.

**Recommendation: ship Option A for the first live demo.** Add Option B's panels only if the first demo says it's worth polishing.

---

## 3. Critical path to a confident live demo (Option A)

### Phase 0 — Make it runnable & real (½–1 day) — BLOCKING
- [ ] **Stack-up dry run:** `docker-compose up` (api, db, redis, workers) + frontend dev (`5173`) + Ollama, hit the storefront end-to-end. Fix anything that doesn't come up clean.
- [ ] **Data realism pass:** confirm the seeded catalog has real laptop names / believable prices / spec fields populated (the grounding ladder + prose quality depend on it). Re-seed if it looks synthetic.
- [ ] **Env for the day:** `OLLAMA_SUMMARY_MODEL=qwen3:14b`, `SEMANTIC_CACHE_MAX_DISTANCE=0.12`, `GROUNDING_LADDER_ENABLED=1`, `OWNER_API_KEY` set (+ `localStorage ss_owner_key`).

### Phase 1 — Make it snappy & reliable (½ day) — BLOCKING
- [ ] **Prewarm:** run `scripts/prewarm_demo_cache.py` for the EXACT demo queries → 0.5s on the day (kills the 12s spinner).
- [ ] **Warm Ollama once** before the audience arrives (first call pays a model-load tax).
- [ ] **Rehearse the unhappy path:** kill Ollama mid-query → confirm the deterministic fallback is graceful, not a stack trace.

### Phase 2 — Stage the story (½ day) — BLOCKING
- [ ] Rehearse the **3-act script** (§5) end-to-end, twice.
- [ ] Prep the **two proof slides:** the eval scorecard (`python -m eval.run_eval`) and the autonomy dial (`python scripts/demo_bounded_autonomy.py`).
- [ ] Pre-load the **skeptic answers** (§6).

### Phase 3 — Quick wins if time allows (P1, non-blocking)
- [ ] Tighten the `identity_abuse` regex ("elevate **my** privileges"). *(XS)*
- [ ] Install `sentence-transformers` + `faiss-cpu`, build the visual index → product-line grounding goes live. *(S)*
- [ ] LLM-judge faithfulness in the eval (`--live` deeper) → put a *judged* 0.9 on the slide. *(M)*

---

## 4. Pre-demo go/no-go checklist (the literal "what else is needed")

**Must be green to go live:**
- [ ] Full stack comes up clean and a storefront query returns products + an answer.
- [ ] Catalog looks real (no obviously-synthetic names/prices).
- [ ] Demo queries are prewarmed (sub-second) and Ollama is warm.
- [ ] The compromised-image scenario returns products + the security badge + escalation (warn-and-continue, not a deny).
- [ ] The ungrounded-brand scenario asks "Is this a Razer?" (the boundary moment).
- [ ] The decision trace opens and shows the agent chain + security mapping.
- [ ] `python -m eval.run_eval` prints the scorecard; `demo_bounded_autonomy.py` prints the dial.
- [ ] Unhappy path (Ollama down) degrades gracefully.

**Nice-to-have (won't block):** frontend evidence panels (Option B), streaming UI, judged faithfulness number.

---

## 5. The 3-act demo script (exact inputs → what to point at)

**Persona:** "a mid-market electronics marketplace."

**Act 1 — Smart shopping (the agent is competent).**
- Type: *"what's good for gaming, 1500–1900? why?"* → cards in ~1.7s, a real "why" answer.
- Type: *"is $1500 enough for a good gaming laptop?"* → leads with **YES/NO** + reason.
- *Talking point:* "answers the question, not a search dump."

**Act 2 — Under fire (the thesis).**
- Upload the **MSI-with-QR** image + ask the gaming question → **still recommends**, shows the security badge, asks nothing it can't ground.
- Upload a photo whose brand isn't in catalog → it **asks "Is this a Razer?"** instead of inventing one.
- *Talking point:* "it keeps flying under fire — and it asks a human exactly when the evidence runs out."

**Act 3 — The trace (proof it's real).**
- Open the **Decision Trace** on the Act-2 turn → show the agent chain, the **grounding ladder** decision, the **breach assessment** (MITRE/OWASP + IP/ASN scored), the residual.
- Cut to the **eval scorecard** + **autonomy dial** slides.
- *Talking point:* "this is measured, not asserted — and here's every agent that fired."

---

## 6. Risk register (live failure modes → mitigation)
| Risk | Mitigation |
|---|---|
| Ollama stalls / 12s spinner | Prewarm exact queries (0.5s); warm model first; deterministic fallback rehearsed |
| "Isn't this a GPT wrapper?" | Open the decision trace — multi-agent + framework mapping |
| "How do you know detection works?" | `eval/run_eval`: precision 100% / recall 100% / FP 0% |
| "What about hallucination?" | The grounding ladder + the fence; show the "Is this a Razer?" refusal-to-invent |
| Synthetic-looking data undermines trust | Phase-0 data realism pass |
| A backend route 500s live | Stack-up dry run + the unhappy-path rehearsal |
| Latency anchoring ("12s is slow") | "local inference for the demo; production streams <2s" |

---

## 7. After the demo (only if it validates)

**Phase A — Polish (the showcase got traction):** Option B frontend panels · streaming UI · judged faithfulness · CLIP index live.

**Phase B — Breadth (a buyer wants a specific surface):** supplier verification (3rd grounding surface) · email-membrane / BEC demo · A2A trust gateway.

**Phase C — Scale (someone's paying):** hosted inference (vLLM/TGI) · monolith → stage extraction (V2 pipeline) · multi-tenant isolation audit · SLOs + CI eval gate.

*Do not start Phase B/C until the demo says the thesis lands. That's the whole point of demoing first.*

---

## TL;DR
- **You are ~2–3 days from a credible live demo** via the trace-driven path (Option A).
- **The only true gaps are presentation-grade:** runnable stack, real-looking data, prewarmed speed, a rehearsed script — not engineering.
- **Don't build more backend** before the demo. The eval already proves it works; the demo is now about *showing* it.
