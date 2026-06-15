# ShopSquire — Live Clickthrough Assessment (2026-06-15)

Real in-process run of the actual app (`create_app()`/`TestClient`) against the
seeded **128-product** catalog. CV libs (pyzbar/cv2/PIL/YOLO) are real and ran
locally. **Caveats (honest):** Ollama was unreachable (the platform's own
`url_guard` blocks the outbound vision-LLM call → `unsafe_url:blocked_host`), so
(a) the vision-LLM half of CV (labels/product-identity) and (b) the LLM natural-
language summary were **not** exercised; Redis fell back to DummyRedis. Everything
below is observed output, not prediction.

Harness: `c:\tmp\authz_clickthrough.py`. Matrix: 2 images × 3 query intents.

---

## 1. Results (observed)

| # | Image | Query | Result | NQE | NL answer |
|---|---|---|---|---|---|
| 1 | apple-red.jpg (fruit) | gaming $1200–1800 | **7 gaming laptops** (MSI Thin A15 RTX3050 $1799, HP Victus 16 $1249, MSI Katana $1499) | shortlist Q | "Great news for your gaming setup — 7 matches $1,200–$1,800. Best: MSI Thin A15 [RTX 3050] ($1,799)…" |
| 2 | msi-SSN.png (laptop+QR/SSN) | gaming $1200–1800 | **same 7** | shortlist Q | same |
| 3 | msi-SSN.png | university (no budget) | **31 student laptops** (Lenovo IdeaPad 5 $1124, Dell Inspiron $1199) | shortlist Q | "great student-friendly options… Best for uni: Lenovo IdeaPad 5 ($1,124)…" |
| 4 | msi-SSN.png | content creation (no budget) | **19 creator laptops** (HP OMEN MAX RTX5080, Legion Pro 7 RTX5090) | **3 clarifying Qs** | "For your creative workflow, 19 options…" |

**YOLO object detection ran for real:** apple-red → "3 apples, 1 donut, 1 mouse";
msi-SSN → "1 laptop". So object recognition correctly distinguished food from laptop.

**The content-creation clarifying questions (scenario 4) — exactly the asked-for behaviour:**
1. "what will you mostly do: general office/school, creator/engineering tools, or gaming?"
2. "what matters more for creator workloads: dedicated GPU + VRAM headroom, or battery and lighter weight?"
3. "do you have a price tier in mind (Under $1000, $1000–$1500, $1500+)?"

---

## 2. What works well (real, differentiated)

- **Recommendation quality:** correct category + budget filtering, GPU-aware, `why`
  reasons per card (`+use_case_match:gaming`, `+embedding_similarity`, `+cross_encoder`,
  `+in_stock`). Gaming→gaming, university→student, content→creator.
- **Answers the question without an LLM:** the deterministic answer-builder gives a
  direct, specced, on-topic reply ("7 matches $1,200–$1,800. Best: MSI Thin A15 [RTX
  3050] $1,799") — the BUG-6/7 robotic-summary fix is real and survives an LLM outage.
- **NQE clarifies genuine ambiguity:** "content creation" → 3 sharp disambiguating
  questions (use-case / GPU-vs-portability / price tier).
- **Bitemporal decision trace + agent swarm:** every request emitted **40–42 trace
  events across ~25 agents**, retrievable via `GET /api/v1/trace/{id}/events`:
  `Security_Observer_Agent`, `Fraud_Scoring_Agent`, `Policy_Gate_Agent`,
  `Recommend_Autonomy_Governance_Agent`, `NLP_Search_Agent`, `NQE_Agent`,
  `Product_Identity_Agent`, `Candidate_Retrieval_Agent`, `Category/Price/Spec/GPU_Filter`,
  `Product_Ranking_Agent`, `Model_Selector`, `Inventory_Agent`, `Recommendation_Agent`,
  and **`Image_Security_Gate_Agent`** (scenario 4). This trace depth is the platform's
  signature differentiator and it is genuinely there.
