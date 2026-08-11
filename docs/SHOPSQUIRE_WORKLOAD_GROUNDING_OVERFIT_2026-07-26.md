# ShopSquire — BYO Model, Evidence Scatter-Gather, External Search & the Game-Overfit Fix (2026-07-26)

Answers: how does the BYO model decompose + scatter-gather evidence, how does external search
trigger, WHY is the platform overfit to Cyberpunk/Valorant, and how to generalize to any demanding
game (ray-tracing aware) and to professional resource-heavy workloads (UE5, CAD, rendering, AI).

---

## 0. TL;DR — the overfit is a DATA + GATING problem, not a design flaw

The architecture is already the right one: **the model classifies intent; a connector supplies real
requirements as citable evidence.** The model does NOT need to memorize game specs. But three things
make it *behave* overfit:

1. **Only 9 games are fixtured** ([steam_fixtures.json]): Cyberpunk, Fortnite, Valorant, BG3, CS2,
   Elden Ring, LoL, Minecraft, Warzone. **None** of your demanding list (Alan Wake 2, Black Myth,
   STALKER 2, Space Marine 2, Flight Sim, Avatar, Forspoken, Path of Exile).
2. **The live Steam lane is built but never triggered.** `get_game_requirements` is called
   fixture-only at [recommend_workload_stage.py:171](../src/app/services/recommend_workload_stage.py#L171)
   — no `allow_live=True`. So a non-fixtured game gets NO real requirements; it falls back to the flat
   generic `gaming` floor (`gpu_tier=discrete, ram_min=16`) which cannot tell path-traced Cyberpunk-4K
   from Minecraft.
3. **The requirement schema is too flat** — `minimum`/`recommended` × {ram, gpu, storage, os}. There is
   **no ray-tracing dimension and no resolution/fps tier**, so "Cyberpunk *with ray tracing* at 1440p"
   cannot map to its true (much higher) VRAM floor.

Fix = expand fixtures + **turn the live lane on** + **add the RT/resolution tier to the schema** +
add professional-workload profiles. All four fit the existing pattern; none is a rewrite.

---

## 1. How the BYO model works (and why it doesn't memorize games)

**Model resolution** ([turn_router.py:21-22](../src/app/services/recommendation_core/turn_router.py#L21)):
`ROUTER_MODEL → CLASSIFIER_MODEL → certified text default`. Any model that can emit the bounded JSON
schema works — the clamps make it **model-agnostic** (a weak/foreign/small model cannot break the
system because breaking it is not in the output space).

**The division of labor that makes BYO viable:**
- **Model's job:** map unbounded language → a *bounded schema* — lane, taxonomy handle, requirements,
  and a **workload/game intent** ("play Cyberpunk with ray tracing" → gaming-workload + game slug +
  graphics options). Interpretation only.
- **Connector's job:** supply the *actual* requirement numbers as citable evidence (Steam min/rec →
  desktop→laptop-tier translation → VRAM floor).

This is precisely why a **small** BYO model stays accurate on games it never memorized: it classifies
the intent; the connector grounds the numbers. Specs change every patch — a model that memorized them
would be wrong within weeks; an evidence lookup is always current. **The de-overfit fix and the
small-model latency lever (prev doc) are the same bet: intelligence in classification + evidence,
not in parameters.**

---

## 2. How decompose + scatter-gather works

```
query → query_decomposer.decompose()            → plan {needs_market_evidence, evidence_kinds, ...}
      → recommend_workload_stage (the workload brain):
            • detect games        → ctx["games"]        (slugs)
            • detect software/AI  → ctx["sw_reqs"]      (regex: fine-tune / SD / 7b|13b|70b / local LLM)
            • Steam requirements  → ctx["steam_reqs"]   (fixture-only today) + citable steam_note
            • merge floors        → fit verdicts (meets/unknown/fails), NOT retrieval filtering
      → evidence_orchestrator (N1 scatter-gather):
            plan-selected legs run in PARALLEL, bounded 2.5s, ADDITIVE:
            market · policy · availability · history · image · web
            → Evidence tab + source chips (message text untouched)
```

Key design choice ([recommend_workload_stage.py:160-161](../src/app/services/recommend_workload_stage.py#L160)):
**Steam enriches TRUTH (fit verdict + narration), it does NOT change retrieval** — the use-case KB owns
retrieval floors. So game requirements sharpen "does THIS laptop run it?" without distorting which
candidates are fetched. (Correct — but it means a too-low generic floor still lets weak laptops
*retrieve*; the fit verdict is where the game truth lands.)

---

## 3. How external search triggers (two separate mechanisms)

| Mechanism | Trigger | Gate | Status |
|---|---|---|---|
| **Steam requirements** ([steam_requirements.py:278](../src/app/services/connectors/steam_requirements.py#L278)) | game detected in workload stage | fixture-first; live lane needs `allow_live=True` + `external_research_allowlist` (store.steampowered.com enrolled) | **fixture-only wired** — live never triggered |
| **General web research** ([evidence_orchestrator.py:75](../src/app/services/evidence_orchestrator.py#L75), [external_product_research_service.py:159](../src/app/services/external_product_research_service.py#L159)) | plan flags `needs_market_evidence` + web_consent | `EXTERNAL_RESEARCH_ENABLED` (off) | dark by default |

Both are governed (allowlist, consent, timeout, provenance). The Steam live lane is the *safer, more
structured* of the two — it hits ONE allowlisted domain and returns typed min/rec specs with a
`source_url`, versus open web search. **Turning the Steam live lane on is low-risk; it's a curated
connector, not open crawling.**

---

## 4. The overfit, precisely (file:line)

- **9 fixtures, flat fallback.** [use_case_kb.json] `gaming` = `gpu_tier: discrete, ram_min: 16,
  vram_min: null`. Every non-fixtured game collapses to this one floor. A 6GB laptop "meets" it — but
  fails Alan Wake 2 (needs RTX 2060 6GB *min*, RTX 4070 16GB path-traced). The platform looks smart on
  Cyberpunk/Valorant because they're *fixtured*, and undergeneralizes everything else.
- **Live lane dormant.** [recommend_workload_stage.py:171](../src/app/services/recommend_workload_stage.py#L171)
  `get_game_requirements(slug)` — no `allow_live`. The one line that would make ANY title real.
- **Schema can't express ray tracing.** Fixture/connector shape = `{minimum, recommended} ×
  {ram_gb, gpu, storage_gb, os}` ([steam_requirements.py:136-143](../src/app/services/connectors/steam_requirements.py#L136)).
  No RT flag, no resolution/fps tier. Real 2026 requirements are a **matrix** — e.g. Alan Wake 2:
  min RTX 2060 6GB → rec RTX 3060 8GB (1440p30) → ultra RTX 4070 12GB (4K60) → **RT** RTX 3070 8GB
  (1080p30 medium RT) → **path tracing** RTX 4070 16GB. The flat 2-tier shape drops the exact axis your
  buyers ask about.

---

## 5. Professional resource-heavy workloads — what exists vs missing

use_case_kb has **11** profiles. Relevant:
- ✅ `ai_ml_workstation` (`discrete_8gb`, vram 8, ram 32) — AI/fine-tuning partly covered; detection is
  regex ([recommend_workload_stage.py:140](../src/app/services/recommend_workload_stage.py#L140):
  fine-tune / stable diffusion / 7b|13b|70b / local LLM).
- ✅ `game_development` (`discrete_6gb`, ram 16), `engineering_student` (`discrete_6gb`, ram 16),
  `creative` (ram 16, no gpu floor).
- ❌ **Missing / too-flat for pro tiers:**
  - **Unreal Engine 5** (Nanite/Lumen): realistically 8-12GB VRAM + 32-64GB RAM — `game_development`'s
    6GB floor undersells it.
  - **Video rendering** (Blender/DaVinci/Premiere): VRAM + CUDA/OptiX + high RAM; `creative` has no GPU
    floor at all.
  - **CAD/engineering** (SolidWorks/AutoCAD/Revit): often certified pro GPUs + specific VRAM;
    `engineering_student` is a student floor, not a pro one.

These are the *high-margin, high-ticket* buyers (a $4k mobile workstation vs a $1.2k laptop) — the exact
segment where getting the floor right justifies the price and the platform's advice.

---

## 6. Roadmap — prioritized, with why

| # | Item | Why | Cost | Files |
|---|---|---|---|---|
| **1** | **Turn on the live Steam lane** (pass `allow_live=` gated by consent + `EXTERNAL_RESEARCH_ENABLED` + allowlist) | The single highest-leverage de-overfit: ANY game → real requirements on-demand. Connector already built. | **S** | [recommend_workload_stage.py:171](../src/app/services/recommend_workload_stage.py#L171) + a consent check |
| **2** | **Expand fixtures** with the demanding list (offline, CI-safe fallback) | Fast, deterministic, no-network coverage for the headline titles; live lane covers the tail | **S (data)** | [steam_fixtures.json] |
| **3** | **Add RT + resolution/fps tier to the requirement schema** | The axis buyers actually ask about ("with ray tracing"); lets a 16GB vs 8GB verdict be correct | **M** (schema + fit-layer + narration) | steam schema, [gpu_translation.json], [workload_fit.py] |
| **4** | **Add pro-workload profiles**: `unreal_engine_5`, `video_rendering`, `cad_engineering` (real VRAM/RAM/CPU floors + citable basis) | Captures the high-ticket professional segment honestly | **M (data)** | [use_case_kb.json] + detection |
| **5** | **Move game/workload detection regex → model classification** | Removes the hardcoded-title dependency entirely; the doctrine ("model proposes closed-vocab, evidence grounds") | **M** | [recommend_workload_stage.py:140-171](../src/app/services/recommend_workload_stage.py#L140), turn_router schema |

**Sequencing:** 1+2 together kill the visible overfit fast (turn the lane on, seed the tail offline).
3 is the modeling upgrade that makes ray-tracing advice correct — the differentiated capability. 4
opens the professional segment. 5 is the doctrinal endpoint (no title list at all).

**Honesty guardrails (unchanged doctrine):** unknown requirement ⇒ `unknown` fit verdict, never a
guessed pass; every requirement number carries its `source_url`/citation; desktop GPU strings always
pass through `gpu_translation` before being compared to laptop parts.

---

## 7. Why this matters (strategic)

- **It removes the single most obvious "demo-rigged" criticism.** A sharp viewer asks "does it only
  know Cyberpunk?" Today: effectively yes. After 1+2: "it looks up any title's real publisher specs,
  live, with a citation." That's the difference between a scripted demo and a system.
- **It's the BYO-model payoff made concrete.** You don't need a bigger model to know more games — you
  need the connector on. Small model + live evidence > big model + stale memorization. Directly
  compounds the router-latency lever.
- **It reaches the buyers who pay.** Path-traced-game buyers, UE5 devs, CAD engineers, video editors and
  AI tinkerers all shop by *capability they can't easily self-assess* — exactly where governed,
  cited, requirement-grounded advice is worth money. Overfitting to two esports titles leaves that
  segment unserved.
- **Ray-tracing awareness is a moat.** No mainstream shopping assistant maps "Cyberpunk with path
  tracing at 1440p" to "you need ≥12GB VRAM, here are the three in-catalog laptops that clear it, cited
  to the publisher." That specific, defensible answer is the product.

*No code changed in this assessment.*
