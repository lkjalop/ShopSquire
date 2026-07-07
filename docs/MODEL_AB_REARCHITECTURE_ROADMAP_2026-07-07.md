# Model A/B → Answer taxonomy → Re-architecture roadmap

**Date:** 2026-07-07 · **Context:** the "platform is dumb" thread resolved to a **model-capability + architecture**
problem, not more deterministic rules. Plan: (1) A/B three new local brains, (2) define what a *good* answer is,
(3) re-architecture to agentic-RAG (fast regex lane + capable-model orchestrator + sources-as-tools).

**Models under test (you are pulling these):** `granite4:micro` · `gemma3:12b` · `phi4` · baseline `qwen3:14b`.
Harness: `scripts/model_ab_harness.py` (built, runnable; auto-skips un-pulled models).

---

## PHASE 0 — Extensive A/B (this is the roadmap you asked for)

### 0.1 What we're actually deciding
Two separate questions the A/B must answer, because they need different tools:
- **Q1 — Reasoning/knowledge:** does the model *know* a laptop is a poor fit for LLM training (24GB ceiling,
  48GB+/cloud for real training)? → tests RAW model capability. (Ollama-direct, no platform.)
- **Q2 — Grounded orchestration:** given the catalog facts + KB floors, does it synthesize an **honest**
  answer without hallucinating inventory, and does it correctly *plan which sources it needs*? → tests the
  Lane-2 orchestrator role.

### 0.2 The test matrix
**Models (rows):** granite4:micro, gemma3:12b, phi4, qwen3:14b (control).
**Cases (cols), two suites:**

**Suite A — Raw domain reasoning (no grounding).** The decisive "is the model the bottleneck" test:
1. `llm_train_hard` — "laptop for training LLM models, $3,500 budget?" → must say a laptop is marginal; name the 24GB ceiling / cloud.
2. `vram_knowledge` — "how much GPU memory to fine-tune vs fully train a 7B?" → correct tiers (QLoRA ~8GB, full ~60-80GB).
3. `category_mismatch` — "best laptop for hosting a production database 24/7?" → should say a server, not a laptop.
4. `honest_upsell` — "is a $400 laptop good for 4K video editing?" → honest no, name the gap.
5. `overreach` — "cheapest laptop that runs Cyberpunk max settings 4K?" → honest about the floor.

**Suite B — Grounded orchestration (facts in the prompt).** Tests synthesis + honesty + planning:
6. `grounded_fit` — same LLM-train query + the catalog rows (8GB/$3499, 16GB/$4499, 24GB/$5999) + KB floors →
   must recommend within reality, name the gap, offer the step-up, not oversell the 8GB.
7. `grounded_challenge` — "are you sure that's good for training?" + the prior pick's specs → defend or concede
   with named gaps.
8. `grounded_compound` — "15 work laptops under $1400 and a monitor" → decompose; identify it needs
   inventory + budget + a second search.
9. `grounded_policy` — "what's your return policy and is $2k enough for gaming?" → route policy to the FAQ
   fact, product half to a fit verdict; don't blend.
10. `tool_planning` — "which of these is cheapest that meets the ML floor, and is that price competitive?" →
    should recognize it needs (a) catalog/KB filter AND (b) external/market data — the scatter-gather plan.

### 0.3 Scoring rubric (per answer)
Auto-scored heuristics + human final call. Dimensions (0-3 each):
- **Correctness** — factually right about hardware/fit/tiers.
- **Honesty** — admits gaps; says "not a laptop job" / "over budget" when true; no overselling.
- **Grounding** (Suite B) — uses ONLY the provided rows/prices; zero hallucinated inventory.
- **Reasoning** — connects requirement → hardware → recommendation (not a keyword echo).
- **Planning** (Suite B, case 8/10) — correctly names WHICH sources it needs.
- **Concision** — helpful, not robotic, not rambling (target ≤120 words).
- **Latency** — wall-clock per answer (measured).
Harness auto-flags: mentions-VRAM-ceiling, mentions-cloud/desktop-alternative, hallucinated-price (regex a
$ not in the provided set), length. Human scores Correctness/Honesty/Reasoning from the side-by-side.

### 0.4 How to run (when pulls finish)
```bash
# confirm the models are present
ollama list
# run the full matrix (auto-skips any not yet pulled); writes a side-by-side report + JSON
python -m scripts.model_ab_harness
# outputs: scratchpad/model_ab_report.md  (read this) + model_ab_results.json
```
Optional platform-integrated pass (Q2 end-to-end): for each model, `set MULTI_INTENT_LLM_MODEL=<m>` +
`OLLAMA_SMALL_MODEL=<m>`, restart backend, POST the 5 grounded queries to `/chat/query`, diff the narrations.
(The direct harness is the decisive first cut; do the integrated pass only for the 1-2 finalists.)

### 0.5 Decision gate out of Phase 0
- **If a local model (likely phi4 or granite4) clears Suite A honestly** → Lane-2 brain can be LOCAL for the
  medium tier; reserve a frontier API only for the hardest orchestration.
- **If none do** → the hard tier needs a **frontier API** (Claude Haiku/Sonnet); local stays fast-lane +
  simple tier. Either way we now KNOW, instead of guessing.

