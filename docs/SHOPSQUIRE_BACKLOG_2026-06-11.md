# ShopSquire — Living Backlog
**Updated:** 2026-06-11  ·  **Lens:** showcase a plausible, clearly-engineered bounded-autonomy agentic commerce platform (NOT enterprise hardening yet)

> This is the single source of truth for what's done, what's next, and what's deliberately deferred. The goal is to *assess plausibility and usefulness* via a compelling, honest showcase — not to productionize. Priorities reflect that.

---

## ✅ DONE (2026-06-10 → 06-11)

### Security membrane (image / trust boundary)
- **Warn-and-continue on compromised image** — never hard-deny the recommendation; quarantine the malicious channel (QR/OCR/steg), keep the safe visual product recognition. `chat.py` `_assess_image_compromise_breach` (IP + ASN/GeoIP bad-actor scoring + human escalation + MITRE/OWASP tags). Legacy hard-lock behind `IMAGE_COMPROMISE_HARD_LOCK=1`.
- **Channel-separated trust** — distrust pixels only on adversarial/forgery, not a QR pasted on a real photo.
- **Apple off-topic fix** — fruit no longer misread as the brand (`cv_triage_basic.py`).
- **Privilege-escalation / code-exec / rogue-agent now scored HIGH** (`observer.py`) — eval caught these were *detected but unscored*.

### NLP / recommendation quality
- **Query decomposer** (`services/query_decomposer.py`) — intent router (product/comparison/knowledge/multi) + multi-intent + numeric slot extraction. 7 unit tests.
- **Knowledge/comparison answer path** — "4060 vs 4070" no longer returns a blank screen (injected at `_with_trace`, survives all early returns).
- **Hard filters + accessory guard** — "240fps"→`refresh_hz≥240`, "portable"→weight cap, dGPU requirement; no laptop-stands in laptop queries.
- **`why` on every result card.**

### Anti-hallucination (the centerpiece)
- **Grounding ladder** (`services/grounding_ladder.py`) — assert-to-evidence, catalog-disposes brand drop, cross-source conflict detection, tiers 0–4, confidence labels. Wired at the recommend identity seam (`GROUNDING_LADDER_ENABLED`). 8 unit tests.
- **Residual question surfaced** — "Is this a Razer?" leads when the ladder can't confirm (NQEInput + chat.py).
- **Generation-layer identity fence** — `_summarize_results` forbids naming an unverified brand/model.
- **Claim grounding** (`services/claim_grounding.py`) — the SECOND surface (return-fraud: claim vs CV/receipt → supported/needs_evidence/contradicted). 5 unit tests.

### Speed
- `qwen3:14b` summary default (25s→12s), de-collapsed tier ladder.
- Tunable semantic cache (`SEMANTIC_CACHE_MAX_DISTANCE`) + `scripts/prewarm_demo_cache.py` (→0.5s).
- Products-first `include_summary=False` → **1.7s warm** cards.

### Proof & demo
- **Eval harness** (`eval/`, `python -m eval.run_eval`) — 4 datasets, deterministic scorecard + optional `--live`. Current: intent/constraints/grounding/claims **100%**, security **precision 100% / recall 100% / FP 0%**, escalation precision **100%**.
- **Bounded-autonomy demo** (`scripts/demo_bounded_autonomy.py`) — autonomy dial, thesis runnable in ~1s.
- Decision trace renders all new events generically (`humanizeKey`) — no frontend change needed.
- ~20 new unit tests; full api/security/services regressions green (1 pre-existing Redis auth test unrelated).

---

## 🎯 NEXT — P0 (do these before/for the showcase)

