# ShopSquire — Model-Quality Eval, LLM Token-Cost, and Competitive Position (2026-06-28)

Scope: (A) measured LLM narration / email-draft / vision quality across local models, (B) the agentic
LLM **token-cost** profile, (C) how the architecture compares to other platforms. All LLM inference is
**local (Ollama)**; numbers below are from a live eval on this machine.

---

## A. Model-quality eval (measured, local Ollama)

### A1. Recommendation narration — grounded on the new per-pick evidence
Three scenarios × `qwen3:14b`, `qwen2.5:14b`, `mistral-small3.2:24b`. All read the structured
`*_fit` evidence block (price_fit / office_fit / fleet_fit / inventory_fit / …).

| Scenario | Result (all 3 models) | Verdict |
|---|---|---|
| Office, real fleet (ThinkPad + EliteBook) | Cited both by `[N]`, noted vPro/fleet + 16GB, "Yes, both fit your budget and office needs" | ✅ relevant + grounded |
| **Office, only gaming in budget** | "No office-grade laptops are available… consider sourcing business-class units" — **none sold gaming as a work pick** | ✅✅ the evidence guard held across every model |
| Gaming | Cited MSI Katana + RTX 4070 + 144Hz for esports | ✅ relevant |

Latency: first call `qwen3:14b` ~22s (cold model load), **warm ~5s** for all three. No model
hallucinated a spec; the `[N]`-citation + "narrate from evidence, don't invent" prompt worked.

### A2. Supplier email-draft polish — the cage holds regardless of model
RFQ draft → `polish_supplier_draft` → re-validated by the claim-safety cage.

| Model | Result | Cage verdict |
|---|---|---|
| `qwen2.5:14b` | Clean, professional rewrite | **SAFE** (sent) |
| `llama3.2:3b` | Minimal rewrite, preserved content | **SAFE** (sent) |
| `qwen3:14b` | Reasoning mode broke `format=json` → returned None | **Deterministic fallback used** (cage worked) |

Takeaway: **`qwen2.5:14b` is the best email-polish model**; `qwen3:14b`'s thinking tokens break strict
JSON output, but the cage correctly falls back to the deterministic draft — **no unsafe output ever ships**.

### A3. Vision (product identification from image)
| Model | JPEG result | Verdict |
|---|---|---|
| `qwen2.5vl:7b` | "Apple MacBook Pro laptop" (~40s) | ✅ accurate (slow) |
| `llava:latest` | "MacBook Pro from Apple" (~18s) | ✅ accurate |
| `moondream:latest` | "iphone" (~5–14s) | ❌ wrong (too small) |

**Real finding:** Ollama vision returned **empty** for `.webp` inputs; JPEG/PNG worked. → the CV path
should transcode `.webp`→JPEG before the vision call (or document the limitation). Recommended vision
model: **`qwen2.5vl:7b`** for accuracy, `llava` for a faster second opinion; avoid `moondream` for product ID.

### A4. Model recommendations
- **Narration:** `qwen2.5:14b` (fast + accurate) or `mistral-small3.2:24b`. Avoid `qwen3:14b` where strict
  JSON/format is required (reasoning tokens); fine for free-text narration.
- **Email polish:** `qwen2.5:14b`.
- **Vision:** `qwen2.5vl:7b` (+ `.webp`→JPEG transcode).

---

## B. LLM token-cost profile — is there much? **No.**

**Yes, your hypothesis is correct: the platform is deterministic-first with near-zero LLM token spend.**

### B1. The decision core uses ZERO LLM tokens
Fully deterministic (no model call): candidate retrieval + ranking, the new **choice-lanes** and
**`*_fit` evidence**, budget/stock checks, fraud scoring (26+ signals), security observers, the
**fulfillment state machine**, supplier ranking, **quote parsing + comparison**, economics, the
exception/governance machinery. These are math + rules, not prompts.

