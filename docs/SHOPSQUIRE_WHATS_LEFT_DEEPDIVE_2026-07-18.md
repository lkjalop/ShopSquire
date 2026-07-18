# ShopSquire — What's Left: Deep Dive (2026-07-18)

*Grounded in the current tree (HEAD after 10 commits this session). Answers: exactly what remains to
retire `recommend.py` (12,396 lines) / `suggest()` and reach a defensible production state, with each
item's steps, "green" definition, effort, owner, and dependencies.*

---

## 0. TL;DR — the whole thing funnels through one user action

The P0 correctness/security tier is **done and green** (money idempotency, image byte-routing, SSRF
allowlist, catalog-injection echo, text_only-wipe pin). What remains is **one dependency chain**:

```
YOU review the 8 labels ─► the quality gate becomes real ─► I pick the router prompt+model that
passes BOTH latency & quality ─► canary ─► (parallel) IMAGE V2 rebuild ─► delete recommend.py
```

Nothing else I own is blocked. The critical path's long pole is the **IMAGE V2 rebuild**; the
critical *unblock* is your **label review**.

---

## 1. Where we are (measured, not asserted)

| Track | State |
|---|---|
| P0 money / image / SSRF / injection / wipe | ✅ done + green (10 commits, TDD red→green) |
| P1 latency | ✅ **diagnosed**: prefill-bound — a **~1,681-token router prompt** every turn; models: qwen3:14b ~13s (best routing) / qwen3-vl:8b ~8.6s / llama3.2:3b ~7.7s (poor routing). `num_predict` barely matters. |
| P2 labels | ⏳ **8 draft labels, human-review pending** — the blocker |
| P3 promotion | after P1+P2 |
| P4 archive | last; facade still dispatched *inside* `suggest()` (`recommend.py:4566-4575`); facade still refuses image (`recommendation_facade.py:454`) |

---

## 2. Deep dive — each remaining item

### A. P2 — Human-review the 8 relevance labels · **YOU** · ~2–4 hrs · **THE UNLOCK**

- **What:** `tests/golden/relevance_labels.json` has 8 draft cases (`labeled_by:
  codex-independent-review`, `review_status: independent_draft_requires_human_second_pass`).
- **Why it gates everything:** NDCG@10 / precision@10 are computed *against these labels*. Until a
  human confirms them, every quality number is measured against an unverified spec — so you can't
  prove V2 ≥ V1, and you can't compare candidate router models on quality. It is simultaneously the
  quality gate *and* the tiebreaker for the model decision.
- **Steps:** for each of the 8 cases, confirm/correct the `{sku: grade 0–2}` map (2 = ideal, 1 =
  acceptable, 0 = wrong), record reviewer identity + any disagreement with the draft, flip
  `review_status` and set `human_reviewed_by`.
