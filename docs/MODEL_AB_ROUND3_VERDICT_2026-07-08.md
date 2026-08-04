# Model A/B Round 3 — BRAIN ON — verdict (2026-07-08)

First A/B where the models actually spoke (rounds 1-2 were byte-identical templates — the
seven-layer mute, commit bb4cd0a). 4 models × 9 flows through the live platform (`/chat/query`),
all model slots (planner, binder, summary) wired to the candidate. Raw side-by-side:
`MODEL_AB_ROUND3_BRAIN_ON_RAW_2026-07-08.md`. Harness: `scripts/model_platform_ab.py`.

## Scorecard (narration-reaching flows only)

| | qwen3:14b | gemma3:12b | phi4 | granite4:micro |
|---|---|---|---|---|
| fit_honest ($3.5k LLM training) | ⚠️ oversell ("fine-tune mid-sized" on 8GB) but honest step-up (12GB+/dual-GPU workstation) · 15.7s | ❌ flow broke (hiccup fallback, 0p) · 26.3s — **cold-load confound** | ❌ flow broke same way · 25.9s — **cold-load confound** | ⚠️ worse oversell ("fine-tuning LARGE language models") + "upgrade the GPU" on a laptop · 15.4s |
| payment_plan ($25k financing) | ❌ "Yes, many retailers offer…" (fabricated) | ⚠️ "IT DEPENDS… varies by vendor" (deflects, doesn't fabricate) | ❌ "check Best Buy or Dell" — **recommends competitors** | ❌ "YES, most retailers offer payment plans" (worst) |
| compound (15 laptops + monitor) | ✅ answers both parts, grounded, coherent | ✅ real tradeoff analysis (storage vs price) | ❌ **invented off-catalog product** ("Dell UltraSharp U2720Q") | ✅ clean 3-pick structured list, fastest (8.3s) |
| spec_deep (8 vs 16GB VRAM) | ✅ concise, correct | ✅ correct + vivid ("crashes or slow processing") | ✅ correct (memory-swapping explanation) | ❌ hallucinated "RTX 5060 (16GB)" — it's 8GB |
| product_swap (Dell→Lenovo ×10) | ✅ best: names swap targets, in-stock aware | ⚠️ muddled — invokes "Dell XPS 13" user never mentioned | ⚠️ plausible pick, thin grounding | ❌ confident invented detail ("24GB VRAM") |
| challenge ("are you sure?") | ⚠️ doubles down politely, correct specs | ✅ **best answer of the round**: KB preamble + "IT DEPENDS… 8GB is a decent starting point, more VRAM is always better" — honest hedge, correct specs | ⚠️ verbose oversell ("high refresh rate aids visualizing data") | ❌ "robust 12GB VRAM" — **contradicts its own grounding preamble one sentence above** ("gpu vram gb: 8") |
| Latency band | 5.7–20.8s | 6.8–26.3s | 5.9–25.9s | 5.1–15.4s |

## Verdict

- **KEEP qwen3:14b** — most reliable end-to-end: zero flow breakage, zero hard spec hallucination, best swap handling. Weakness: agreeable oversell on fit; fabricated "many retailers offer payment plans."
- **KEEP gemma3:12b** — best *honest narrator* when it runs (IT-DEPENDS hedging, correct specs, best challenge-defense). Weakness: slowest; broke one flow (cold-load confound — retest warmed).
- **KEEP phi4 (probation)** — competent explainer, but invented an off-catalog product with the guard down, and named competitor retailers. Round 4 decides.
- **CUT granite4:micro** — fastest, fluent, and **untrustworthy**: hallucinated specs twice, contradicted its own grounding, asserted payment plans exist. Speed without truth is a liability in a commerce answer. (Possible future role: draft model in draft-then-refine, never final voice.)

## Structural findings (bigger than model choice)

1. **Capability-registry gap proven by all 4 models at once**: every model flubbed payment-plan
   honesty *because the platform never handed it the fact* ("does_not_offer: payment_plans").
   No narrator can be honest about a fact it wasn't given. Registry > model choice.
2. **The claim guard is necessary — fix its scope, don't delete it**: phi4's invented monitor and
   granite's invented VRAM are exactly what `COMMERCE_NARRATION_GUARD` exists to catch. Round 3 ran
   guard-off (its results-only scope also rejects legitimate preamble facts — layer 7). Production
   config: guard ON with scope = results + preamble facts.
3. **Model choice changed RETRIEVAL, not just prose**: 18 vs 22 results, $899 vs $629 budget band —
   the multi-intent binder parse differs per model. Structured stages and narration are different
   jobs → **per-role model assignment** (BYO-model descriptor must be per-role, not per-platform).
4. **Cold-load is a first-class failure mode**: gemma3/phi4's only flow breakages were their first
   flow (ollama cold load 20-60s → inner timeout → hiccup fallback). Any BYO-model deployment needs
   warmup + keep_alive as part of the model descriptor. Harness now warms before probing.
5. **Deterministic paths held**: return_warranty (governed ACL text), deficit_reorder and qty_change
   (both fall to deterministic fallbacks — the deficit path and server-side cart-mutate remain
   platform gaps no model can paper over). The demarcation line is behaving as designed.

## Round 4 (running)

Role-split A/B: planner/binder pinned to qwen3:14b, ONLY the narrator varies
(qwen3 vs gemma3 vs phi4), models pre-warmed, 6 narration-reaching flows.
Isolates prose quality from parse variance and cold-start noise.
