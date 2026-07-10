# ShopSquire — Comprehensive Codebase Deep-Dive & Roadmap (2026-07-10)

> Self-contained honest assessment for external re-evaluation (GPT-5.6). Written from a 4-agent
> parallel sweep of the actual code (not memory), every claim evidence-backed with file:line.
> The brief: what we do well, what needs work, what's missing/stub/demo, the state of
> `suggest()`/`recommend.py`, and **how to improve the agnostic model's "brain" and decrease
> deterministic brittleness.** No flattery — the goal is a real plan.

---

## 0. Executive verdict (one paragraph)

ShopSquire is a **genuinely engineered, governance-first agentic commerce platform** whose
*safety architecture is real and load-bearing* — the claim guard (on by default, fail-closed),
the bounded-autonomy action gate, the layered human-gated supplier-send, and the
narrator-over-evidence anti-hallucination design all hold up under inspection. **But two hard
truths dominate**: (1) **the model barely makes any decisions** — every genuinely intelligent
model use (LLM planner, multi-intent binding, evidence orchestrator) is flag-gated OFF by
default and clamped to gap-filling; the "agentic orchestrator" that would let the model
decompose a query and select tools **is not built**; the real decision-making is a large,
brittle regex/keyword surface (the "add-a-regex treadmill"). (2) **The headline "market
intelligence / adaptive AI" subsystems do not run in the shipped config** — market analysis,
pipeline, hippograph, orchestrator, ranking-nudge, storefront-emphasis, and even
`DECISION_LOG_WRITES_ENABLED` are all OFF in `config/feature_flags.json`; the demo is
seeding-and-synthetic-replay-real. The platform is **demo-real and safety-real, not
production-real or intelligence-live.** The path forward is not more rules — it is a
**model-judged selection layer** (propose into a closed vocabulary → clamp → guard) plus
flipping the built-but-dark value chain on with calibration.

---

## 1. Scale & metrics (measured 2026-07-10)

| Metric | Value |
|---|---|
| Backend LOC | ~211,554 across 776 `.py` files (375 services, 108 routers) |
| `recommend.py` | 12,281 LOC; `suggest()` = **7,245 lines** (4341–11586) |
| `chat.py` | 2,795 LOC |
| Tests | 805 test files |
| `except Exception` in recommend.py | **302** — but only **15** `record_partial_failure` calls (~95% of catch sites unobserved) |
| Distinct `*_ENABLED` flags | 317 |
| LLM call sites | 153 (most gated/shadow) |
| Service-level regex sites | 436 `re.*` across 86 files (heaviest: query_decomposer 44, recommendations 32, nlp_search 30, intent_decomposer 25) |

---

## 2. What we do WELL (evidence-based, not flattery)

1. **The anti-hallucination design is real and holds.** The model narrates; deterministic code
   decides; the claim guard fences it. `product_claim_guard.guard_enabled()` defaults ON
   (`COMMERCE_NARRATION_GUARD="1"`); ungrounded prose → deterministic fallback; a guard *crash*
   → `{"guard":"error"}` (never certifies). Numeric (not substring) price/spec membership after
   documented bypass audits. Async swap applies the *same* guard before showing prose.
   **Verified: the model does not pick products, set budgets, or route — it explains.**
