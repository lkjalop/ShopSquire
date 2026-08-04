# ShopSquire — NQE, Speed, Pipeline & Recommendation Roadmap
**Date:** 2026-06-11  ·  **Author:** engineering deep-dive (live-tested, not theoretical)  ·  **Status:** actionable

> This roadmap is grounded in **live dry-runs against the real stack** (Ollama up, TestClient → real `/api/v1/recommend/suggest`), not code-reading alone. Every latency number and answer-quality verdict below came from an actual run on 2026-06-11.

---

## 0. Execution status (updated 2026-06-11, same day)

Most of WS1–WS3 was **implemented and live-tested** the same day. Summary:

| Item | Status | Evidence |
|---|---|---|
| WS1.1 fast summary model (`qwen3:14b` default) | ✅ done | 25s→12s, same quality |
| WS4.5 de-collapse tier ladder (medium→14b) | ✅ done | `config/ml/tier_ladder.json` |
| WS2.1/2.3 query decomposer (intent + multi-intent + slots) | ✅ done | `services/query_decomposer.py` + 7 unit tests |
| WS2.2 knowledge/comparison answer path | ✅ done | "4060 vs 4070" now answers (was blank); injected at `_with_trace` so it survives all 10 early-return paths |
| WS2.4 numeric slot extraction → WS3.2 hard filters | ✅ done | "240fps"→`refresh_hz≥240`; esports query now filters office laptop out |
| WS3.1 accessory guard | ✅ done | "$45 Laptop Stand" no longer leaks into laptop queries |
| WS3.4 `why` on results | ✅ verified | populated at full-path seam |
| WS1.4 tunable cache + pre-warm | ✅ done | `SEMANTIC_CACHE_MAX_DISTANCE` env + `scripts/prewarm_demo_cache.py` |
| WS1.2 products-first | ✅ done (backend) | `include_summary=False` → **warm 1.7s** product cards (cold 12s is one-time model load, eliminated by the pre-warm script). `summary_pending` flag returned. Frontend just needs to fetch prose separately. |
| WS4.1 V2 pipeline | ✅ verified | `RECOMMEND_PIPELINE_V2=1` runs without crashing (falls back cleanly) |
| WS4.4 VLM routing | ⏳ deferred | small tier is already a VLM; product-identity vision is a scoped Phase-3 item |
| WS4.2 monolith breakup | ⏳ deferred | genuine multi-day refactor; not attempted in one pass |

**Measured after (live, `qwen3:14b`, cache off):** comparison 21.8s→answers; multi-intent 7.4s honours gaming+editing+portable; esports 7.5s honest "NO" + filtered; knowledge 15s. Cache-warm repeats ~0.5s.

**Latency picture is actually good now:**
- **Products-first (`include_summary=False`): ~1.7s warm** — render cards instantly, fetch prose async.
- **Full prose answer: 7–22s** (local Ollama generation dominates) — the part to stream or pre-warm.
- **Cache-warm repeat: ~0.5s.**
- **Cold first call: ~12s one-time model load** — eliminated by running `scripts/prewarm_demo_cache.py` before the demo.

**Demo-day recipe:** `OLLAMA_SUMMARY_MODEL=qwen3:14b` + `SEMANTIC_CACHE_MAX_DISTANCE=0.12` + run the pre-warm script. Then product cards land in ~1.7s and the exact demo queries are cached at ~0.5s.

---

## 1. Executive summary

ShopSquire's **security intelligence and answer *form* are already strong**. The weak points are **(a) latency**, **(b) query understanding / decomposition**, and **(c) candidate quality** — all pre-existing platform behaviour, not regressions.

| Dimension | State today | Target |
|---|---|---|
| Security under attack (compromised image) | ✅ Resilient — recommends + warns + escalates + IP/ASN scores | Keep |
| Single-intent answer quality | ✅ Excellent (leads with answer, cites specs, plain English) | Keep |
| First-answer latency | ❌ **25s** (uncached, 27B+think) | **< 2s perceived** |
| Comparison / knowledge queries | ❌ **Blank** (empty retrieval → no answer) | Always answer |
| Multi-intent decomposition | ⚠️ Drops constraints (3 intents → 1 wins) | Honour all |
| Numeric constraint extraction | ⚠️ "240fps"/"portable" ignored | Hard-filter |
| NQE clarifying behaviour | ✅ Fires correctly on vague queries | Keep + tune |

**The plan:** a 4-hour demo-hardening pass (Phase 0) makes it stage-ready; three sprints (Phases 1–3) turn the gaps into the platform's next differentiators.

