# Model A/B — FINAL verdict after 4 rounds (2026-07-08)

Rounds 1-2: byte-identical (the seven-layer mute, `bb4cd0a`). Round 3: first divergent prose
(`MODEL_AB_ROUND3_VERDICT_2026-07-08.md`). Round 4: role-split (planner pinned qwen3:14b, narrator
varies, models pre-warmed) — raw: `MODEL_AB_ROUND4_ROLESPLIT_RAW_2026-07-08.md`.

## Round 4 headline: the hardware decided, not the prose

gemma3/phi4 failed 4/6 flows at a CONSTANT ~26s (the `LLM_PLANNER_TIMEOUT_SEC=25` ceiling) while
qwen3 passed 6/6. Not cold-load (warmed). **12GB VRAM cannot co-resident the pinned qwen3:14b
planner + a different 12-14B narrator** — Ollama swap-thrashes weights on every alternating call
(10-30s per swap) → planner times out → platform hiccup fallback. The qwen3 backend never swaps
(planner = narrator = same weights).

**Generalized: model certification must certify the DEPLOYMENT CONFIG (the resident set of models
on the target hardware), not each model in isolation.** Two individually-certified models can be
jointly uncertifiable. The model descriptor needs `resident_footprint_gb` and the cert harness
needs a co-residency check. (This is a BYO-onboarding profiler requirement, discovered live.)

## What the completed round-4 flows still showed

- **phi4 invented a product AGAIN**: "Dell UltraSharp U2723QE 27" 4K Monitor ($399)" — off-catalog,
  with an invented PRICE this time (round 3: "U2720Q"). Two fabricated SKUs in two rounds.
- **gemma3 best prose where it ran**: spec_deep "out of memory errors" framing was the most concrete
  and honest 8-vs-16GB answer of any round. Mild flaw: invented a comparative claim ("HP's build
  quality will likely be more dependable").
- **qwen3 flaws are stable and nameable**: agreeable oversell on fit ("8GB ideal for fine-tuning");
  fabricates "many retailers offer payment plans." Both are fixed by grounding (KB floor truth RK1 +
  capability registry), not by model swap.

## FINAL MODEL DECISION

| Role | Model | Why |
|---|---|---|
| **Default (all roles)** | **qwen3:14b** | Only config that runs the full pipeline on 12GB with zero breakage across 15 flows over 2 rounds; no invented products ever; flaws are grounding-fixable. |
| **Challenger config (later, via cert harness)** | gemma3:12b ALL roles (not split) | Most honest narrator; round-3 all-roles run completed 8/9 warm. Single-resident so it fits. Test as a config when cert harness productizes. |
| **Small-planner split (future)** | granite4:micro planner (~2GB) + large narrator | The only viable split on 12GB. granite is CUT as narrator (hallucinations) but structured planning is schema-validated — a legitimate role for a small model. Untested; needs a cert round. |
| **CUT** | phi4 (invented SKUs ×2 — worst possible commerce failure), granite4:micro as narrator | Fabrication with confident detail. |

**A/B testing is CLOSED.** Further rounds are diminishing returns: the constraint is hardware
co-residency and grounding gaps, both platform work, not model choice. This is the Phase-A exit.

## Roadmap impact (assessed per the user's directive)

Order UNCHANGED — evidence strengthened it:
1. **B1 capability registry** — payment-plan fabrication survived every model and every round; it is
   a missing-fact problem. (In progress.)
2. **B2 guard scope fix + ON** — phi4's twice-invented SKUs are the live exhibit for why the guard
   must exist; layer-7 scope bug is why it can't ship as-is.
3. **B3 model descriptors** — now ALSO carries `resident_footprint_gb` + co-residency (round-4's
   discovery), beyond the timeout/think fields (seven-layer lesson).
4. **B4 async draft-then-refine narration** — qwen3 warm latencies 11-20s on narration flows:
   too slow for blocking, perfect for replace-in-place.
