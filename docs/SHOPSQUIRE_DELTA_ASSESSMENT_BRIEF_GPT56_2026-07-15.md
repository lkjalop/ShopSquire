# ShopSquire — Delta Assessment Brief for GPT-5.6 (2026-07-15)

*Paste this to GPT-5.6. It asks GPT-5.6 to (a) verify this session's 5 commits, (b) find anything
missed, (c) assess the forward roadmap, and (d) pressure-test the plan to retire `recommend.py` /
`suggest()`. Everything is file:line-grounded so it can be checked directly.*

**Delta under review:** `git log 9bb9fd0..HEAD` — 5 commits, +1067/−6 lines, all with tests.
**Branch:** `wip/docker-real-env-20260213`. **HEAD:** `01c03e8`.
**Context docs:** `docs/SHOPSQUIRE_IMAGE_PREARCHIVE_REASSESSMENT_GAPCHECK_2026-07-15.md` (the image-lane
findings + gap-check) and `docs/SHOPSQUIRE_ARCHITECTURE_DEEPDIVE_V3_ARCHIVE_2026-07-14.md` (the
retirement map).

---

## 0. How this session started

The goal was to characterize the IMAGE lane **before** archiving `recommend.py`, using a live VLM
battery (`qwen3-vl:8b`) over the fixture set (valid / wrong / steg / PCI images) with procurement
journeys at changing unit quantities. That testing surfaced **4 live bugs independent of the
archive**, which were fixed. So the delta is: image characterization + those Tier-0 fixes.

**Image-lane findings (verified live, see the reassessment doc):** steg detector catches all 5 LSB
payloads (`steg_score=0.52` vs clean 0.16–0.33); **no shopper-facing PCI/PII bleed** (correct
warn-and-refuse posture); BUT (a) triage hangs >600s on 2–24 MP images (no size cap), (b) baseline
triage ~23s even on a 225² image (sequential stages), (c) the router model and VLM are the same
evictable local model → silent empty results post-triage, (d) unredacted SSNs echoed in the triage
response, (e) OCR (glm-ocr) hallucinates/loops on some images. A methodology note worth flagging: an
early "PAN bleed" alarm was a **false positive** — a greedy `\d{13,19}` regex matched floats like
`damage_score=0.16000000000000003`; the real card/SSN never reached a chat response.

---

## 1. The 5 commits — VERIFY each (bug → fix → file:line → test → what to probe)

### e9ede2e — `feat(vision)`: bound VLM/OCR image size
- **Bug:** `routers/vision.py` triage ran the VLM + OCR on full-resolution uploads; a 2–24 MP photo
  (normal e-commerce size) hung the model >600s. Ingest gate caps bytes, not decoded pixels.
- **Fix:** new `services/image_downscale.py` — cheap PIL header probe, decode-bomb reject
  (>30 MP / >25 MB → 413), downscaled COPY (≤1280px) for the model. `vision.py:~347-380` bounds and
  passes `vlm_content` to the provider (`:388`); **full-res `content` is preserved** for
  steg/adversarial/phash/forensics (`:406`, `:437`, `:704`). Live-proven: Dell 2000² 4.5s vs >600s.
- **Test:** `tests/services/test_image_downscale.py` (8).
- **Probe:** does downscaling to 1280px weaken **OCR** of small on-screen text (e.g. a real card)?
  Is 1280 the right budget? Is the steg path *definitely* still full-res on every branch (incl. the
  deep-OCR path `vision.py:~748` `run_risk_triggered_multicontrast_ocr`, which I did NOT bound)?

### dc2f784 — `fix(recommend)`: decision_mode truthfulness
- **Bug:** `services/recommendations.py:2205 maybe_llm_rerank` silently caught LLM failures and fell
  back to rule ranking, but the response still reported `decision_mode="agent_rerank"`.
- **Fix:** `maybe_llm_rerank` now sets `self.last_rerank_mode` (`llm|rules|rules_fallback|llm_empty_fallback`);
  `recommend.py:~9650` captures `_rerank_mode`, `~9788` reports `agent_rerank` only when the model
  actually reranked + exposes `rerank_mode` in `factor_telemetry`.
