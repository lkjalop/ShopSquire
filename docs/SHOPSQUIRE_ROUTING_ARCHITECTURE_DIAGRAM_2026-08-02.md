# ShopSquire — Routing & NLP Architecture (technical) + LinkedIn draft (2026-08-02)

*Traced from `turn_router.py`, `plan.py`, `core.py`, `recommendation_facade.py`, `memory.py`.
Every box below corresponds to code that exists at HEAD `b3dca021`.*

---

## 1. The full pipeline

```
════════════════════════════════════════════════════════════════════════════════════════
  TURN N              buyer utterance + session (uid, tenant, site) + optional image
════════════════════════════════════════════════════════════════════════════════════════
                                        │
                    ┌───────────────────▼───────────────────┐
                    │  EDGE  chat.py :: _chat_query_impl    │   ⚠ still holds a legacy
                    │  build TurnEnvelope                   │     regex parser (see §3)
                    │  (query · budget · qty · session ·    │
                    │   currency · image refs · trace_id)   │
                    └───────────────────┬───────────────────┘
                                        │
                    ┌───────────────────▼───────────────────┐
                    │  SHARED COMMERCE GUARD  (run once)    │   DETERMINISTIC
                    │  injection · model-theft · rate ·     │   fail-closed
                    │  intake_gate (MIME/polyglot/NFKC)     │
                    └───────────────────┬───────────────────┘
                                        │ blocked → 200 w/ refusal envelope, no data
                                        ▼
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  STAGE 1 · ROUTE          turn_router.route_turn()                                    ║
╠══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                       ║
║   ┌─ MODEL CALL #1 ────────────────────────────────────────┐   ROUTER_MODEL           ║
║   │  in : utterance + prior node + sold-taxonomy candidates │   → CLASSIFIER_MODEL     ║
║   │  out: ONE JSON object, closed schema                    │   → certified default    ║
║   │       { lane, node_handle, requirements[],              │                          ║
║   │         quantity, budget, brand, subject_action,        │   ~99% of turn latency   ║
║   │         procurement_context, confidence, refusal }      │   p95 ≈ 6.9s             ║
║   └────────────────────────────────┬───────────────────────┘                          ║
║                                    │  the model PROPOSES. it decides nothing.          ║
║   ┌────────────────────────────────▼───────────────────────┐                          ║
║   │  CLAMP CHAIN   (deterministic, every field)             │                          ║
║   │   lane          ∈ LANES (10)          else → fallback   │                          ║
║   │   node_handle   ∈ offered candidates  else → drop       │                          ║
║   │   requirements  ∈ attribute registry  else → drop       │                          ║
║   │   brand         ∈ catalog brands      else → drop       │                          ║
║   │   quantity/budget → canonical grammar (NOT model text)  │                          ║
║   │   refusal       → granted ONLY if sells_within()==False │                          ║
║   │                   ── the model may propose a refusal;   │                          ║
║   │                      only the sold taxonomy grants it   │                          ║
║   └────────────────────────────────┬───────────────────────┘                          ║
║                                    │ any miss / model down / bad JSON                  ║
║                                    ▼                                                   ║
║              _bounded_fallback_decision()      DETERMINISTIC, always valid              ║
║              lane = PROCUREMENT if qty >= 2 else SEARCH        ← one line, no model     ║
║                                                                                        ║
║   ⇒ TurnDecision { lane, node, reqs, qty, budget, confidence, source }                 ║
╚═══════════════════════════════════════════════╤══════════════════════════════════════╝
                                                │
                    ┌───────────────────────────▼───────────────────────────┐
                    │  STAGE 2 · CLARIFY GATE   (pre-retrieval)             │
                    │  required field missing for the lane?                 │
                    │  → ask ONE bounded question. TEMPLATE ONLY.           │
                    │  NO MODEL CALL → ~single-digit ms, and it SKIPS       │
                    │  a 7s retrieval that would have guessed.              │
                    └───────────────────────────┬───────────────────────────┘
                                                │ else
╔═══════════════════════════════════════════════▼══════════════════════════════════════╗
║  STAGE 3 · PLAN            plan.py                                                    ║
╠══════════════════════════════════════════════════════════════════════════════════════╣
║   TOOLS = closed vocabulary of 7 executors                                            ║
║     retrieve · fit_check · off_catalog_honesty · clarify ·                            ║
║     policy_answer · handoff_support · handoff_procurement                             ║
║                                                                                        ║
║   derive_plan(decision)          DETERMINISTIC · always available · the baseline       ║
║     SEARCH/FILTER/COMPARE/EXPLAIN → [retrieve, fit_check]                              ║
║     PROCUREMENT                   → [retrieve, fit_check, handoff_procurement]         ║
║     OFF_CATALOG                   → [off_catalog_honesty]                              ║
║     POLICY_QUESTION               → [policy_answer]                                    ║
║     SUPPORT_CLAIM                 → [handoff_support]                                  ║
║     INVENTORY                     → [retrieve, inventory_summary]                      ║
║                                                                                        ║
║   ┌─ MODEL CALL #2 (optional) ─────────────────────────────┐                          ║
║   │  propose_plan() — may REORDER or EXTEND within TOOLS    │                          ║
║   │  e.g. insert `clarify` before `retrieve` on ambiguity   │                          ║
║   └────────────────────────────────┬───────────────────────┘                          ║
║                                    ▼                                                   ║
║               validate_plan()  → any miss falls back to derive_plan()                  ║
║                                                                                        ║
║        ★ THE INVARIANT:  the model can add a STEP.                                     ║
║                          it can never add a CAPABILITY.                                ║
╚═══════════════════════════════════════════════╤══════════════════════════════════════╝
                                                │
                    ┌───────────────────────────▼───────────────────────────┐
                    │  STAGE 4 · EXECUTE   (deterministic executors)        │
                    │                                                        │
                    │  retrieve   → taxonomy-first candidate fetch           │
                    │               Postgres BOW · MODEL-INDEPENDENT         │
                    │               (this is why cards can paint < 1s)       │
                    │  fit_check  → attribute-registry verdicts              │
                    │               meets / fails / UNKNOWN  ← tri-state     │
                    └───────────────────────────┬───────────────────────────┘
                                                │
╔═══════════════════════════════════════════════▼══════════════════════════════════════╗
║  STAGE 5 · POST-RETRIEVAL   each wrapped in _run_stage(): guarded · timed · traced     ║
╠══════════════════════════════════════════════════════════════════════════════════════╣
║   capability_budget   → budget vs capability floor; closest_fit vs stretch band        ║
║   shelf               → 3 bands: budget-fit · performance-fit · all                    ║
║   variant_clarify     → one bounded question if a variant axis is ambiguous            ║
║   complement_offer    → accessory/bundle, floor-gated                                  ║
║   bulk_economics      → qty × price breaks × MOQ  (fires on PROCUREMENT)               ║
║   fulfillment_preview → network availability + transfer plan + shortfall               ║
║   secondary_explanation                                                                ║
║                                                                                        ║
║   a stage that throws is recorded as stage_partial_failure — never a silent pass       ║
╚═══════════════════════════════════════════════╤══════════════════════════════════════╝
                                                │
                    ┌───────────────────────────▼───────────────────────────┐
                    │  STAGE 6 · COMPOSE   set_message(MsgPriority ladder)  │
                    │  DETERMINISTIC. the winning stage claims the message.  │
                    │  a blank stage can never claim it.                     │
                    │  (LLM narration is a separate, guarded, optional leg — │
                    │   cite-or-suppress; it may not assert a spec that      │
                    │   isn't in the catalog or the evidence set)            │
                    └───────────────────────────┬───────────────────────────┘
                                                │
                    ┌───────────────────────────▼───────────────────────────┐
                    │  STAGE 7 · POSTFLIGHT   run_postflight()              │
                    │  persist constraints_used (REFRESH, not wipe)         │
                    │  session:{uid}:summary      utterances[-50:]  TTL 24h │
                    │  session:{uid}:kv_state     budget/brand/subject      │
                    │  session:{uid}:recent_retrieval          TTL 600s     │
                    │  observation_log[-500:]                               │
                    │  ✗ reads do NOT refresh TTL — memory expires on purpose│
                    └───────────────────────────┬───────────────────────────┘
                                                │
                                    ╭───────────▼───────────╮
                                    │   TURN N+1 re-enters   │
                                    │   with kv_state as the │
                                    │   PRIOR NODE + budget  │
                                    ╰───────────┬───────────╯
                                                │
════════════════════════════════════════════════▼══════════════════════════════════════
  MULTI-TURN JOURNEY                     discovery → cart → sourcing
════════════════════════════════════════════════════════════════════════════════════════

  T1  "gaming laptop under $2000"      SEARCH        budget → kv_state
       │
  T2  "something quieter"              FILTER        prior node inherited; budget PERSISTS
       │                                             (refresh-not-wipe; the bug class that
       │                                              killed the old engine)
  T3  "what about 15 of them"          PROCUREMENT   qty>=2 · DETERMINISTIC, no model
       │                               → bulk_economics: MOQ, price breaks
       │                               → fulfillment_preview: network ATP, shortfall
       ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  CART                        cart lane (guarded, tenant+customer)    │
  │   qty > stock → two options:                                         │
  │     A. fill now  (in-stock + transfer + supplier shortfall)          │
  │     B. ship from stock now / alternatives                            │
  └───────────────────────────────┬─────────────────────────────────────┘
                                  │  "Confirm delivery plan"
                                  ▼         ═══ GATE 1 ═══  (domain)
  ┌─────────────────────────────────────────────────────────────────────┐
  │  DRAFT RFQ           fulfillment/draft.py :: draft_and_record()      │
  │   build_draft → recipient · subject · body · qty · terms             │
  │   draft_send_gate(min_confidence=0.6)  ← ADVISORY, PRIOR to human    │
  │   economics: list → wholesale → margin → break → max discount        │
  │                                                                       │
  │   send_gate: "human"        auto_sent: FALSE                          │
  │   outbound_integrity → the platform can quarantine its OWN draft      │
  └───────────────────────────────┬─────────────────────────────────────┘
                                  │
                                  ▼         ═══ GATE 2 ═══  HUMAN ONLY
                        outbound_queue: pending → sending → sent
                        idempotency_key · claim/reclaim · backoff · DLQ
                                  │
                                  ▼
                        supplier ── reply ──► QUARANTINE ──► observation
                                             (never an instruction)
```

