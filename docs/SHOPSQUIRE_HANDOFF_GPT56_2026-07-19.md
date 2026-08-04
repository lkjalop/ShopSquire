# ShopSquire — Handoff & Delta Assessment for GPT-5.6 (Sol)
**Date:** 2026-07-19  **HEAD:** `629df6a`  **Tree:** clean, all work committed.
**Purpose:** hand off the V2-retirement arc at a token-limit pause. Everything below is
measured/committed unless marked PROPOSED or USER-GATED.

---

## 0. TL;DR — where we are

- **V2 core is build-complete and the promotion quality-gate is ONE lane-alias away from green.**
- **The "latency blocker" was a MISDIAGNOSIS — it is SOLVED.** It was VRAM eviction, not model
  speed. Warm+pinned, the CURRENT `qwen3:14b` router routes at **p95 5.2s** through the full
  replay path (gate ≤8s). No model downgrade, no prompt trim needed. (Prompt-trim was tested and
  REFUTED: 836 tok=4.9s vs 377 tok=5.6s — no gain.)
- **Only one promotion gate fails: `fallback_rate 0.037 > 0.01`** — traced to a single
  deterministic cause (below). Everything else is green.
- **Remaining path to archive `recommend.py`/`suggest()` is CALENDAR, not code:** seal labels
  (USER) → soak → canary ladder → delete. Plus IMAGE-lane V2 rebuild (the one true 🔴 blocker).

---

## 1. Delta since your last review (`c08b325 → 629df6a`)

### Latency — the big correction
- `73584a7`, `8dbf17e`, `629df6a`: measured that ~100% of the turn is the single router model
  call, THEN proved the 11–13s spikes were **VRAM eviction** (vision `glm-ocr` evicting the
  router), not model speed. Warm through `route_turn`: qwen3:14b **p95 6.2s**, qwen3-vl:8b 5.1s —
  both PASS. Full replay warm: **p95 5219ms, timeout_rate 0.0.**
- Fix committed: `629df6a` startup preload thread pins the router (off under `APP_ENV=test`).
  **Ops pairing (USER machine): `OLLAMA_MAX_LOADED_MODELS>=2`** so router + VLM coexist.