| # | Item | Why | Effort |
|---|---|---|---|
| P0-1 | **Wire the frontend to render the new evidence** — `breach_assessment` panel, grounded-confidence badge, `recognized_product`, the residual question, knowledge answers. Backend emits them; React ignores them. | The intelligence is invisible in the UI today. This is what makes the demo *show* the architecture. | M |
| P0-2 | **Stage + rehearse the 3-act demo** (script in [the roadmap](SHOPSQUIRE_NQE_SPEED_PIPELINE_ROADMAP_2026-06-11.md)): shopping → under-fire → the-trace, with the scorecard slide + autonomy dial. Rehearse the unhappy path (Ollama stalls). | The demo *is* the deliverable for "is this worth pursuing?" | S |
| P0-3 | **Pre-demo hardening checklist** — `OLLAMA_SUMMARY_MODEL=qwen3:14b`, `SEMANTIC_CACHE_MAX_DISTANCE=0.12`, run `prewarm_demo_cache.py`, seed a real-looking catalog, set `OWNER_API_KEY`. | Snappy + truthful happy path; gaps avoided on stage. | S |

## 🔜 NEXT — P1 (strengthens the showcase)

| # | Item | Why | Effort |
|---|---|---|---|
| P1-1 | **LLM-judge faithfulness layer** in the eval (`--live` deeper) — score answer faithfulness + relevance with a strong model, not just the deterministic proxy. | Turns "100% on our checks" into "0.9 faithfulness, judged." | M |
| P1-2 | **Install `sentence-transformers` + `faiss-cpu`, build the visual index** (`scripts/build_visual_index.py`, `VISUAL_SEARCH_INDEX_ON_START=1`). | Activates `visual_match` → grounds product *line* ("MSI Raider") → unlocks ladder tiers 0/1. | S |
| P1-3 | **Streaming UI (products-first SSE)** — cards instantly, prose streams. | Makes act 1 feel alive; <2s perceived. | M |
| P1-4 | **Tighten `identity_abuse` regex** — `elevate\s+privilege` misses "elevate **my** privileges". | Latent detection gap (masked in eval by "act as admin"). | XS |
| P1-5 | **Fix `/suggest`-direct residual drop with `budget_max`** (NQE cap quirk; chat.py compensates for the real flow). | Consistency for the direct API. | S |

---

## 🅿️ DEFERRED — explicitly NOT now (with rationale)

| Item | Why deferred |
|---|---|
| **Supplier verification** (3rd grounding surface) | Same primitive as products/claims — adds breadth, not demo value. Build when a supplier story is needed. |
| **VLM product-identity routing** (parallel vision pass) | Medium effort; do after the CLIP index (P1-2) so it has something to cross-check against. |
| **Email-membrane / Agent-to-Agent (A2A) frontier** | Architect on a slide; don't build until the core thesis lands. |
| **Monolith breakup** (`recommend.py` ~14k lines) | Genuine multi-day refactor; premature — it's a maintainability cost, not a demo blocker. |
| **Hosted inference** (vLLM/TGI), multi-tenant isolation audit, SLOs | Enterprise scale. Premature until the showcase says it's worth scaling. |
| **Multi-intent decomposition (deeper)** | Current version honours the constraints; deeper ranking-fusion is polish. |

---

## 🐞 KNOWN ISSUES / CAVEATS (tracked, not blocking)
- **Eval escalation rate (~52%) is dataset-skewed** — the set is half adversarial by design (boundary stress-test). The defensible number is **escalation precision (100%)**, not the rate. Real traffic escalates far less.
- **CLIP/FAISS not installed in dev** → `visual_match` grounding inactive; catalog-brand grounding compensates (correctly). See P1-2.
- **Products-first cold latency ~12s = one-time model load** — `prewarm_demo_cache.py` eliminates it.
- **Pre-existing:** `test_auth_forced_reauth_enforcement` needs real Redis (unrelated to any of this work).

---

## 📌 The honest verdict (for the "is this worth pursuing?" question)
You have the trio that turns breadth into "clearly engineered": **it works** (eval + regression gate), **it's visible** (decision trace), **the thesis is runnable** (autonomy demo). The eval even caught a real security gap on its first run — the strongest possible signal the methodology is real. Next investment should be **making it visible in the UI (P0-1) and staging the demo (P0-2)** — not more backend. The showcase will tell you whether enterprise scale is worth it.