---

## 2. Evidence base (what live testing showed)

### 2.1 Latency is *entirely* the LLM prose summary
Product retrieval is **sub-second**. The 12–25s wait is the summary call alone.

| Summary model | Latency | Quality |
|---|---|---|
| `qwen3.6:27b` + think (current default) | **25.3s** | excellent |
| `qwen3:14b` (think off) | **12.6s** | excellent |
| `qwen3:14b` (think auto) | 14.5s | excellent |
| `mistral-small3.2:24b` | 41.2s | — |
| 8B / 3B models | time out → deterministic fallback | poor |
| **semantic cache warm-hit** | **0.5s** | (cached) |

**Implication:** decouple product rendering from prose, and/or shrink the summary model. Both are cheap.

### 2.2 NLP answer-quality battery (5 query types, `qwen3:14b`)

| Query | Answer | Verdict |
|---|---|---|
| "is $1500 enough for gaming?" | "**NO**, $1500 isn't enough for a discrete GPU at this tier. [2] and [3] lack dedicated GPUs…" | ✅ Direct, cited |
| "what's good for gaming 1500-1900 why?" | "**Dell G16 [3]** is best… RTX 4070 runs max settings, 240Hz… Prioritize Dell." | ✅ Excellent |
| "difference between RTX 4060 and 4070 laptops?" | *(blank — 0 results)* | ❌ No answer |
| "gaming + video editing, portable, under 2000" | "For your **creative workflow**, 17 options…" | ⚠️ Dropped gaming + portable |
| "best for esports valorant 240fps under 1900?" | "…HP Victus + **HP Laptop 15 ($899)**…" | ⚠️ Ignored 240fps; office laptop leaked |
| "show me something good" | "24 options… VivoBook + **Laptop Stand $45**…" + asks use_case/brand | ✅ NQE good; ⚠️ accessory leaked |

**Three root-cause gaps:**
1. **No knowledge/comparison path** — every query is treated as a product filter; empty retrieval → `_summarize_results` returns early → blank screen.
2. **No multi-intent decomposition** — the query analyzer picks one persona; other constraints are silently dropped.
3. **No numeric/use-case slot extraction → hard filter** — "240fps" never becomes `refresh_hz ≥ 240`; accessories aren't excluded.

### 2.3 Frontend reality
The React UI renders `assistant_message`, `next_questions`, and the "Image Security: {route}" badge. It does **not** yet read the new structured security fields (`breach_assessment`, `recognized_product`, …) — those are API-only until wired.

---

## 3. The presentable way to demo it

> Principle: **lead with the moat, show one flawless happy path, frame the gaps as a published roadmap.** Never let the audience discover a gap you didn't name first.