2. **Bounded autonomy is genuine and default-safe.** `adaptive_action_gate` (kill switch +
   allowlist + confidence + durable audit; an ALLOW that can't persist → `DENY(audit_unavailable)`).
   Autonomous supplier RFQ is layered (KYV-trusted, claim-safety, confidence≥0.8, value/qty caps,
   rate-limit fail-closed) and **OFF by default** → everything escalates to a human.
3. **The agnostic-core mechanism is real for the main path.** `platform/store_profile.py` +
   `profile_slot()` is a clean ContextVar resolver; `pharmacy.json`/`fashion.json` are fully
   shaped (use-case maps, NQE packs, capabilities) and reach the ranking/NQE path.
4. **The guard/evidence discipline the recent arc built is solid**: capability registry (honest
   "we don't offer X" for infinite phrasings), knowledge pool + workload-fit + Steam facts as
   *guard-legitimate* evidence, provenance-scoped guard, 9 mute layers sealed, async brain
   reaching the buyer with clean content (post-PX0).
5. **The best real model use — multi-intent binding** (`intent_decomposer._bind_with_llm`) makes
   relative language computable ("halve it" with prior qty 20 → 10) that regex fundamentally
   can't, with every number re-authorized by the deterministic grammar. This is the *template*
   for the brain shift below. (Sadly default-off.)
6. **Vision reasoning is genuine model perception** (`vision_reasoning.analyze_product` — brand/
   spec/damage from pixels, no deterministic substitute).

---

## 3. THE CENTRAL FINDING — the brain barely decides

**Almost every real decision in the buyer path is made by deterministic code.** The model's one
always-on job is narration (read-side). Categorization of the actual decision-making:

### 3a. Where the model *could* decide — but is OFF/clamped
- **LLM planner** (`llm_planner.py`, wired recommend.py:4549): `LLM_PLANNER_ENABLED` default `0`.
  Only fires on ≥4-word, <0.45-confidence residual; output whitelisted to 6 intents, category
  clamped to profile `primary_types`, use-case clamped to profile `use_cases`, **only fills gaps
  rules missed.** A vocabulary-clamped gap-filler, effectively dead in prod.
- **Multi-intent LLM binding** (`intent_decomposer._bind_with_llm:409`): `MULTI_INTENT_LLM_BINDING_ENABLED`
  default off. The *best* real model use — but default-off.
- **"Complexity scoring"** (`llm_provider.score_query_complexity:132`) is a ~15-signal keyword/regex
  scorer, NOT the model deciding — it picks a *model tier*.
- **Intent routing** Ollama summary is **shadow-only** (10% sample, off the hot path).
- **NQE question selection** is **fully deterministic** (profile packs + ~15 hook filters).

### 3b. Where the model only narrates (design holds) — §2.1 above.

### 3c. Where deterministic rules decide — THE BRITTLENESS (the treadmill)
Every one is a "screenshot → add a token" surface; the scar comments are the treadmill made visible:

| Surface | Location | Failure mode |
|---|---|---|
| **Turn-intent** (the epicenter) | `chat.py:303` `_classify_turn_intent` — ~30 substring checks | `"only " in q` → FILTER zeroed retrieval → needed bespoke `_is_deficit_reorder_query` patch |
| use_case detection | `use_case_advisor.match_use_case_from_query:75` | miss → generic ranking, re-ask |
| budget parsing | `recommend_budget_parsing:88` + `budget_grammar` | "nothing over 2000" read as FLOOR (inverted); over-cap leaked |
| brand resolution | `chat.py:396` — 8 hardcoded brands | non-listed brand → None; electronics-only |
| off_catalog_gate | `off_catalog_gate.py:19` — one regex/class | "A100-equivalent laptop" over-blocks |
| game/software | `flows/nqe.py:101` — 15 games/11 sw hardcoded | unknown title → no spec floor |
| capability topics | `capability_registry.py:29` | `\bleas\w+` matched "at **leas**t 16GB"; `20000mAh`→$20k |
| support-claim | `answer_quality.is_support_claim:71` | miss → warranty Q hijacked to photo-triage |

### 3d. THE ORCHESTRATOR GAP — confirmed NOT built
`docs/AGENTIC_ORCHESTRATOR_ARCHITECTURE_2026-07-08.md` specifies decompose → **LLM-selects-tools**
→ scatter-gather → synthesize. **Grep verdict: `ORCHESTRATOR_LANE_ENABLED` = zero hits; no
`cart_mutate` tool, no synthesize loop, no LLM-emitted tool plan.** `evidence_orchestrator.py`
is a decent scatter-gather *substrate* but `select_legs:43` is a **deterministic if-ladder**
(flag-off). The `allowed_tools` hits are static MAESTRO security fences, not model selection.
**There is no code where the model decomposes a query and selects which sources to call.**

---

## 4. What's REAL vs DEMO vs DARK (stubs/integration census)

### 4a. Stubs that LOOK real but aren't (ranked by how misleading)
1. **PayPal is hardcoded to `SandboxEnvironment` in code** (`payments.py:88-91`) — needs a *code
   change*, not a credential swap, to go live. Most misleading item.
2. **OOB payment-change MFA silently doesn't deliver** (`security/oob_verification.py:43,105`) —
   `_delivery_backends` is an empty dict; `register_delivery_backend` is never called → token
   "sent" but delivered nowhere.
3. **Voice ASR returns a canned `"Voice input received."`** without `OPENAI_API_KEY`.
4. **Supplier transport `sandbox` reports `status="sent"` while transmitting nothing** (default).
5. **SendGrid/SES "send" writes `dump/email_dev.log` and returns `ok:True,dev:True`** without keys.
6. **ERP/EDI default is fixture-backed** (`erp_edi_stub.json`).

### 4b. Built-but-DARK (flag-off in shipped `config/feature_flags.json`)
Market analysis (`MARKET_ANALYSIS_ENABLED=0`), market pipeline (`MARKET_PIPELINE_ENABLED=0`),
hippograph (`HIPPOGRAPH_FEEDBACK_ENABLED` unset→off), evidence orchestrator (`=0`), LLM planner
(`=0`), external research (triple-gated off), storefront emphasis (unset→off), ranking nudge
(off), V2 retriever (**shadow**), image similarity (off). **The one adaptive lever that's ON:
sales-response nudge.** Also: **`DECISION_LOG_WRITES_ENABLED=false`** in the committed flags.

### 4c. Demo-only scaffolding (breaks on a real empty tenant)
Startup auto-seeds catalog (`AUTO_SEED_CATALOG_ON_START=1`), gaming set, suppliers/vendor
contacts. Market dashboard "demand rising/conversion dropping" comes from `market_replay.py`
**synthetic 7-day curve**, not real events. Point at a real empty tenant → empty
recommendations, `NO_APPROVED_SUPPLIER` on any fulfillment, blank market view.

### 4d. Code-real but config-inert (needs YOUR secrets, not new code)
Stripe (live key), competitor scraper, SSRF-guarded web-research fetcher, SMTP supplier
transport, SendGrid/SES. **Steam live-fetch exists but the only caller passes no `allow_live`
→ fixture-only, live path unreachable today.**

---

## 5. Governance / security / audit reality

- **Claim guard, autonomy gate, supplier-send: REAL, fail-closed, default-safe.** ✅
- **Immutable audit + bitemporal replay: REAL CODE, DARK IN PROD.** `audit_chain.py` is a real
  SHA-256 chain + HMAC anchor + optional S3 WORM; `decision_replay.decisions_as_of` is a real
  bitemporal query — **but the only population path is behind `DECISION_LOG_WRITES_ENABLED`,
  which is `false` in the shipped flags** (force-true only in non-prod). A prod deploy honoring
  the flag file writes **no decision logs, no hash-chain** → nothing to replay. **One-flag fix
  from aspirational to real.**
- **`ADAPTIVE_MIN_CONFIDENCE` global default 0.0** — the confidence gate is a no-op unless the
  caller passes a floor (market levers do, 0.6; a naive future caller wouldn't).

---

## 6. Agnostic-core integrity — HALF-DELIVERED

Real for the main recommend path. **But electronics is hardcoded and load-bearing off the happy
path**, worst on a *security* path:
- `recommend.py:7487-7491` — security-degraded image SQL fallback is **pure electronics**
  (`LIKE '%gaming%' OR '%rtx%' OR '%geforce%'`). A pharmacy tenant on this path **literally
  queries for RTX GPUs.**
- `recommend.py:6615` `BRAND_ALIASES={macbook→apple,thinkpad→lenovo,...}` inline (dupes the
  profile `manufacturers` slot).
- `recommend.py:7428` defaults category to `laptop`; `9097` hardcodes a `laptop ` retrieval prefix.
- `pharmacy.json`/`fashion.json` both set `cv_returns_pack:"electronics"` — CV damage/returns is
  electronics for all three verticals.
- `STORE_PROFILE_STRICT` defaults `0` → a mis-routed profile **silently falls back to electronics**.

---

## 7. suggest() / recommend.py structural risk

### 7a. The 5–8 largest remaining INLINE blocks (ranked by size × entanglement)
1. **Candidate filter cascade 8335–9586 (~1,250 lines).** `candidates` reassigned in place ~30×;
   deeply woven into branch-local flags. **Not cleanly extractable** without a pipeline object;
   moving any block reorders which fallback "wins."
2. NQE/session-slot/persona/budget 6060–6626 (~560 lines). Mutates `constraints` ~40× + Redis
   round-trips inline. Partially extractable.
3. **Early-return response builders 7653–8320 (~670 lines).** ~6 hand-built ~20-key payload dicts
   (greeting/FAQ/open-ended/clarify/support). **Most cleanly extractable** (self-contained terminal
   branches) — but the hand-duplicated payload schema is drifting.
4. Product-identity + grounding ladder 7022–7390 (~368 lines) — entangled with the security path.
5. Brand/budget price-fallback ladder 8483–8935 (~450, nested) — 6 fallback tiers with own `_meta`.
6. Spec-filter `_match_spec` closure 8974–9110 — extractable as a pure predicate.
7. Support-claim playbook 8210–8320 — cleanly extractable.

### 7b. The 5 most DANGEROUS silent swallows (fix immediately — no flag, no signal)
1. **`recommend.py:4876` `catalog_profile={}; catalog_relevance={}`** — any failure silently strips
   ranking relevance signals; worse products, no trace.
2. **`8983–8991` `cand_specs={}` (×2)** — malformed spec JSON → candidate looks spec-less → passes/
   fails the spec gate wrong → changes which products show.
3. **`5702` `sigs={}`** — security-signal parse failure → injection/jailbreak/exfil checks evaluate
   against an empty dict → a genuine attack treated as clean.
4. **`6387` `nqe_selection_applied={}`** — loses the user's just-answered clarifying selections →
   re-asks, ignores applied budget/use-case → visible conversation regression, no log.
5. **`7020` `_off_catalog_hit=None`** — silently disables the off-catalog honesty gate → "rack-mount
   A100 server" can fall through to laptop recs.

### 7c. Duplicate / drifting logic (the treadmill made visible)
- **Turn-intent classification: 2 divergent copies same name** — `recommend.py:2011` (no EXPLAIN
  branch) vs `chat.py:303` (EXPLAIN + deficit pre-check). "should i"/"overkill"/"why" → EXPLAIN in
  chat but SEARCH in recommend. **Guaranteed to drift.**
- **Budget: 4+ sites, 3 separate widen implementations** (recommend.py:6389, 6510, chat.py:376).
- **Brand resolution: no single resolver** — 2 extractors in chat, 3 more in recommend.
- **use_case: 2 entry points, last-writer-wins** (recommend.py:2311 vs 2412).
- **view_mode computed 3× with different inputs** (5389/5699 less-informed than 7653) — same request
  gets different view_mode by branch.

### 7d. State-threading ordering hazards
- **Budget re-assert at 8444–8447 MUST precede the filter at 8458** (a distant 14-line coupling);
  move it and the $1,200–1,800 request silently returns $5,999 laptops.
- The 30-step candidate cascade is ordering-encoded purely by line position (no pipeline abstraction).
- WIDEN block reads a potentially **stale local `structured_state`** (fresh-budget wrote to Redis, not local).

### 7e. THE PARITY NET is NOT strong enough to guard a big extraction
`scripts/suggest_parity_capture.py` (15-query battery) guards single-turn product-shaped happy
paths only. **Blind spots**: cold-session only (**cannot protect any multi-turn state path** —
exactly where 7d hazards live), no `right_panel`/`next_questions`/`status`/`assumptions_applied`
comparison, `why` truncated to 2, no image queries, single-shot equality. **A refactor could
break every follow-up turn and parity would stay green.** Before extracting anything in 6060–8447
or the cascade, the net needs: (a) 2–3 multi-turn scripts reusing a uid, (b) `right_panel`/
`next_questions`/`status`/full `why`/product-order added to compared keys.

---

## 8. HOW TO IMPROVE THE BRAIN & DECREASE BRITTLENESS (the plan)

**The safe pattern already exists** (`llm_planner._validate_plan`): *model proposes a value from
a CLOSED vocabulary → deterministic code clamps it to the registry/profile → deterministic
downstream executes → guard verifies → falls back to today's deterministic default on any miss.*
Ceding zero facts, prices, or authorizations. Ranked by (brittleness pain × safety of handing to
the model):

1. **`_classify_turn_intent` → model-judged lane classification.** Highest pain (mis-routes entire
   lanes; treadmill center), high safety (fixed 5-value enum). Give the model the enum as schema,
   clamp to it, fall back to SEARCH on miss. **Collapses `_is_deficit_reorder_query`, the `"only "`
   special-case, and the `with`/`without` fragility in one move.** Do first. Also unifies the two
   drifting copies (§7c).
2. **"Do you offer X?" / off-catalog → model maps phrasing to a declared `does_not_offer`/
   `off_catalog_classes` slug.** Highest safety — the capability registry is already authoritative
   ground truth; the model only maps free phrasing → a declared slug; the registry text is emitted.
   Kills the payment-plan hallucination class AND the `least`/`20000mAh` scars AND fixes the
   A100-laptop over-block (GPT-5.5 #3) **as judgment, not another regex.** This is the Phase-O beachhead.
3. **use_case detection → model-judged, clamped to profile `use_case_keyword_map` keys.** Drives
   ranking/NQE/spec-floors; clamp to profile vocab; wrong pick self-corrects via NQE.
4. **game/software/domain-entity detection → model maps to profile vocab, verified against the KB.**
   Medium priority; the code TODO already names "generalize to profile-driven domain entities."

**Keep deterministic (do NOT hand to the model):** budget *number* parsing (exact digits — a model
saying "$1,999≈$2000" corrupts the cap; use the model only to disambiguate scope like "for those"),
brand resolution / final product pick / price buckets (catalog-grounded, exact — narrated + guarded).

**Then build the orchestrator lane** (the deferred intelligence leap): the model emits a validated
tool-selection plan over the existing scatter-gather substrate + capability registry + guard.
#2 above is its first proof.

---

## 9. UPDATED ROADMAP (reordered by this deep-dive)

**Tier A — dangerous silent failures (fix now, no new feature):** the 5 swallows in §7b — replace
bare `except: {}`/`None`/`pass` with `record_partial_failure` + a safe-but-visible fallback.
Especially the security one (5702) and the off-catalog gate disable (7020).

**Tier B — the brain shift (the answer to "less brittleness, more intelligence"):** §8 items 1–2
first (turn-intent + off-catalog as model-judged, clamped, guarded), behind a flag, shadow-compared
against the regex, then routed. This is Phase O, made concrete.

**Tier C — turn the built value chain ON (honest intelligence, not new code):**
`DECISION_LOG_WRITES_ENABLED=true` (makes the audit moat real in prod — one flag); wire M1 signal
emission on the buyer path so the sales-response nudge has fuel; graduate hippograph/emphasis from
shadow with the counterfactual data already accumulating.

**Tier D — de-duplicate the drift (anti-treadmill):** one turn-intent classifier, one budget
resolver, one brand resolver, one use_case entry — collapse the copies in §7c.

**Tier E — agnostic-core hardening:** move the electronics leaks (§6) into profile slots —
especially the security-path image SQL fallback; real CV packs for pharmacy/fashion.

**Tier F — safe monolith reduction:** first *strengthen the parity net* (§7e), then extract the
clean terminal early-return builders (§7a.3) + pure predicates (§7a.6/7); treat the candidate
cascade as unguarded until multi-turn parity exists.

**Tier G — production integration (needs your inputs):** PayPal live env (code change), OOB SMS
backend, SMTP/ESP creds, competitor feed URLs, Steam `allow_live` wire-up.

**Deferred (correct as-is):** the guard, autonomy gate, supplier-send are real — leave them.

---

## 10. Questions for the external reviewer (GPT-5.6)

1. Is the **model-judged-clamped-guarded** pattern (§8) the right way to add intelligence without
   ceding safety, or is there a better architecture for the turn-intent/off-catalog decisions?
2. Given the parity net's blind spots (§7e), what's the safest order to shrink a 7,245-line
   function — and is a hermetic (non-live-server) parity harness worth building first?
3. Is turning on the dark value chain (Tier C) with calibration the right call, or should the
   market-intel modules stay dark until external signal feeds exist?
4. What did we MISS — stubs, silent failures, security gaps, or intelligence opportunities this
   sweep didn't surface?

---

*Sources: 4 parallel code-sweep agents (brain map, stubs/dark census, governance/agnostic/
market-intel, suggest/recommend structure), 2026-07-10, all file:line-verified against HEAD
(`dc8faee`).*