---

## 2. The division of labour, stated plainly

```
┌──────────────────────────────┬──────────────────────────────────────────────┐
│  MODEL DECIDES               │  DETERMINISTIC CODE DECIDES                  │
├──────────────────────────────┼──────────────────────────────────────────────┤
│  which lane (proposal)       │  whether that lane is in LANES               │
│  which taxonomy node         │  whether we sell it (sells_within)           │
│  which requirements          │  whether they're in the attribute registry   │
│  plan step ORDER             │  the plan's CAPABILITY set (TOOLS)           │
│  narration prose             │  whether a claim is grounded (cite-or-       │
│                              │    suppress against catalog + evidence)      │
├──────────────────────────────┼──────────────────────────────────────────────┤
│  cost: ~7s, tokens, GPU      │  cost: ~0ms, $0                              │
└──────────────────────────────┴──────────────────────────────────────────────┘

  Things a model must NEVER decide — because the answer must be identical every time:
    qty >= 2 → PROCUREMENT          currency comparability (needs dated FX authority)
    UoM category equivalence        ATP when reservations are unknown
    sellability / refusal grant     whether an email may be sent
```

**The FinOps consequence falls straight out of the table.** Every decision on the right costs
nothing and never varies. Every decision on the left costs a model call. Latency and spend are
therefore a *design* output, not a tuning exercise — and the clarify gate is the sharpest example:
it's template-only, so asking one good question is both **more correct and ~7 seconds faster** than
retrieving on a guess.