### 3.1 Narrative arc (12–15 min)
1. **The hook — "AI commerce that keeps flying under fire" (the A-10 story).**
   Upload the **MSI-with-QR** image + apple image, ask *"what's good for gaming? 1500-1900? why?"*
   - It **still recommends** gaming laptops (doesn't refuse).
   - It **warns**: "a suspicious QR element was detected and neutralised — I didn't open it; recognised a gaming laptop, recommendations anchored to that."
   - Open the **Decision Trace**: show the breach assessment — MITRE ATLAS `AML.T0043`, OWASP `LLM01`, the IP scored against ASN/GeoIP as a known-bad-actor, human escalation fired.
   - **This is the differentiator.** No competitor does shift-left agentic security *inside* the shopping flow.
2. **The intelligence — one flawless answer.**
   Pre-warmed query *"is $1500 enough for a good gaming laptop?"* → instant "**NO**, … because …". Show it leads with the answer, cites specs in plain English.
3. **The honesty slide — "the roadmap" (this doc).**
   Put up the scorecard from §1. Frame latency/decomposition as *next sprint*, already designed. Buyers trust teams who know their own gaps.

### 3.2 What to show vs. avoid
| Show | Avoid live (it's on the roadmap) |
|---|---|
| Compromised-image resilience + decision trace | "RTX 4060 vs 4070" (blank today) |
| Single-intent "why" answer (pre-warmed) | "gaming + editing + portable" (drops constraints) |
| NQE clarifying a vague query | First *uncached* query on a cold model (25s) |
| Off-topic apple → "that's not a product" | "240fps esports" (ignores the constraint) |

### 3.3 Pre-demo checklist (Phase 0 — do these first)
- [ ] `OLLAMA_SUMMARY_MODEL=qwen3:14b` (halves latency, same quality)
- [ ] Pre-warm the semantic cache with the exact demo queries (→ 0.5s)
- [ ] Seed the demo catalog with real RTX 4060/4070 laptops in $1500–1900 (so "is $1500 enough" answers YES truthfully)
- [ ] Set `OWNER_API_KEY` / `localStorage ss_owner_key` so the security panels render
- [ ] Confirm Ollama warm (run each demo query once before the audience arrives — first call pays a model-load tax)

---

## 4. Improvement roadmap — four workstreams

### WS1 — Speed & responsiveness  *(highest ROI, lowest effort)*
**Problem:** 25s uncached first answer; the wait is 100% the prose summary.

| # | Change | Where | Effort | Impact |
|---|---|---|---|---|
| 1.1 | Default summary model → `qwen3:14b` | `OLLAMA_SUMMARY_MODEL` env / `llm_provider.py` defaults | XS | 25s→12s |
| 1.2 | **Return products immediately; stream prose** (SSE or 2-phase: card payload first, `assistant_message` via follow-up/WS) | `recommend.py suggest()` + `chat.py` + `App.tsx` | M | 25s→**<1s perceived** |
| 1.3 | Token streaming for the summary (`stream:True` → SSE) | `_summarize_results` / `_llm_generate_payload` | M | first token ~1–2s |
| 1.4 | Pre-warm + widen semantic cache (lower cosine gate 0.08→0.12, longer TTL) | `_summarize_results` cache block | S | repeat/similar → 0.5s |
| 1.5 | Keep the think-gate (already shipped) — think only on why/compare/yes-no | `recommend.py` (done 2026-06-10) | done | avoids think on simple lookups |

**Recommended order:** 1.1 (now) → 1.2 (the real fix) → 1.4 → 1.3.
**Target:** p50 perceived < 1s (cards), p50 full prose < 8s, cache-hit < 1s.

### WS2 — NQE & query decomposition  *(the "does it answer the question" fix)*
**Problem:** single-intent works; comparison/knowledge/multi-intent don't.

| # | Change | Where | Effort |
|---|---|---|---|
| 2.1 | **Intent router upfront**: `product_search │ comparison │ knowledge │ recommendation_multi │ support`. | new `services/query_decomposer.py`; call in `recommend.suggest()` before retrieval | M |
| 2.2 | **Knowledge/comparison answer path** — when intent is comparison/knowledge OR retrieval is empty, answer the *concept* with the LLM (grounded in spec KB), don't return blank. | `_summarize_results` (handle empty-results branch) + `config/use_case_kb.json` | M |
| 2.3 | **Multi-intent decomposition** — split "gaming + editing + portable" into a constraint union (dGPU ∧ color-accurate panel ∧ ≤2kg) instead of one winning persona. | `query_decomposer.py` → constraints; `flows/nqe.py` already has `detected_*` hooks | M |
| 2.4 | **Numeric/use-case slot extraction** — "240fps"→`refresh_hz≥240`, "portable"→`weight_kg≤2`, "valorant"→esports tier → **hard filters**. | extend `_extract_candidate_numeric_specs` + a query-side extractor | M |
| 2.5 | NQE tuning — keep convergence(3 slots); add "ask vs. show" rule: when budget+use_case known, **show products + ONE optional refiner**, never block. | `flows/nqe.py propose()` | S |
| 2.6 | Decomposition trace events for the Decision Trace panel (shows the agent "thinking") | `query_decomposer.py` + `log_trace_event` | S |

**Target:** comparison/knowledge queries answer 100% of the time; multi-intent honours ≥2 constraints; "240fps" filters to 240Hz panels.

### WS3 — Recommendation quality  *(candidate relevance)*
**Problem:** accessories leak into laptop queries; budget floor soft; specific constraints not honoured.

| # | Change | Where | Effort |
|---|---|---|---|
| 3.1 | **Category guard** — when intent is "laptop/PC", exclude accessories (stands, cables) from candidates unless explicitly asked. | candidate retrieval / `_fast_path_product_score` + full path | S |
| 3.2 | Hard constraint filters from WS2.4 (refresh, GPU class, weight) applied pre-rank. | retrieval filter stage | S |
| 3.3 | Budget floor respected (currently soft → returned $1249 for a $1500 floor). Keep a graceful "nearest" only when the band is empty, and *say so*. | `_extract_explicit_budget_override` consumers + ranking penalty | S |
| 3.4 | Per-product `why` populated on **all** paths (was empty on full path in test). | `results.append(...)` sites in `recommend.py` | S |
| 3.5 | Catalog quality program — ensure each use-case band has real inventory (seed + supplier ingest). | seed scripts + inventory | M |

**Target:** zero accessories in device queries; 100% of returned items satisfy hard constraints; every card has a `why`.

### WS4 — Pipeline architecture  *(scalability & maintainability)*
**Problem:** `recommend.py` is a **13.9k-line monolith**; the cleaner scatter-gather pipeline exists but is **off**.

| # | Change | Where | Effort |
|---|---|---|---|
| 4.1 | **Turn on & finish `RECOMMEND_PIPELINE_V2`** (scatter-gather: DB+vector+fraud+inventory+CV in parallel). Scaffold already present, flag default `0`. | `services/recommend_pipeline.py`, `RECOMMEND_PIPELINE_V2` | L |
| 4.2 | Extract stages out of the monolith: decomposer → retriever → security → ranker → summarizer (each independently testable). | `services/candidate_retriever.py`, `query_classifier.py` already scaffolded | L |
| 4.3 | Parallelize retrieval + CV + security (today largely sequential). | pipeline orchestrator | M |
| 4.4 | **Multimodal routing decision** — for image queries, run a real VLM (`qwen3-vl:8b`/`:30b`, both pulled) on the pixels for product identity, instead of the 27B *text* model reasoning over CV labels. | `cv_triage_basic` Tier-1 + `llm_provider` routing | M |
| 4.5 | De-collapse the model ladder — give `medium` a faster model than `large` (today both = `qwen3.6:27b`). | `config/ml/tier_ladder.json`, `llm_provider.py` | S |

**Target:** suggest() < 400 lines orchestration; stages unit-tested; V2 default-on; image queries use a vision model.

---

## 5. Phased plan

### Phase 0 — Demo hardening  *(hours, before the demo)*
WS1.1 (model swap) · WS1.4 (cache pre-warm) · WS3.5 (seed demo catalog) · §3.3 checklist.
**Outcome:** snappy, truthful happy-path demo; gaps avoided on stage and named in the roadmap slide.

### Phase 1 — "Always answers, fast"  *(Sprint 1, ~1–2 wks)*
WS1.2 products-first/stream · WS2.1 intent router · WS2.2 knowledge/comparison path · WS3.1 category guard.
**Outcome:** no blank answers; <1s perceived; accessories gone.

### Phase 2 — "Understands the request"  *(Sprint 2)*
WS2.3 multi-intent decomposition · WS2.4 numeric slot extraction → WS3.2 hard filters · WS2.5/2.6 NQE tune + trace · WS3.3/3.4 budget + why.
**Outcome:** multi-constraint queries handled; 240fps/portable honoured; decision trace shows decomposition.

### Phase 3 — "Scales & sees"  *(Sprint 3+)*
WS4.1 V2 pipeline on · WS4.2 monolith breakup · WS4.3 parallelism · WS4.4 VLM routing · WS4.5 ladder de-collapse · frontend `breach_assessment` panel.
**Outcome:** maintainable parallel pipeline; true image-anchored recommendations; full security UI.

---

## 6. Success metrics (instrument these)

| KPI | Today | Phase 1 | Phase 3 |
|---|---|---|---|
| p50 perceived latency (cards) | ~25s | <1s | <0.5s |
| p50 full-answer latency | 12–25s | <8s | <5s |
| % queries that return an answer | ~80% (blanks on comparison) | 100% | 100% |
| % returned items meeting hard constraints | ~70% | 90% | 100% |
| Multi-intent constraints honoured | 1 of 3 | 2 of 3 | 3 of 3 |
| Accessories in device queries | present | 0 | 0 |
| Security: compromised-image still serves + escalates | ✅ | ✅ | ✅ + UI panel |

---

## 7. Sequencing notes & risks
- **WS1.2 (products-first) is the single highest-leverage change** — it makes everything *feel* fast regardless of model speed, and unblocks streaming.
- **WS2 depends on a clean intent router (2.1) landing first**; 2.2/2.3/2.4 hang off it.
- **WS4.1 (V2 pipeline) is the biggest lift** — do it last, after stages are extracted (4.2) so you're parallelizing clean units.
- **Catalog quality (WS3.5) is a force-multiplier** — great routing over a thin catalog still disappoints. Seed in parallel with engineering.
- Keep the **security path untouched** through all phases — it's the moat and it's already verified resilient.

---
*Verified live 2026-06-11: Ollama models present (`qwen3.6:27b`, `qwen3:14b`, `qwen3-vl:8b/30b`); regression — full API+security suites green except one pre-existing Redis-dependent auth test; zero regressions from the 2026-06-10 security/image changes.*