- **⇒ The P1 "pick a router model" decision you flagged is now NON-BLOCKING** — the current model
  hits the gate. (Corrected in memory: was "latency is a MODEL choice"; it's a SERVING choice.)

### Money-path P0s (mine, all committed + tested)
- `b3d233f` durable webhook inbox/outbox + ledger idempotency (P0-1);
  `3801f37` dedup refund_settled on provider_ref (P0-1c). Layers on top of your M1–M5.

### Security P0s (mine)
- `31a7e27` vision raw/sanitized/bounded byte separation (steg+phash on raw, VLM on downscaled,
  QR/adversarial on raw) + recursive PII redaction; `01c03e8` raw SSN/PAN redaction at triage;
  `6a48e53` internal-service egress allowlist (SSRF); `e6e6a13` catalog-spec injection-echo
  neutralize + text_only-wipe strict pin; `e9ede2e` VLM/OCR image size-bound (downscale-for-VLM,
  full-res-for-steg, reject >30MP/25MB — fixes the >600s hang on normal e-commerce image sizes).

### Your batch (52 files) — VERIFIED + committed in 8 reviewable chunks
- All 3 of your P0s resolved: hippograph tenant-leak FIXED (`55f2e46` — `_default_hippograph`
  now forwards `tenant_id`; was a cross-tenant leak on a SUPPLIER-OUTBOUND artifact);
  market-intel self-contradiction FIXED (`e3f0fa2` — inventory expansion now requires UPWARD
  demand direction AND a real shortfall, not any bare `demand_shift`); narration-band verified
  fail-CLOSED by the `ungrounded_price` guard → downgraded P0→P1.
- Chunks `dc4ee54` (V2 procurement advice + draft-retry worker), `9a2e000` (total-vs-perunit
  budget grammar + workload capability filtering), `d217529` (recommend budget-cap + memory
  reset), `a63b4d5` (tenant-scoped attribution/decision-log/evidence), `bed089e` (frontend
  cart/right-panel/image-panel canonical rendering), `40295f8` (demo/replay/image tests).
- Persona fix `e2b3743`: "gaming development" now classifies **developer**, not consumer gamer
  (the screenshot bug) — regex negative-lookahead `\bgaming\b(?!\s*dev)`.

---

## 2. THE ONE OPEN GATE — `fallback_rate 0.037` (deterministic, ~10-line fix)

**Case:** `procurement_bulk:0` — *"we need 25 laptops for our new office, can you do a bulk quote?"*
**Root cause (temp=0, reproducible):** the qwen3:14b router emits `lane="BULK"`. `BULK` is NOT in
the closed lane vocab `{CART_MUTATE, COMPARE, EXPLAIN, FILTER, INVENTORY, OFF_CATALOG,
POLICY_QUESTION, PROCUREMENT, SEARCH, SUPPORT_CLAIM}`. The clamp at
`turn_router.py:511` correctly rejects the out-of-vocab lane → `DEFAULT_DECISION` (SEARCH,
source=default) → counts as a fallback AND routes the bulk-quote to the wrong lane (should be
PROCUREMENT). The model's intent is unambiguous; only its label is out-of-vocab.

**PROPOSED fix (doctrine-aligned: clamp/alias, not a new regex parser):** add a small lane-alias
map applied BEFORE the reject, e.g. `{"BULK":"PROCUREMENT","QUOTE":"PROCUREMENT",
"RFQ":"PROCUREMENT","BULK_QUOTE":"PROCUREMENT"}`. TDD: RED test asserting the bulk-quote query
routes PROCUREMENT (not SEARCH/default) → add alias → GREEN → re-run
`python tests/characterization/shadow_replay.py` and confirm `fallback_rate → 0.0`,
`model_modes.default → 0`. NOTE: PROCUREMENT is a non-canary lane (delegates to legacy), so this
also correctly routes the bulk buyer to the mature RFQ path instead of a dead SEARCH.

**Sample-size caveat to record:** the gate is `fallback_rate ≤ 0.01` but the corpus is 27 cases,
so a SINGLE fallback = 3.7%. The alias fix takes it to 0. Consider whether the gate should be
`count ≤ 0` on small corpora rather than a rate.

---

## 3. Full promotion scorecard (replay warm, `629df6a`)

| Gate | Value | Threshold | Status |
|---|---|---|---|
| p95_latency_ms | 5219 | ≤ 8000 | ✅ |
| timeout_rate | 0.0 | ≤ 0.01 | ✅ |
| empty_rate | 0.0 | ≤ 0.15 | ✅ |
| unauthorized_rate | 0.0 | ≤ 0.0 | ✅ |
| constraint_satisfaction | 0.792 | ≥ 0.7 | ✅ |
| precision@10 / ndcg@10 | 0.78 / 0.879 | ≥ 0.6 | ✅ |
| diversity | 0.659 | ≥ 0.3 | ✅ |
| labeled_coverage | 0.3125 | ≥ 0.3 | ✅ (5 labels exist; thin) |
| classified_shown_rate | 1.0 | ≥ 0.98 | ✅ |
| **fallback_rate** | **0.037** | ≤ 0.01 | ❌ **§2** |

`gate_match_rate 0.5833` and the 10 BLOCKER/13 MAJOR "divergences" are the v1-vs-v2 DIAGNOSTIC
census (by design NOT a promotion oracle) — each is either a v2-correct behavior to tag
`known_wrong`, or a v2 gap. e.g. `offcatalog_a100 off_catalog→no_results` is v2 doing the RIGHT
thing (refusing) vs v1's known-wrong. These need triage but do NOT block promotion.

---

## 4. What is needed to ARCHIVE `recommend.py` (~12.3k ln) + `suggest()`

Ordered critical path (unchanged shape, latency now off it):

1. **USER-GATED — seal relevance labels** (`tests/golden/relevance_labels.json`, keyed
   `case_id:turn`). 5 exist (coverage 0.3125, just clears). Thin — more labels harden the gate.
   This is the ONLY human-blocking item for the RECOMMEND lanes.
2. **Fix §2 fallback** (alias clamp) → last gate green.
3. **P-deploy — pgvector/`product_embeddings` migration proof** (mechanical; retrieval is BOW
   today, semantic path needs the embedding table live).
4. **Soak** — re-run your 200-turn stateful synthetic soak against the current HEAD; confirm no
   regression (prior soak 39/40, zero budget/subject/persistence/self-complement).
5. **Canary ladder** — `RECOMMEND_CORE_MODE` shadow→primary for `CANARY_LANES =
   {SEARCH,FILTER,COMPARE,EXPLAIN,OFF_CATALOG}` only. PROCUREMENT stays legacy (advise-only V2
   would regress RFQ — decision `c08b325`).
6. **Dispatch-hoist + char-net** — the facade is dispatched INSIDE `suggest()`
   (`recommend.py:4566-4575`); hoist it above, flip the characterization xfail→strict pins, then
   delete. **Do not delete a behavior not first captured as a failing test.**
7. **IMAGE V2 rebuild = the one true 🔴 blocker to full retirement** (see §6).

---

## 5. Per-domain status (your explicit questions)

### Text-based security — ✅ strong, verify-live
Injection echo neutralized (`e6e6a13`), text_only-wipe strict-pinned, SSRF egress allowlist
(`6a48e53`), SSN/PAN redaction at triage boundary (`01c03e8`). **VERIFY:** the SSN redaction
(`vision.py:603`) was NOT confirmed against a LIVE API restart last session — needs a live probe
(`scripts/pci_bleed_probe.py`). PAN "bleed" earlier was a FALSE positive (greedy `\d{13,19}`
matched a float) — real SSN/PCI never reached the shopper response.

### Image-based security — ✅ posture solid, ⚠️ happy-path is the blocker
Steg (numpy, ~2s/4MP) + QR/adversarial on RAW bytes, VLM on downscaled copy, size-bound rejects
>30MP/25MB (`e9ede2e`/`31a7e27`). All 5 steg payloads detected (score 0.52 vs clean 0.16–0.33).
**The blocker is NOT security — it's that the IMAGE happy-path is unreliable** (router==VLM share
12GB → eviction → silent 0-products). IMAGE V2 rebuild must PRESERVE this security posture + FIX
the happy path + KEEP the size-cap. Harness: `scripts/image_procurement_battery.py` (paused
mid-battery last session — 8 small images left to run).