---

## 3. ⚠️ Accuracy caveat — do not post around this

`chat.py` (3,689 lines, growing) still contains a legacy regex parser doing work the core router
now owns:

| Function | Line |
|---|---:|
| `_extract_budget_bounds` | 256 |
| `_is_budget_query_text` | 303 |
| `_classify_turn_intent` | 367 |
| `_brand_hint_from_text` | 592 |

**The 12k engine is retired. The duplicate decision surface at the edge is not.** Say that in the
post. It costs one sentence and it's the difference between a claim that survives someone opening
the repo and one that doesn't.

---

## 4. LinkedIn draft — four paragraphs

> **I deleted 12,403 lines of my own code because it couldn't remember a budget.**
>
> The old engine was one enormous function with the intent logic spread across regexes. It could
> parse "gaming laptop under $2000" perfectly. Then you'd say "something quieter" and the $2,000
> was gone — because each regex ran once, returned a value, and nothing owned the state between
> turns. Bigger context windows don't fix that. The constraint wasn't lost in the context; it was
> never anywhere that survived the turn.
>
> The rebuild split the problem in two. A model maps unbounded language into a **closed schema** —
> lane, taxonomy node, requirements, quantity — and then deterministic code clamps every field:
> the lane must be one of ten, the node must be one we actually sell, the requirements must exist
> in the attribute registry. The model can propose a refusal; only the sold taxonomy can grant one.
> Plans work the same way: the model may reorder or extend the steps, but only from a fixed
> vocabulary of seven executors. **It can add a step. It can never add a capability.** And some
> decisions never reach a model at all — `quantity >= 2 → procurement lane` is one line, because
> that answer has to be identical every single time.
>
> That split turned out to be a cost architecture as much as a correctness one. A deterministic
> branch costs 0ms and $0; a router call costs about seven seconds and real tokens. So "which
> decisions deserve a model call" is a budget decision. My favourite consequence: when a required
> field is missing, the system asks one bounded, template-only question **before** retrieval —
> which is both more correct *and* about seven seconds faster than retrieving on a guess. Memory
> got the same treatment: 50 utterances, a 600-second retrieval cache, and reads deliberately do
> not refresh the TTL. It forgets on purpose, because the alternative is a context that rots.
>
> Honest caveat, since someone will check: the 12k engine is gone, but my chat edge still carries a
> legacy regex parser doing work the core router now owns. It's a duplicate decision surface and
> it's on the list — I'm naming it here so I can't quietly forget it. And the usual disclosure:
> no customer, no production traffic, synthetic data. What I can prove is the engineering and that
> my measurement apparatus is honest enough to tell me when I'm wrong.

**Attach:** the "MODEL DECIDES / DETERMINISTIC CODE DECIDES" table from §2 as the image. It's the
most screenshot-able artifact here and it carries the whole argument without needing the post.

---

*Traced from source. No code changed.*