---

## PHASE 1 — Define "what a good answer is" (the target the models are judged against)

The answer taxonomy — each query class + its ideal answer shape. This is the contract the re-architecture builds to.

| Query class | Ideal answer shape | Lane |
|---|---|---|
| Simple search ("gaming laptop <$2000") | ranked results, one-line why, no ceremony | 1 (fast) |
| Budget-fit ("is $1800 enough for gaming?") | direct yes/no + why + best pick | 2 |
| Hard-requirement use case ("LLM training $3500") | honest fit: what budget gets, what the need really wants, the GAP, and "maybe not a laptop" when true; offer the step-up + off-catalog truth | 2 |
| Challenge ("are you sure?") | defend-or-concede vs the KB floors, gaps NAMED | 2 |
| Compound/multi-intent | decompose, handle each, confirm qty/budget | 2 |
| Knowledge ("what VRAM to train?") | domain knowledge (model's own), grounded, honest | 2 |
| Volatile fact ("is this price competitive today?") | external/market data + citation | 2 + tool |
| Off-domain / policy / support | route correctly, never hallucinate products | 1 or FAQ |
| Category mismatch / honest-broker | soft-reject + reframe to achievable + next-best + off-catalog | 2 |

**Principle:** "fits the use case" == meets the KB `required_specs`, said **once**, everywhere (ranking, narration,
challenge, alternatives). The model narrates; the platform grounds; the policy gate authorizes.

---

## PHASE 2 — Re-architecture (agentic-RAG, three lanes)

The target that STRIPS `suggest()`/`recommend.py` instead of growing them.

```
LANE 1  FAST (regex/deterministic)  — greeting/off-domain/cart/simple lookup, <100ms, no model.
                                       The ONLY place deterministic rules grow.
LANE 2  ORCHESTRATOR (capable model + tool-use) — reads intent → PLANS which sources → platform executes
                                       bounded tools → model SYNTHESIZES an honest, grounded answer.
LANE 3  SOURCES AS TOOLS  — catalog DB · pgvector · graph · inventory · policy · conversation memory ·
                                       external search (volatile only). Each = a bounded, tested, permissioned fn.
```

### What maps to what (we already have most of the substrate)
- **Scatter-gather substrate** = the R2 evidence orchestrator (`evidence_orchestrator.py`). Legs → become TOOLS.
- **`select_legs` (deterministic today)** → becomes the **model's job** (function-calling picks the tools).
- **Narration (hand-coded: `_deterministic_assistant_message`, capability_verdicts, honest-broker templates)**
  → becomes the **model's job**, grounded on tool outputs. ← this is the big deletion.
- **Guardrail/policy gate** → unchanged: model PROPOSES tool calls + answer, deterministic code AUTHORIZES,
  trace records (same bounded-autonomy spine as pricing/refunds).
- **KB `required_specs` + ranking floors (RK1)** → still needed, but as **grounding fed to the model**, not
  as narration logic.

### Migration phases (each flag-gated, reversible, parallel to the current path)
- **2a — Tool interface:** wrap the existing sources as callable tools with JSON schemas (catalog_search,
  kb_requirements, inventory_check, policy_answer, purchase_history, market_evidence, web_research). Most are
  the R2 leg fns + retrieval — expose, don't rebuild. (No behavior change; new surface.)
- **2b — Orchestrator loop:** the Lane-2 model plans → we execute tools → model synthesizes. Flag
  `ORCHESTRATOR_LANE_ENABLED` default OFF. Runs SIDE-BY-SIDE with the deterministic path (shadow/compare).
- **2c — Route the hard tier to Lane 2:** high-complexity-score queries go to the orchestrator; battery must
  stay green; the deterministic path remains the fallback.
- **2d — Strip the redundant deterministic narration** from `suggest()`/`recommend.py` once Lane 2 covers it
  — the actual monolith reduction. Each deletion behind a passing parity test.

### Risks (carried from the earlier reassessment)
- Tool-calling reliability degrades with model size → the A/B decides local-vs-API for Lane 2.
- Tool-use is a guardrail surface → each tool bounded + policy gate in front (we have the pattern).
- Privacy if Lane 2 is a frontier API → scrub PII before send (privacy.py machinery exists).
- Latency → frontier API is often FASTER than local 14B; local stays the fallback.

---

## Sequencing (the whole thing)
1. **Phase 0 A/B** (harness ready) → pick the Lane-2 brain. ← next, when pulls finish.
2. **Phase 1** answer taxonomy → freeze the contract (mostly written above).
3. **RK1** (KB-floor grounding correctness) → so whichever brain is fed TRUE fit facts. Small, do alongside.
4. **Phase 2a→2d** re-architecture, flag-gated, parallel, parity-tested — the real work, post-demo.
5. **Deferred:** Option C (in-process suggest_core), external search rescoped to volatile facts, RK4 fit-source unification.

Everything here is reversible and shadow-able. Nothing forces a big-bang rewrite — the orchestrator lane runs
beside the deterministic one until it's provably better, then the deterministic narration is deleted piece by piece.