### NLP routing — ✅ measured good, one alias gap (§2)
Closed-vocab router (model proposes → clamp → guard → deterministic fallback). Live-proved:
cyberpunk/valorant/accessory FIXED, refuses A100/car/insulin. Persona gaming-dev fixed. Gap = the
`BULK` lane alias (§2). `use_case=None` display polish still open (cosmetic).

### Procurement journey — ✅ legacy owns it, V2 advises-only
Legacy RFQ path is mature (PR→CASE→PO→GR/INV, 2 irreversibility gates, human-only send). V2
PROCUREMENT lane is ADVISE-ONLY (bulk economics + draft-for-review). **Standing invariants
INTACT:** `FULFILLMENT_SUPPLIER_TRANSPORT=sandbox`, `FULFILLMENT_AUTONOMOUS_RFQ=0`, human-only
supplier send. §2 fix routes bulk buyers correctly INTO this path. **VERIFY via clickthrough:**
the quantity-permutation battery (changing unit counts → correct bulk tiering + budget
total-vs-per-unit grammar, `9a2e000`).

### Shopping-cart changes — ✅ tenant-scoped, verify-live
Cart identity = (tenant, customer) threaded everywhere (`a63b4d5` + prior tenant_context work);
whole-op authorization by the shopper's own words (`c8e9c85`); swap/deficit-reorder built. Cart
regression tests still open (P1-quality, mine). **VERIFY via clickthrough:** add → swap →
deficit-reorder → confirm; tenant isolation (Tenant A cart invisible to Tenant B).