### B2. The only routine LLM call is one narration per substantive query
| LLM touchpoint | Default | Tokens/call (approx) | Notes |
|---|---|---|---|
| Recommendation **narration** | `USE_LLM_SUMMARY=1`, `blocking`, **8s cap** | ~600–1,200 in / ~120–250 out | 1 call per substantive recommend; can be `skip`/`async` |
| Intent routing | gated (complexity-scored) | small model, short prompt | skipped for simple queries |
| LLM rerank | flag (`USE_LLM_RERANK`, off unless set) | — | deterministic ranker is the default |
| Embeddings | `nomic-embed-text` (local) | embedding, not generation | semantic search/cache |
| Supplier email polish | **OFF by default** | ~300 | only when `SUPPLIER_DRAFT_LLM_POLISH=1` |
| Vision (CV) | **OFF by default** | image+prompt | only when `CV_VISION_ENABLED=1` |

### B3. Cost conclusion
- **All inference is self-hosted on Ollama → $0 per-token API fees.** The marginal cost of a query is
  GPU compute/electricity, not metered tokens.
- A typical recommend = **1 local LLM call (narration)**; everything that decides *what* to recommend or
  *whether/how* to procure is deterministic. Narration is a thin presentation layer, not the decision-maker.
- Latency, not dollars, is the real budget — and it's already bounded (8s narration cap; `skip`/`async`
  modes; route-timing observability). If even narration is disabled, the platform still returns a correct,
  grounded deterministic answer.

**Implication:** unit economics scale with traffic at ~flat marginal cost — the opposite of per-token or
per-conversation agentic pricing.

---

## C. Competitive position — "deterministic core + thin local LLM + shift-left security"

| Platform | LLM usage model | Cost shape | Determinism / auditability | Security posture |
|---|---|---|---|---|
| **ShopSquire** | Local LLM as a thin **narration** layer over a deterministic engine | **~Flat marginal** (self-hosted, $0/token) | Decisions deterministic + bitemporal decision-trace audit | **Shift-left security in the pipeline** (fraud, CV triage, prompt-injection cage, supplier BEC guard) |
| Shopify Magic / Sidekick | Hosted LLM features bolted onto the storefront | Bundled/usage; vendor-metered | Mostly opaque generative output | Platform security; not AI-pipeline-specific |
| Salesforce **Agentforce** | LLM-agentic, per-conversation/per-action | **Per-conversation pricing** (metered) | Agent reasoning largely non-deterministic | Enterprise trust layer; general |
| **CrewAI / LangChain** agent stacks | Multi-LLM-call agent loops per task | **High** (many paid API calls, retries) | Non-deterministic, hard to audit | DIY |
| Darktrace / CrowdStrike | (Security only, not commerce) | Seat/endpoint | N/A to merchandising | Strong security, **no commerce decisioning** |

**Differentiators**
1. **Cost:** deterministic-first + local LLM = near-zero marginal token cost vs per-conversation/per-call
   agentic billing. This is a structural unit-economics advantage at scale.
2. **Auditability:** decisions are deterministic and recorded on a bitemporal decision trace — you can
   replay *why* a pick/price/route happened. Agentic-LLM stacks can't reconstruct a stochastic chain.
3. **Safety:** the LLM is **caged** — it narrates/drafts, but a deterministic guard authorizes (proven
   above: a model that breaks format simply falls back; the supplier send-cage rejects unsafe rewrites).
4. **Security depth:** shift-left fraud/CV/prompt-injection/BEC controls inside the commerce pipeline —
   a quadrant (high security × high commerce-domain depth) competitors don't occupy.

**Honest weaknesses vs the field:** smaller catalog/connector ecosystem than Shopify; no hosted-LLM
"wow" polish out of the box (deliberate — local + caged); requires GPU hosting for the narration/vision
layer (the trade for $0/token).

---

## D. Follow-ups identified by the eval
1. **CV `.webp` → JPEG transcode** before the vision call (vision returned empty on `.webp`). (Item 7 area.)
2. Default **narration model → `qwen2.5:14b`** (faster + accurate); keep `qwen3:14b` out of strict-JSON paths.
3. Catalog gap: lanes need real **Windows-business / MacBook / Surface / Chromebook** SKUs to populate
   (see the procurement-metrics + product-template note in chat).