- **Test:** existing recommend/rerank suites green.
- **Probe:** any OTHER response field still asserting "agent" when it fell back? Is `last_rerank_mode`
  reset per call (stale-read risk if `maybe_llm_rerank` isn't called on a branch)?

### d9ac9df — `fix(recommend)`: honest zero-results for below-floor device queries
- **Bug:** "laptop under $50" answered *"Yes, $50 covers these laptops, starting from $8"* pointing at
  **Hand Sanitiser** — `recommend_budget_advisor.py` `_build_brand_budget_answer_v2` price-only check
  (`cheapest <= cap`) affirmed accessory/junk fallback as the device; the turn kept
  `assistant_message` + 13 junk results + spec disambiguation instead of the zero-results shape.
- **Fix:** new `_below_device_floor_verdict(constraints)` returns the honest "No — $X is short for a
  laptop" when the budget-tier floor is tripped, **skipping accessory queries** (sleeve/mouse/hub/…);
  wired after the gaming-specific check in `_build_brand_budget_answer_v2`. Separately,
  `recommend.suggest` applies a **shape switch after the post-pipeline** (message, no
  assistant_message/junk/disambiguation) **gated on the budget being in the CURRENT query text** — so
  an explain/follow-up that *inherited* a low budget keeps its prior shortlist.
- **Test:** `tests/services/test_budget_below_floor_honesty.py` (6); greens
  `test_recommend_contract_stability` zero-results; `test_zero_result_followup_does_not_overwrite_prior_shortlist` still passes.
- **Probe (highest-value):** the **query-text budget heuristic** (`\$\d|under \$?\d|…`) is the guard
  that distinguishes "fresh below-floor search" from "inherited-budget follow-up." Is it robust? Cases
  to break: "show me something under $50" (no device word), "cheaper options" (relative, no number),
  a genuinely-cheap device the catalog *does* stock, non-USD currency, "laptop for 50 dollars". Also:
  is `budget_tier_tags` (laptop-centric floor) ever wrong for a non-laptop device query?

### 01c03e8 — `fix(vision)`: redact raw SSN/PAN in the triage linked-artifact
- **Bug:** the linked-artifact scan extracted 19 SSNs and set the signals, but echoed the **raw**
  values into `linked_artifact.ssn_hits[]` → response + logs + traces + persisted event
  (detector-becomes-the-leak).
- **Fix:** `_redact_linked_artifact_pii` masks `ssn_hits → ***-**-1234`, card hits →
  `****-****-****-1234` **in place at the assignment boundary** (`vision.py:~603`) before `linked`
  propagates; detection signal preserved (`ssn_count`/type), last-4 kept for correlation. 4 unit tests.
  **Not yet confirmed live** (running API predates the change — needs a restart).
- **Probe:** are there OTHER PII echo paths not covered by masking at `:603`? (`support_complaints.py`
  + `admin_email_security.py:1007` also read `ssn_hits` — email path, out of this scope, but worth
  flagging.) Is masking at the boundary sufficient, or does `analyze_linked_artifact` persist raw
  bytes upstream?

### e3c59cf — `docs+tooling`: image-lane reassessment + live probes
- The reassessment/gap-check doc + `scripts/image_procurement_battery.py` + `scripts/pci_bleed_probe.py`.
- **Probe:** is the gap-check's archive-safety-net argument sound (esp. "convert xfail security pins to
  strict")?

**Cross-cutting asks:** any NEW silent swallow, regression, or contract drift introduced by these 5
commits? Any place a fix is a bandaid vs a root fix (esp. the zero-results query-text heuristic and
the downscale budget)?

---

## 2. Forward roadmap — assess & prioritize

Remaining Tier-0 (live bugs, pre-archive), NOT yet built:
- **Tier0d — triage stage parallelization**: run VLM ∥ OCR ∥ steg ∥ QR ∥ adversarial concurrently to
  hit a 5–10s budget (baseline ~23s is sequential). *Assess: safe ordering/dependencies between
  stages? which must stay sequential?*
- **Tier0e — narration UX**: one streamed surface for (1) a deterministic stage-progress "loading
  screen" (NOT an LLM call) and (2) severity-tuned security warn-and-continue **templated from the
  verdict category, never the payload** (feeding detected injection text to an LLM re-triggers it).
- **Ops (not code):** `OLLAMA_MAX_LOADED_MODELS=2` so the router (`qwen3-vl:8b`) and `glm-ocr` coexist
  in 12 GB and the router stops getting evicted (the silent-empty root cause).
- **Known gaps to fold in:** `pci_card_exposed=None` for a printed card (add a Luhn-checked PAN
  detector on OCR text); bound the deep-OCR full-res path; OCR-confidence gate for the glm-ocr looping.

*Assess: is Tier0d/e the right next priority, or should the characterization net + IMAGE V2 come
first? What ordering minimizes rework?*

---

## 3. THE MAIN ASK — pressure-test the plan to retire `recommend.py` / `suggest()`

**Scope:** `routers/recommend.py` = **12,349 lines** (the target). `suggest()` is ~7k of them. The
33 legacy-only `recommend_*` services + the chat→HTTP loopback go with it. (`admin.py` at 4,169 lines
is unrelated — not part of this retirement.)

**The plan we intend to execute (assess it):**
1. **Dispatch-hoist (A step-0):** the V2 facade is dispatched *from inside* `suggest()`
   (`recommend.py:4524`), so it's both router and fallback engine. Rename the body `_legacy_suggest()`,
   route = `guard → facade-first → legacy fallback`. Prerequisite to any shrink.
2. **Characterization net:** golden I/O per lane + **convert the `xfail` security pins to strict**
   (the `text_only` image-wipe pin is `xfail(strict=False)` today — a refactor could silently delete
   the wipe) + endpoint-contract tests. The now-green `test_recommend_contract_stability` is one brick.
3. **Lane migration to V2:** SEARCH/CART/INVENTORY ✅ done; POLICY/FAQ 🟡 small; SUPPORT_CLAIM 🟠
   extract; **IMAGE 🔴 the critical path — no V2 impl, facade hard-refuses at
   `recommendation_facade.py:455`; rebuild preserving the security posture + folding in the size-cap**;
   PROCUREMENT/RFQ 🟡 **deliberately KEPT legacy** (advise-only V2 regresses RFQ).
4. **Promotion ladder (USER-gated):** relevance labels → soak → `RECOMMEND_CORE_MODE` shadow → canary
   → primary.
5. **Mechanical teardown:** relocate the **9 sibling endpoints** living in `recommend.py` (they die
   with the *file*, not the function), repoint ~40 tests importing internals, kill the chat loopback
   (`chat.py:1855/1995`), migrate 4 frontend callers off `/suggest`, then delete.

**Estimate:** ~3–5 weeks focused + ~1–2 weeks canary; **IMAGE is the critical path**.

**Questions for GPT-5.6:**
- Is this sequence right, or is there a cheaper ordering? What's genuinely on the critical path?
- Is "keep PROCUREMENT legacy" defensible, or does it leave a permanent legacy island that blocks the
  file delete? (i.e., can the file ever be deleted if a lane stays legacy — or does PROCUREMENT need
  its own home?)
- What behaviors are most at risk of silent loss in the delete that the characterization net as
  described would MISS?
- For the IMAGE V2 rebuild: given the findings (degraded happy-path, load-bearing security, size-cap),
  what's the minimal contract the V2 image lane must satisfy to be at parity?

## 4. Labeling ask for GPT-5.6

Please label, per the 5 commits: **{correct | correct-but-incomplete | wrong | risky-bandaid}**, and
for any `wrong`/`risky`, the exact input that breaks it. Then rank the **top 5 things to do next**
toward retiring `recommend.py`, and name the **single biggest risk** in the retirement plan.