### Drafted supplier email — ✅ human-gated, verify-live
Draft-for-review only; nothing sent autonomously. Draft-retry worker added (`dc4ee54`). Tenant
leak on the draft's hippograph evidence FIXED (`55f2e46`). **VERIFY via clickthrough:** trigger a
bulk quote → see the DRAFTED email at cart-confirm (NOT chat) → confirm the RFQ card shows the
right supplier + no cross-tenant evidence in the draft body.

---

## 6. Browser clickthrough checklist (what to verify by hand)

Run `./start_demo.ps1` (api :8080, frontend :5173, admin :3001, Ollama :11434). Set
`OLLAMA_MAX_LOADED_MODELS=2` first so the router isn't evicted.

1. **Latency felt** — first chat turn after cold start should be ~5–6s, not 12s (preload thread
   warms the router). Subsequent turns steady ~5s.
2. **Recommend lanes** — "gaming laptop under $2000", "cheaper ones", "why is the first better?",
   "compare the top two" → products render, follow-ups keep the subject, no React object-child
   crash (`377e894`).
3. **Gaming-development persona** — "laptop for gaming development" → developer workstation specs,
   NOT consumer gaming, no Apple, per-unit ≤ budget/qty (the two screenshot bugs).
4. **Bulk quote** — "we need 25 laptops for our new office, bulk quote?" → currently routes SEARCH
   (the §2 bug); AFTER the alias fix → PROCUREMENT/RFQ card + drafted supplier email at confirm.
5. **Image upload** — normal photo (~2–8MP) returns in reasonable time (not >600s hang); oversize
   (>30MP) → reject-with-guidance; steg/QR-hostile image → security narration + still answers
   ("gaming loading screen" UX the USER asked for — short LLM narration, still tries to help).
6. **Cart + tenant** — add/swap/deficit-reorder; confirm a second tenant can't see the first's
   cart.
7. **Security narration UX** — when a security element triggers, a SHORT llm narration should tell
   the user while still attempting the answer (USER's explicit UX ask — verify it's wired, not
   just fail-closed silence).

---

## 7. What to hand GPT-5.6 to VERIFY / assess

1. **§2 alias fix** — review the PROPOSED lane-alias approach; is aliasing `BULK/QUOTE/RFQ →
   PROCUREMENT` the right clamp, or should the prompt enumerate it instead? (doctrine: clamp
   near-misses, don't add regex.)
2. **Re-run the 200-turn stateful soak** on HEAD `629df6a` — confirm no regression from the batch
   commits + latency/security P0s.
3. **Diagnostic census triage** — the 10 BLOCKER / 13 MAJOR divergences (§3): for each, decide
   v2-fix vs tag-`known_wrong`. This is the "divergences are the deliverable" work.
4. **Latency correction sanity-check** — confirm the eviction diagnosis (preload + MAX_LOADED=2)
   and that no honest model-speed problem remains at the p95 gate.
5. **Live security confirmations** — SSN-redaction against a live API restart; the paused image
   battery (8 small images); the "gaming loading screen" narration UX.
6. **IMAGE V2 rebuild plan** — the one 🔴 blocker to full retirement: happy-path reliability +
   preserve security posture + size-cap. Needs a design.

---

## 8. Standing constraints (DO NOT violate)
`FULFILLMENT_SUPPLIER_TRANSPORT=sandbox`; `FULFILLMENT_AUTONOMOUS_RFQ=0`; human-only supplier
send. Never modify the user's `.env` model config; secrets → `.env`, never chat. Never collect
credentials/card data in chat (PCI-DSS). Commit/push only when the user asks. `RECOMMEND_CORE_MODE`
stays shadow in prod until the canary ladder. Don't set ops flags silently (`INTERNAL_SERVICE_ALLOWLIST`,
`OLLAMA_MAX_LOADED_MODELS`) — recommend to the user, their machine.
