# ShopSquire — Commerce Core Roadmap (product-agnostic answer engine)

Date: 2026-06-15
Status: direction-setting; no code in this doc. Companion to
`SHOPSQUIRE_GridVerdict_NLP_Narration_Improvement_Report_2026-06-15.md`.

## North star

Replace the 14,355-line `recommend.py` monolith with a **product-agnostic
commerce core** (modelled on GridVerdict's typed pipeline) plus a thin
**ShopSquire adapter pack**, cut over segment-by-segment behind a flag, validated
by the existing 95 test files as a parity oracle, and archive the monolith only
once the new path has carried real traffic with parity holding.

Three goals, in priority order:
1. **Actually answer what the user is asking** (decompose → plan → answer-first).
2. **Spend compute only when justified** (conditional escalation to vision / LLM).
3. **Portability with less code** (agnostic core written once; stores ship config + thin adapters).

Grounding facts (verified 2026-06-15):
- `recommend.py` = 14,355 lines, **9 endpoints** (`/suggest` is the hot path), 165 helpers.
- **Blast radius = 1 import** (`main.py` registers the router). Nothing imports its internals.
- It imports **100 `src.app` services** — the algorithms already live outside; the monolith is glue + fallback ladders + response assembly.
- **95 test files** touch suggest/recommend — the behavior contract AND the safety net.
- `chat.py` is a co-owner of the response contract (delegates into the pipeline, stashes image blobs "for recommend").

## Method: strangler, not big-bang

Do NOT excise-and-swap. Build `commerce_core` in parallel, flag-off = today's
monolith, flag-on = new core, cut over per query segment, each gated by parity.
Rationale and adversarial analysis: see "Adversarial critique" below.

---

## Part A — The demarcation (this IS the portability payload)

Three layers. The seam between them is the whole point.

### A1. `commerce_core/` — product-agnostic (write once, port everywhere)
Knows only abstractions: `Candidate`, `SourceStatus`, `EvidenceBundle`,
`PlanNode`, `ClaimMap`, `EscalationDecision`, `CommerceAnswer`.

- Query restatement (LLM seed, fail-open to empty)
- Decomposition CONTRACT: intent taxonomy, `sub_questions`, `image_role`,
  `answer_gap_risk`, `premise_to_verify`, abstract hard-filters (budget/brand/category as constraints)
- Query plan: typed `PlanNode` DAG, `evidence_needed`, `depends_on`, clarify gate, `inherit_plan`
- Scatter-gather orchestration + `SourceStatus` (full/partial/empty/unavailable/error/stale + latency + confidence)
- Evidence bundle (typed; the narrator's only input)
- Answer builder (deterministic sections + `claim_map`)
- Answer planner (ordered `[(predicate, handler)]` routing table)
- Claim guard (grounding rules: every claim traces to evidence)
- Narrator (LLM rewrite + cite-or-suppress guard, deterministic floor)
- Response formatter (the SINGLE output boundary)
- **Escalation policy engine** (when to call vision / LLM — Part B)

### A2. `commerce_adapters/` — store/company-specific (swap per store)
Implements narrow core interfaces over existing ShopSquire services.

- Catalog schema → `Candidate` mapping (fields, specs shape, price units)
- Candidate sources behind one interface: DB-keyword, pgvector caption-RAG, CLIP-visual (`candidate_retriever`)
- Ranking weights + policy (`product_ranking_agent`, `use_case_kb.json`)
- Budget/brand fallback ladder (ShopSquire's specific order)
- NQE — next-question/clarification engine
- Inventory + supplier governance (`inventory_agent`, `inventory_guard`, `supplier_domain_guard`)
- Security/CV surfacing (`cv_triage`, image security matrix, QR/steg) — detection is store config; the BOUNDARY is core
- Bounded-autonomy commercial policy (discount/bundle/reorder) → wraps the Authorization Engine
- Domain knowledge (`use_case_kb.json`, FAQ)
- Response-contract specifics the frontend + chat expect

### A3. `config/` (per tenant, NOT code)
Intent keyword tables, use-case KB, ranking weights, **escalation thresholds**,
autonomy tiers, brand aliases. Adding a store = new config + (rarely) a new adapter, never core edits.

**Portability test:** porting to another store should touch A2/A3 only. If it forces a core change, the seam leaked.

---

## Part B — The escalation decision model (when to bring in vision / LLM)

The single biggest lever for "faster AND smarter." Default to a cheap
deterministic floor; escalate only on a measured signal, with a hard budget and a
fallback. This is conditional compute / escalate-on-residual — the same shape as
the grounding ladder.

| Tier | Fires when | Budget | Floor if it fails/over-budget |
|---|---|---|---|
| **0. Deterministic** (always) | every query | sub-second | — (this IS the floor) |
| **Vision model** | image present AND `image_role ∈ {identity, similarity, return_evidence, authenticity}` AND not in image-hash cache AND text underspecifies | hard timeout, async/background, cache by sha256 | safe labels / text-only hints |
| **LLM decomposition enrichment** | rules set `answer_gap_risk=true` (compound / multi-intent / ambiguous / premise-to-verify) AND confidence < threshold | ~1–4 s, fail-open | rules decomposition |
| **LLM narration** | deterministic sections exist AND query benefits from prose (conversational / yes-no / tradeoff) | bounded tokens | deterministic sections as prose |
| **LLM "thinking" (reasoning / large model)** | comparison/knowledge with genuine tradeoff AND evidence assembled AND deterministic answer insufficient | bounded, gated hardest | deterministic tradeoff template |

Governing rules:
- **Never escalate by default.** Each tier needs a signal: `image_role`, `answer_gap_risk`, `query_type`, residual uncertainty.
- **Every tier has a deterministic floor** and emits `used_llm` / `used_vision` / `fallback_reason`.
- **Vision is the most expensive — gate it hardest** and cache first (image-hash cache already built this session).
- **Most queries terminate at Tier 0.** That's the speed win — not the rewrite.
- Off-topic images, fully-specified text, and cached results **skip vision entirely**.

This is the answer to "when to bring in vision/LLM thinking/narration based on
gathered evidence": escalation is a function of the evidence gap, not the query's
surface form, and it is measured, budgeted, and reversible.

---

## Part C — Make queries smarter: actually answer what they want

The mechanism is decompose → plan → **answer the question before listing products**.

- **Decompose into `sub_questions`** — break the request into what they actually want to know.
- **`answer_gap_risk`** — detect when a simple lookup would miss the real need (compound, "is X enough for Y?", "similar but cheaper", "why did you pick these?").
- **`premise_to_verify`** — "I heard this overheats" → verify, don't inherit.
- **`image_role`** — separate what the image MEANS from the text intent (find-exact vs similar vs return-damage vs authenticity vs ignore).
- **Answer planner answers FIRST, lists second.** This structurally fixes the documented answer bugs:
  - Budget yes/no ("is $1800 enough for gaming?") → `budget_viability` node answers yes/no with the band, *then* products.
  - Comparison ("4060 vs 4070 for school+gaming") → `knowledge_answer` node gives guidance, doesn't force a product list.
  - No-match → `no_match_recovery` with `upgrade_path` ("raise to $1300, or allow MSI/Lenovo").
  - Follow-ups ("what about Lenovo?") → `inherit_plan` carries budget/category/use-case/shortlist.

These were real ShopSquire defects (robotic summary, budget-not-answered,
comparison-forces-list, NQE repetition). The new architecture fixes them by
construction, not by another prompt tweak.

---

## Part D — Wiring, routing, and security

- **Single output boundary.** `assistant_message` / `results` / `products` /
  `source_statuses` / `confidence` / `trace_id` set in exactly ONE formatter.
  Kills contradictory mutation across the route and shrinks the leak surface.
- **Routing is a data table**, not nested if/elif. New answer type = new row.
- **Untrusted input never reaches any model.** QR / OCR / PII / steg payloads →
  sanitized status only (fixes the confirmed `recommend.py:12694` injection).
  `image_role` carries `allowed_to_influence` / `blocked_from_influencing`.
- **Claim guard** rejects fabricated product/price/spec/stock claims → deterministic floor.
- **Bounded autonomy** for commercial actions (discount/bundle/reorder/supplier) routes through the existing Authorization Engine — no second gate.

---

## Part E — Iterative roadmap (each phase: flag, floor, exit criteria, rollback)

**Phase 0 — security + trust quick wins** (independent of the rewrite)
- Fix QR-injection (sanitized status only); grounded claim-guard wrapping `_summarize_results`.
- Flag `COMMERCE_NARRATION_GUARD`. Exit: 5 golden tests (invented product/price/spec/QR rejected; grounded passes). Rollback: flag off.

**Phase 1 — foundation (no behavior change)**
- Define agnostic interfaces (`Candidate`, `SourceStatus`, `EvidenceBundle`, `PlanNode`, `ClaimMap`, `EscalationDecision`, `CommerceAnswer`) + ShopSquire adapter stubs over existing services.
- Stand up `commerce_core` skeleton behind `COMMERCE_CORE_V2`, mounted parallel. Exit: app builds, skeleton returns monolith output via adapters for one trivial query. Rollback: flag off.

**Phase 2 — parity oracle**
- Wire the 95-test suite to run against monolith vs core; add request-level shadow diff (top-k SKUs, budget/brand adherence, message shape, security flags).
- **Triage the 95 tests into "preserve" vs "known-bug-to-fix"** (don't blindly preserve demo hacks). Exit: harness runs, baseline diff captured.

**Phase 3 — decomposition + escalation engine**
- Rules-first decompose + `sub_questions` + `image_role` + `answer_gap_risk` + the Part B escalation engine. LLM enrichment only on `answer_gap_risk`.
- Flag `COMMERCE_DECOMP_V2`. Exit: `decomposition_eval` harness baseline + escalation unit tests (vision fires only on image_role; narration only with sections). Rollback: flag off.

**Phase 4 — evidence bundle + scatter-gather with status**
- Typed `EvidenceBundle`; `candidate_retriever`/`recommend_pipeline` return `source_statuses` + `degraded_sources`. Exit: source-status truth table green (db-error/empty/unavailable/partial). Surfaced in Decision Trace.

**Phase 5 — answer builder + planner + narrator + formatter**
- Deterministic sections + claim_map; ordered routing table; grounded narrator; single formatter. Exit: answer-quality golden set (budget yes/no, comparison, no-match) + "one writer" CI assertion. Flag `COMMERCE_FORMATTER`.

**Phase 6 — cutover by segment** (each flips only on its parity slice green + live shadow)
- Order: text-simple → text budget/brand → comparison/knowledge → image safe → image flagged-security. chat.py contract tests in the must-pass set before any flip.

**Phase 7 — bounded-autonomy commercial nodes**
- availability/bulk/bundle/discount/supplier proposal nodes via Authorization Engine. Exit: bounded-autonomy table tests (bulk>stock, price-match, auto-send blocks, "reserved" only if reservation succeeded).

**Phase 8 — archive**
- `recommend.py` → `recommend_legacy.py`, importable behind `COMMERCE_CORE_V2=0` for one release as rollback, then delete. Exit: all segments cut over, parity holds (minus documented intentional diffs) on 95 tests + live shadow for a sustained window, latency budget met.

---

## Part F — Extract / recycle / build ("less coding" reality)

- **Recycle as-is (already services, just compose):** orchestrator, ranking agent, candidate_retriever, recommend_pipeline, vision_cache, NQE, cv_triage, inventory services, supplier_domain_guard, authorization_engine, use_case_kb.json.
- **Extract from monolith → adapters (with their tests):** budget envelope, brand fallback ladder, security surfacing, per-product `why` builder, OOS penalty, response contract.
- **Rewrite as core (the only genuinely new code):** routing (→ table), output assembly (→ formatter), fallback branching (→ plan nodes), escalation engine, claim guard, evidence bundle, narrator guard.
- **Net:** replace ~14k lines of spaghetti with a ~2–3k-line pure core + thin adapters; most logic already exists. The "new" volume is interfaces + config, not algorithms. **This is the "less code" win — and it only materialises if the seam holds.**

---

## Part G — Adversarial critique (and mitigations)

- **Speculative generality** (building agnostic for one tenant). → Drive the core with ONE real adapter (ShopSquire). No second store's hooks until a second store exists. Agnosticism lives in the SEAM, not in imaginary features. (YAGNI.)
- **"Take our time" → never ships.** → Every phase ships behind a flag with standalone value; time-box phases; Phase 0 ships value in week one.
- **Parity oracle preserves bugs/demo-hacks.** → Triage the 95 tests; document intentional diffs; parity-with-exceptions, not blind parity.
- **LLM decomposition adds latency/cost/nondeterminism.** → Rules-first; LLM only on `answer_gap_risk`; gated by the eval harness number; conditional compute.
- **Two code paths = double maintenance during transition.** → Freeze monolith (bug-fix only); all new work on core; keep the transition window per segment short.
- **Over-aggressive grounding guard rejects good prose.** → Tune on a golden set; the deterministic floor is always acceptable, so a false reject degrades gracefully.
- **Rewrite ≠ faster.** → Speed is the cache/timeout/pre-warm/escalation workstream (mostly done). Don't let the rewrite take credit for latency; run them as separate tracks.

---

## Part H — Definition of done (archive gate)

Archive `recommend.py` only when ALL hold:
1. Every query segment cut over to the core.
2. 95-test parity green (minus documented intentional diffs).
3. chat.py + NQE contract tests green.
4. Live shadow parity holds for a sustained window.
5. Latency budget met (text and image+text) under the escalation model.
6. One release shipped with `recommend_legacy.py` available as instant rollback.

Then move to `recommend_legacy.py`, ship one release, then delete.