- **Didn't get derailed by the irrelevant image:** apple photo + gaming query still
  returned gaming laptops (didn't recommend fruit-adjacent nonsense).

---

## 3. Gaps found (real, prioritized)

**P0 — CRITICAL: vision-LLM outage silently disables deterministic security.**
`/cv/analyze` ([cv.py:417](../src/app/routers/cv.py#L417)) runs `tier2` (vision-LLM),
`image_consistency`, and `qr_decode` in **one `asyncio.gather` under a single 15s
`wait_for`**. When the vision-LLM hangs, the whole group is cancelled — so the
<100ms deterministic QR/steg/SSN analyzers are killed too. Observed: both images
"parallel tasks timed out after 15.0s" → `qr_prompt_injection: false`.
**Proof the detector itself is fine:** run directly, pyzbar decoded the MSI image's
QR as `https://scanned.page/p/R2g2Jb` (a dynamic-redirect URL — exactly the exfil
pattern). **Consequence:** in this run the compromised image (scenario 2) was handled
identically to the unrelated one (scenario 1); no `[SECURITY]` surfaced. The logic is
right; the *orchestration coupling* defeats it on any vision-LLM degradation.
**Fix:** isolate deterministic analyzers from the LLM task — run QR/steg/phash
synchronously (or with their own short timeout), put only the vision-LLM call under the
wall-clock budget. ~30-line change, high security value.

**P1 — NQE shortlist question fires on the first turn.** Scenarios 1–3 asked "Do you
mean products from your previous shortlist, or start fresh?" with no prior shortlist —
a disambiguation that doesn't apply on turn one (the BUG-4/5 shortlist-context family).

**P2 — PII over-redaction false positive.** "Dell Inspiron **[REDACTED_PHONE]**" — a
model number was redacted as a phone number in the output path. Harms product display.

**Env-limited (not platform bugs), to retest with the full stack:** vision-LLM labels /
product-identity (Ollama down) → grounding ladder got no *visual* evidence this run; LLM
NL summary not exercised; OCR/SSN text extraction unconfirmed (swallowed by the P0 timeout).

---

## 4. Delta vs previous tests (dump/ screenshots)

| Earlier finding | Now |
|---|---|
| Robotic summary ("I found 3 matches", no answer) — `sec-LLM-summ.png` | **Fixed** — direct specced answers, even without the LLM |
| Wrong-model / under-anchored multimodal — `lenovo-multimodal*` | Recommendations correctly category+budget+GPU filtered |
| NQE repeating budget/brand after disambiguation — `smart-1/2.png` | Budget/use-case respected; one *new* first-turn shortlist nit (P1) |
| Visual attack handling — `where payload.png` (QR decoded, products still right) | Deterministic QR decode still works; but P0 coupling now hides it on LLM outage — **a regression-class risk to track** |
| Decision trace depth | 40–42 events / ~25 agents, retrievable — strong |

---

## 5. How each stakeholder reacts

**Shopper:** "It actually answered me, with specifics and prices, and asked smart
questions when I was vague." Strong. Watch-out: the first-turn "previous shortlist?"
question feels odd.

**AI engineer:** "Grounding ladder + NQE + a 25-agent traced swarm with per-card
reasons and a deterministic fallback answer — this is a real, inspectable pipeline,
not a single LLM call." Will want the vision-LLM path up to judge multimodal grounding,
and will immediately flag the P0 gather-coupling as an availability/security smell.

**Security reviewer:** "The bitemporal trace, the in-pipeline Security_Observer/
Fraud/Policy agents, and the QR-exfil detector are exactly right — but P0 means a
vision-LLM outage blinds the deterministic detectors. That's a fail-open on a security
control and must be fixed before any 'in-pipeline security' claim. Also fix the
over-redaction (data-quality) and confirm SSN/PII OCR end-to-end."

---

## 6. Investor case (vs Shopify / Magento / Agentforce / CrowdStrike / Darktrace)

- **Unoccupied quadrant:** high ecommerce-domain depth **and** high security depth.
  Shopify/Magento have commerce, not in-pipeline AI security; CrowdStrike/Darktrace
  have security, not commerce reasoning; Agentforce/CrewAI have agents, not a
  bitemporal audit + bounded-autonomy control plane.
- **Demonstrable moat (seen today):** per-decision **bitemporal trace across 25 agents**,
  a **deterministic Authorization Engine** (refunds/supplier-orders/PII gated, fail-closed,
  shadow→active), an **exception model proven to have no fall-through**, and **CV return-
  fraud + QR-exfil detection in the buy/return path**.
- **Honest diligence answer:** "the differentiated intelligence + autonomy-control layer
  is built and tested; the remaining work is loop-closing and de-coupling one CV
  orchestration path — not research." That's an investable position.

---

## 6b. Fixes applied + verified (2026-06-15, same day)

- **P0 — CV security fail-open FIXED (two parts).** (1) Decoupled the three CV
  tasks in `/cv/analyze` into per-task timeouts so a vision-LLM hang can't cancel
  the others. (2) Discovered the real-tier2 (YOLO/steg, CPU-bound) was **starving
  the QR worker thread**, so the QR decode itself timed out even decoupled — fixed
  by running the deterministic QR/barcode decode **first and uncontended**, then the
  heavy tasks. **Proven on real images:** `msi-SSN → qr_code_detected=True`,
  `apple-red → False`. The security signal now differentiates compromised vs clean.
  Test: `tests/api/test_cv_security_decoupling.py`.
- **P1 — first-turn shortlist NQE FIXED.** Gated the "previous shortlist vs fresh
  search?" question on an actual prior shortlist existing. Re-run: 0 occurrences
  (was firing on all 3 first-turn scenarios). `recommend.py` ~12451.
- **P2 — PII over-redaction FIXED.** `deps.py scrub_pii` now validates the matched
  token holds 10–15 digits before redacting as a phone. "Dell Inspiron 14 7440"
  preserved; real phones still redacted; 19 PII tests pass.
- Regression: 49 tests green across cv-decoupling / authz-engine / seam /
  exception-model / claim-grounding / authz-audit.

## 6c. Live-Ollama re-run (vision + LLM, same day)

Ollama was actually **up** the whole time (host :11434, vision models `qwen2.5vl`/
`llava`/`qwen3-vl` + text `qwen3`/`llama3.2`/`mistral-small`); the earlier failure
was the platform's `url_guard` blocking the literal host `localhost` (in `_BLOCKED_HOSTS`,
checked before any allowlist). Forcing `OLLAMA_URL=http://127.0.0.1:11434` (an IP
literal, allowed in non-prod) lights up the full path in-process — no Docker needed.

With the LLM live:
- **Answers became genuinely good**, spec-grounded and citing products by index:
  gaming → "best pick is [3] for its RTX 4070 — runs modern games at high settings,
  handles ray tracing; [2] strong with RTX 4060 + 16GB…"; content creation →
  "[1] … accurate colors for color grading, powerful GPU speeds up rendering, 32GB
  RAM handles 4K timelines." University → battery/RAM/storage reasoning.
- **NQE questions sharpened** ("What kind of games — determines the GPU tier"; "What
  subject are you studying — matches specs to workload"). P1 fix held (no shortlist Q).
- **Compromised image now FULLY detected at cv/analyze:** msi-SSN →
  `image_consistency.status="mismatch"`, `suspicious`, `soft_verify_required=true`,
  reasons `["qr_code_detected","qr_external_url…"]`. apple-red stayed clean.

**NEW finding (honest) — detection ≠ shopper-facing surfacing in the recommend path.**
Although cv/analyze flags the compromised image, the `/suggest` response's `security`
block and `assistant_message` were **identical** for the compromised (scenario 2) and
clean (scenario 1) images — no `[SECURITY]` note to the shopper. Two causes: (a) the
cv→suggest hand-off is brittle — the QR verdict lives nested in
`image_consistency.images[].reasons`, so a caller must know to extract+forward it; and
(b) the recommend `[SECURITY]` prefix triggers on **prompt-injection** QRs, not on a
benign-looking **exfil/redirect** QR (`qr_code_detected` without injection). The
chat-orchestration path (`/api/v1/chat/query`) — which normally injects `[SECURITY]`
— couldn't be exercised in-process (it calls recommend over internal HTTP).
**Next fix:** standardize the cv→recommend security hand-off and surface
`qr_external_url`/`suspicious` (not just injection) as a shopper `[SECURITY]` note.

## 6d. Text-only vs image+text — controlled experiment (Ollama live)

Same brand-neutral query ("which gaming laptop should I get", $1200–1800); one arm
text-only, one arm with the MSI image (real vision identity forwarded). Vision was
accurate: `MSI / laptop / RTX / 16GB / conf 0.9` (qwen2.5vl:7b).

| | ARM A — text only | ARM B — image + text |
|---|---|---|
| Results | 7, **all in budget** ($1,249–$1,799) | 8, **mostly OUT of budget** ($1,919–$5,999) |
| Reasoning (`why`) | diverse: `+use_case_match`, `+embedding_similarity`, **`+cross_encoder`** | dominated by **`+embedding_similarity`** only |
| LLM answer | "MSI Katana 15 [3] is the best pick **in this budget** — RTX 4070, 144Hz, 16GB, 1TB" | "**No product fits your budget**… exceeds your $1,800 limit" |
| Result overlap | — | **1 of 7** vs text arm |
| Extra agents | `Price_Filter_Agent` | `Image_Text_Fusion_Agent`, `Product_Identity_Agent` |
| Missing agents | — | **`Price_Filter_Agent` absent** |

**Findings:**
1. **The image genuinely changes recommendations** (overlap 1/7) — when the product
   identity is forwarded, the grounding ladder + Image_Text_Fusion shift retrieval.
   (My first harness saw *no* change only because it didn't forward `image_product_identity`.)
2. **NEW P0-class bug — image+text bypasses the budget hard-constraint.** ARM B
   returned $1,919–$5,999 laptops for a $1,200–1,800 ask and the LLM itself said "no
   product fits your budget", even though in-budget gaming laptops exist (ARM A found 7).
   The trace shows **`Price_Filter_Agent` runs in the text arm but NOT the image arm** —
   the visual/embedding-similarity signal dominates and the price filter is dropped.
3. **Reasoning quality regresses with the image**: text arm uses cross-encoder rerank +
   multiple signals; image arm collapses to raw embedding similarity. This mirrors the
   old BUG-2 (multimodal under-scoring) and the `lenovo-multimodal` screenshots.

**Takeaway:** text-only is currently the higher-quality, safer path. The image adds
real grounding (brand/spec) but today *degrades* recommendation quality by skipping the
budget filter and over-weighting visual similarity. **Fix: enforce hard constraints
(budget/category) on the image+text path too — constrain visual/identity similarity to
the within-budget candidate set, and keep the cross-encoder rerank.**

## 6e. P0 multimodal budget-bypass — root-caused + FIXED (2026-06-15)

**Diagnosis (via the decision trace, not guesswork):** the image+text path's
`LLM_RERANK_Gate` showed `budget_cap: null` and **no `Price_Filter_Agent` fired**,
while `Category/Spec/GPU` filters did. The budget block at `recommend.py:10079`
reads `constraints.get("budget_min/max")` — it was skipped because an upstream
constraint rebuild on the image / multi-intent path **silently dropped the explicit
budget API params** (text-only kept them). This is a *silent fail*: no error, just
wrong results.

**Fix (right altitude):** the explicit budget API params are AUTHORITATIVE — re-assert
them into `constraints` immediately before the budget block, so text, image, and
multi-intent paths all enforce the user's stated budget. Emits a trace breadcrumb
when it has to correct drift (observability, not silent).

**Proven** by re-running the identical experiment:
| | before | after |
|---|---|---|
| ARM B (image+text) prices | $1,919–$5,999 ❌ | **$1,259–$1,799** ✅ |
| LLM answer | "No product fits your budget" | "best pick is [3] for its RTX 4060… 144Hz" |

The image still personalizes (top card `+brand_match`) — now within budget.

**Remaining (P0#2, partial):** the image arm's reasoning is still weaker than text —
2 of 3 cards showed `catalog fallback fill` instead of `+cross_encoder`/`+embedding_similarity`.
The cross-encoder rerank / richer "why" isn't fully applied on the image path. Next.

## 6f. Tech-debt / silent-fails / refactor targets found in this area

- **Silent fail (fixed):** explicit budget dropped on the image path — no log, no error.
  The re-assert now emits a breadcrumb when it corrects drift.
- **Constraint mutation has no single source of truth.** `constraints` is built and
  re-derived in several places (NLP parse, image fusion, multi-intent, identity specs);
  the budget loss was a symptom. *Refactor:* a single `resolve_constraints()` that merges
  explicit params (authoritative) > NLP > image, returning an immutable snapshot.
- **Price-filter logic is duplicated across ~6 branches** (`recommend.py:10100–11433`):
  in-budget filter, brand-band fallback, nearest-above-budget, brand-jump, etc. — each
  re-issues similar SQL. *Refactor:* one `_apply_budget(candidates, min, max, tolerance)`
  + one `_fallback_nearest(brand, band)` helper.
- **Vision-model nondeterminism:** identity came back `MSI/qwen2.5vl` one run and
  `Acer Predator/llava` another (model auto-selection varies). Pin `CV_VISION_MODEL`
  for reproducibility; treat low-confidence identity as a clarifying-question trigger,
  not a silent anchor.
- **`_fast_path_catalog_recommendation` lists static `parallel_agents`** (incl.
  `Price_Filter_Agent`) in `right_panel` that don't correspond to real trace events —
  cosmetic drift between the displayed agent list and the actual run.

## 6g. Latency (measured), security-escalation, email bounded-autonomy (2026-06-15)

**Reply latency (in-process, measured, Ollama live — median of 3):**
| path | median | max |
|---|---|---|
| TEXT, no LLM | 0.86s | 0.94s |
| TEXT + LLM summary (qwen3:14b) | 3.7s | 14.8s |
| IMAGE+TEXT, no LLM (features as params) | 1.4s | 1.9s |
| IMAGE+TEXT + LLM summary | **52s** | 52s |
| `/cv/analyze` raw image (full security) | **86s** | 108s |

- **The /suggest engine is fast (~1s).** The latency the user feels on an image upload is
  catastrophic — **50–86s** — driven by the **vision-LLM** (qwen2.5vl:7b for labels/identity,
  tens of seconds on this hardware) plus tier2 + the qwen3:14b text summary. This is a
  **live-demo blocker**, not a nice-to-have.
- **Improve (urgent, in priority order):** (1) cache vision identity + CV verdict by image
  hash → repeat demo images instant; (2) pre-warm/pre-compute the demo image set; (3) pin a
  FAST vision model (moondream / smaller) or GPU; (4) stream over SSE — paint YOLO labels
  (~100ms) + deterministic QR/security (<6s) immediately, hydrate vision identity + LLM
  summary async; (5) make vision identity optional/async (don't block results on it);
  (6) hard client timeout on every Ollama call + the deterministic fallback (already exists).

**Frontend security-flag → human escalation:**
- Backend: STRONG. `chat.py _assess_image_compromise_breach` runs IP/ASN/GeoIP breach
  assessment, persists a security event that **auto-routes to an incident + WORM audit**,
  emits `image_security_escalation`, route="escalate" (warn-and-continue: products still
  flow text-only). EscalationRoom backend = full state machine + staff notify + SLA.
- Frontend: `EscalationRoom.tsx` = complete live room (WS→SSE→poll, buyer+staff tokens,
  CSRF). Trigger wired in the **CV/returns** panel (`RightPanelExtras.escalate()` →
  `/api/v1/incidents/escalate` → opens room). Demo-friendly: `_allow_public_escalation`
  allows token-based rooms on localhost without an auth wall.
- **GAP:** in the **shopping** flow a flagged image shows only the "⚠️ Image flagged —
  text-only results" banner; the backend creates the breach incident but the **shopper
  gets no in-chat "talk to a human"/open-room affordance** there. Escalation UI lives in
  the returns/CV panel only. For a slick live demo of "security flag → human room" in
  shopping, add a shopper-facing escalate button when `image_flagged`/`route=escalate`.

**Email security — bounded autonomy (no auto-reply is correct):**
- Tier 0 auto (no human): verified-safe (SPF/DKIM/DMARC pass + trusted domain + no
  BEC/attachment risk) → auto-file / optional auto-ACK with a **human-approved template**.
- Tier 1 bounded autonomous (no human, reversible): quarantine attachment, rewrite/strip
  URLs, hold, tag.
- Tier 2 escalate to GOVERNANCE/analyst (NEVER auto-reply): BEC, bank-detail-change
  request, supplier-domain drift, attachment-forensics hit → `notify_analyst` + incident
  → analyst sends any reply MANUALLY.
- Tier 3 hard block: never auto-reply to flagged/spoofed senders; `bank_change` via email
  = hard_block. These map directly onto the Authorization Engine (`never_auto`/`hard_block`),
  so email actions should route through `authorize_action()` too.

## 6h. Image-path latency FIX (2026-06-15) + tech-debt found

**Root cause (deep dive):** the vision-LLM runs **twice per image upload** — once in
`product_identity_agent.identify_product_from_image` (recommend grounding) and once in
`cv_provider.get_labels_and_text` (cv/analyze + sidecar + orchestrator) — with **no
cache anywhere**, and `identify_product_from_image`'s `url×model` loop waited up to
`timeout_s` **per iteration** (stacking to N×timeout on a slow first model).

**Fix shipped (safe, fail-open, tested):**
- `services/vision_cache.py` — sha256(image_bytes)+namespace TTL+LRU cache; both vision
  entry points check/populate it. A repeat image skips the vision call entirely.
- `identify_product_from_image` — overall **deadline** bounds total time to ~`timeout_s`
  (was N×); success cached; total failure now emits `vision_extract_failures_total` +
  `degraded:true` (was a SILENT empty identity).
- `cv_provider.get_labels_and_text` — cached by `labels:{mode}`, only non-empty results.
- Metrics: `shopsquire_vision_cache_total{outcome}`, `shopsquire_vision_extract_failures_total`.
- Tests: `tests/services/test_vision_cache.py` (5) — repeat image ⇒ vision called once;
  namespacing; fail-open when disabled; failure ⇒ degraded + not cached.

**Tech-debt / spaghetti / silent-fails surfaced (follow-ups, NOT done here):**
1. **Duplicate vision pipelines** — `identify_product_from_image` and
   `cv_provider._ollama_labels_and_text` are two independent Ollama-vision
   implementations (different HTTP clients: `requests` vs `urllib`, different model
   fallback lists, different timeouts, different prompts). Should be ONE vision client.
   The shared cache mitigates the cost; it doesn't remove the duplication.
2. **`cv.py /analyze` is ~600 lines** of inline orchestration (ingest gate, sanitize,
   OCR, tier2, consistency, QR, security observer, persistence). Extract the analysis
   into a service; the router should just call it.
3. **Silent failures still present elsewhere:** `cv_provider` swallows vision errors and
   falls through with empty labels (no metric on that path yet); the recommend grounding
   path treats a degraded identity as "no anchor" without surfacing it to the shopper.
4. **No streaming** — biggest remaining UX lever: SSE so YOLO labels (~100ms) + QR/security
   (<6s) paint immediately and the LLM summary hydrates async (deferred — frontend+backend).
5. **`prewarm_demo_cache.py`** currently warms only the semantic (LLM prose) cache; extend
   it to run the demo IMAGES through identify + cv/analyze so the vision cache is warm too.

## 7. What to do next (prioritized)

1. **P0 fix** — decouple deterministic CV analyzers (QR/steg/phash) from the vision-LLM
   task in `/cv/analyze` so a model outage can't fail-open the security detectors.
2. **Bring up the full ShopSquire stack** (resolve the GridVerdict 5432/6379 port clash)
   and re-run this matrix with Ollama live → exercises vision grounding + LLM answers +
   the `[SECURITY]`/off-topic surfacing end-to-end.
3. **P1** — suppress the "previous shortlist?" NQE on first turn (no shortlist in state).
4. **P2** — tighten the PII redactor so product model numbers aren't redacted as phones.
5. Then resume the build roadmap: activate the Authorization Engine (shadow→active),
   wire `claim_grounding` into returns, schedule the exception-resolver task, Tier-2 loops.