- **Green:** `review_status != independent_draft_requires_human_second_pass`; `labeled_coverage ≥
  0.30` still holds (it's 31.25% now — 8 cases). *Optional but valuable:* label more of the 25-case
  corpus to widen the quality gate's reach.

### B. P1 — Router prompt-trim + model config · **ME** (after P2) · ~1–2 days

- **The measured problem:** latency is **prefill-bound** — the ~1,681-token router prompt dominates,
  so `num_predict` is a non-lever and every pure model-swap trades routing quality (14B routes best
  but is ~13s; 3B hits the gate but routes badly — wrong lanes, empty requirements).
- **The work:** (1) **trim the router prompt** ~1,681 → ~700 tokens (drop redundant taxonomy dumps /
  few-shot examples / verbose instructions) so *every* model speeds up without getting dumber;
  (2) pick the model (likely qwen3-vl:8b or qwen3:14b *with* the trimmed prompt); (3) run the shadow
  replay per `{prompt × model}` config; (4) choose the one that passes both gates.
- **Green:** **3 consecutive sealed replays** with **p95 < 8s AND timeout < 1% AND** ndcg≥0.60 /
  precision≥0.60 / constraint-sat / unauthorized=0. (Can only be *proven* after P2 — the quality half
  needs reviewed labels.)
- **Risk:** trimming the prompt could regress routing → the shadow replay + labels catch it. This is
  why B strictly follows A.
- **Production note (separate track):** 100s-concurrent needs a batching inference server (vLLM/TGI)
  + replicas, not Ollama — the single-turn 8s gate ≠ latency-under-load.

### C. IMAGE V2 rebuild · **ME** · ~1–2 weeks · **CRITICAL PATH for the delete**

- **Why it's the pole:** IMAGE is the one lane with no V2 implementation — the facade hard-refuses
  image (`recommendation_facade.py:454`), and the legacy image lane is threaded through ~20
  conditionals in `recommend.py`. `recommend.py` cannot be deleted while it's the only thing that
  serves image.
- **What must be preserved** (now characterized *and test-pinned* this session, which is why the
  pre-archive testing mattered): steg detection, **QR-external → text_only wipe** (now a *strict*
  pin), PCI/SSN no-bleed, off-domain no-hijack, damage→support routing, and the **size-cap**
  (downscale-for-VLM / full-res for steg+QR+adversarial).
- **The work:** build an image lane inside `recommendation_core/` that (1) runs the security posture
  (reuse `image_feature_gate`, `steg_detector`, the QR/PCI path), (2) does CV/vision identification
  (reuse the extracted `recommend_vision_stage` / `recommend_image_*` services), (3) grounds
  retrieval on the identified product — then flip the facade's image refusal to serve.
- **Green:** this session's image characterization + security tests pass on the V2 lane; parity with
  legacy on the golden image corpus (valid identify, wrong no-hijack, steg/PCI/QR detect + no bleed).

### D. P3 — Promotion (soak → canary → money-staging) · **ME + YOU** · ~1–2 weeks calendar

- **Shadow soak:** 200–500 persona/procurement/image/cart turns; gates hold; no unauthorized
  products, no money regression.
- **Canary ladder:** `RECOMMEND_CORE_MODE` 1% → 5% → 25% of live traffic, each rung holding the
  gates for a sustained window before widening (YOU own each go/no-go).
- **Money staging proof:** apply the webhook/refund migration in disposable Postgres CI; real Stripe
  test-mode webhook **redelivery / provider-crash** tests; derive tenant identity from authenticated
  middleware, not raw headers.

### E. P4 — Archive mechanics · **ME** · ~2–3 days once A–D are green

1. **Dispatch-hoist** (`recommend.py:4566-4575`): today `if _core_payload is not None: return
   _core_payload` sits *inside* `suggest()`. Rename the 7k-line body `_legacy_suggest()`; make the
   route `guard → facade-first → _legacy_suggest() fallback`. Until this, the file can't shrink.
2. **Characterization net:** convert the remaining **10 xfails** to strict where they pin real
   behavior (I converted the text_only wipe this session; triage the rest — some are cosmetic
   status-code/env, some real like the pending spec-notes-in-followup edge).
3. **Relocate the 10 sibling endpoints** living in `recommend.py` (`/checkout_upsell`, `/narration`,
   `/why_product`, …) — they die with the *file*, not the function.
4. **Repoint ~40 tests** that import module internals (`_classify_turn_intent`, `_with_trace`, …).
5. **Kill the chat→HTTP loopback** (`chat.py:1855/1995`) — call the facade/handler directly.
6. **Migrate 4 frontend callers** off the `/suggest` contract.
7. **`git rm`** `recommend.py` + the 33 legacy-only `recommend_*` services (keep the 5 keepers +
   PROCUREMENT, which stays legacy by design).

---

## 3. Smaller / parallel items (not on the critical path)

- **Ops flags (YOU, 1 min each):** `INTERNAL_SERVICE_ALLOWLIST=127.0.0.1:11434,localhost:11434`
  (activates P0-3); `OLLAMA_MAX_LOADED_MODELS=2` (stops the router/OCR VRAM eviction).
- **PROCUREMENT stays legacy** — a deliberate keeper (advise-only V2 regresses RFQ). Open question:
  it must get its own home (extract to a `procurement` router) or it re-pins `recommend.py`. Resolve
  before the final `git rm`.
- **The 10 xfails** need a triage pass (real-behavior → strict; cosmetic → leave/fix).

---

## 4. Sequencing + effort

| # | Item | Owner | Effort | Gate to next |
|---|---|---|---|---|
| 1 | Review 8 labels | **YOU** | 2–4 hrs | quality gate real |
| 2 | Prompt-trim + model config | ME | 1–2 days | p95<8s **and** quality gates (3 sealed replays) |
| 3 | IMAGE V2 rebuild | ME | 1–2 wks | image characterization tests pass |
| 4 | Soak → canary → money-staging | ME+YOU | 1–2 wks cal | gates hold on live traffic |
| 5 | Archive mechanics + delete | ME | 2–3 days | all above green |

**Critical path:** `labels (you) → config (me) → IMAGE V2 (me, long pole) → canary → delete`.
**Rough total:** ~3–4 weeks of my engineering + ~1–2 weeks canary calendar, unblocked by your label
review. PROCUREMENT-home + the xfail triage are the two "don't forget" items before `git rm`.

## 5. The definition of DONE (one runnable go/no-go)

Retirement is green when a single script exits 0:
```
char-net green (security pins STRICT) · contract suite green · quality gates over REVIEWED labels ·
safety gates (unauthorized=0, PCI/SSN no-bleed, steg/QR detected) · p95<8s & timeout<1% (3 sealed
replays) · money staging (migration + Stripe redelivery) · canary held 1%→5%→25%
```
Today: safety ✅, contract ~✅, char-net partial (2 of the security pins now strict), latency
diagnosed (needs the config), quality blocked on your labels, canary/money-staging downstream.
