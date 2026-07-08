# Brain-on audit — how the holes happened, fixes, and the guardrail verdict (2026-07-08)

Scope: 10-angle adversarial review of `bb4cd0a..66cd3a7` (unmute + B1-B4) + live E2E re-sweep
(multi-intent, VRAM-tier queries, procurement RFQ, supplier-gap). Mechanically-verified findings
were confirmed by EXECUTING the code, not by reading it.

---

## 1. The three root patterns (how it happened)

Every confirmed defect traces to one of three patterns — name them to stop repeating them:

**P1 — Same policy resolved in two places drifts.** The force flag is read env-OR-flags at the
gate (recommend.py:10858) but env-ONLY at the exact_fit overwrite (11007) → mute-layer 5 is back
in the shipped flag-driven config. Same pattern: guard applied in blocking path + separately in
an async closure (drift already: async fail-open, blocking fail-closed); eval scorer verifies
with a different scope than production.

**P2 — Substring/string matching where the domain is NUMBERS.** The guard's price allowance
(`str(val) in pre_low`) lets invented $2,000 pass because "$20,000" is in the preamble
(EXECUTED: leaked). Spec squash lets "10GB" ground against "gb1024" (prefix hole). The registry's
money regex reads i9-14900K as $14,900,000 (EXECUTED: triggers the human-manager line). The fix
class is one move: parse BOTH sides to numbers once, compare numerically.

**P3 — Evidence provenance not tracked.** The preamble is a MIX of platform-authored facts
(step-ups, capability registry — legitimate guard evidence) and conversation-derived text
(session excerpt, prior shortlist — NOT legitimate). B2 whitelisted the whole preamble →
a session-parroted URL now bypasses the quarantine check (EXECUTED: leaked). The guard needs a
scoped evidence channel, not the whole preamble blob.

---

## 2. Confirmed defects and exact fixes

### P0 — ship-blockers for the brain-on default

| # | Defect (how) | Fix (file:line) |
|---|---|---|
| 1 | **Mute-layer 5 back**: `_narr_forced` env-only vs gate env-or-flags | recommend.py:11007 — resolve force ONCE into a variable next to `_llm_force` (10853) and use it at both sites |
| 2 | **Price substring hole**: invented $2,000 grounded by "$20,000" in preamble | product_claim_guard.py:205 — parse preamble amounts into a `set[int]` (reuse `budget_grammar`), compare `val in amounts` |
| 3 | **Quarantine bypass**: session-excerpt/prior-shortlist text whitelists URLs+brands | recommend_narration_stage.py — pass ONLY platform-authored notes (capability + step-up + market evidence) as `guard_evidence`, never ctx/session parts; product_claim_guard keeps URL check vs results+guard_evidence only |
| 4 | **Async guard fails OPEN**: `except Exception: pass` around verify → unverified prose swaps in | recommend_narration_stage.py:~179 — fail CLOSED (return (None,None,meta) on guard exception) + stamp meta {"guard":"error"} |
| 5 | **Registry false triggers** (EXECUTED): "at least"→leasing note; i9-14900K/20000mAh→$-autonomy; "how many USB ports"→backorder | capability_registry.py — `\bleas(e|es|ed|ing)\b` (not `leas\w+`); replace `_MONEY` with `budget_grammar` (has `_UNIT_GUARD` for mAh/K-SKUs); tighten backorder topic to explicit stock/reorder terms |
| 6 | **Poll-endpoint info leaks**: violations (incl. quarantined URL fragments) + raw `str(exc)` returned verbatim to browser | recommend_narration_jobs.py — store violations CATEGORIES only (e.g. "ungrounded_url"), error as generic code; reserved-key filter so meta can't shadow status/assistant_message |
| 7 | **Spec prefix holes**: "gb10" in "gb1024"; TypeError retry double-runs verify + `_status="passed"` set pre-verify (false telemetry) | product_claim_guard.py — structured compare (see §4); recommend_narration_stage.py:367/376 — set status after verify; delete TypeError retry (update the 3 test doubles instead) |

### P1 — correctness/ops (fix this week)

8. **Executor starvation**: `_NARRATION_EXECUTOR` max_workers=2 vs 45s×2-retry jobs on EVERY turn;
   frontend gives up at 45s → prose computed, never shown. Fix: workers ≥4, retries=0 for narration,
   job stores queue-time, frontend poll keys off job state not fixed budget.
9. **Blocking fallback trap**: flags-load failure → mode "blocking" + 45s descriptor budget (old 8s
   cap gone). Fix: fallback mode should be "skip" (recommend.py:10917-10921).
10. **model_profiles**: CWD-relative path, permanent `{}` failure cache, no invalidation, shallow
    nested copies. Fix: adopt `feature_flags.get_flags` loader pattern (mtime reload + env path
    override + test reset).
11. **Eval/cert scorer scope mismatch**: `eval/answer_shape_scorers.py:59` verifies WITHOUT preamble
    → certification penalizes exactly the honest B1/B2 answers. Fix: thread guard_evidence through.
12. **Knowledge lane skips the capability note** (recommend.py:3554 early-return) → "do I need a
    payment plan for a $3k laptop?" fabricates on that lane. Fix: inject capability facts at the
    choke point (see §4 altitude).
13. **Async snapshot race**: job shares result dicts with the request thread's stock-annotation loop
    (recommend.py:~11346). Fix: `copy.deepcopy` the top-N results at submit (bounded, small), or
    move submit after annotation.
14. **App.tsx poll chains lack cancellation** (36×1.25s per message, no unmount/supersede abort).
15. **LLM_ASYNC_QUEUE_ENABLED=1 + async mode = job-inside-job** (inner RQ id discarded, prose
    unreachable — "mute-layer 8"). Fix: disable inner enqueue when running inside a narration job.
16. **Chat-hop timeouts surface as buyer hiccups** (round-3/4 "hiccup" mechanism = upstream
    ReadTimeout; today a 400 also degrades to hiccup). Fix: hop timeout > suggest worst case;
    distinguish 4xx (bug — log loud) from 5xx/timeouts (degrade).

### E2E verdicts (live, this audit)

- **Procurement**: confirm-cart → Gate 1 (AWAITING_BUYER_COMMITMENT, honest preview) → commit →
  QUOTE_DRAFTED. RFQ email HIGH quality (full SKU+specs, volume ask, warranty/terms/validity,
  not-a-PO footer). One leak: "Required by: the stated deadline" placeholder when no deadline
  given (fulfillment/draft deadline slot — omit line or ask buyer).
- **Multi-intent**: deterministic budget-math contradiction detection EXCELLENT ("12 × $629 =
  $7,548 > $1,500") — but the async prose REPLACED it with "Yes, you can get..." → the swap lost
  the arithmetic honesty. Guard checks products/prices/specs, NOT quantity math. Fix: when the
  deterministic message carries a contradiction/refusal marker, suppress the swap (or require the
  prose to restate the warning).
- **Supplier-gap (the user's core ask)**: "5 rack-mount GPU servers with A100s, budget 80k" →
  sold GAMING LAPTOPS confidently. No category honesty, no supplier-ask offer, no $20k autonomy
  escalation on an $80k order. THE Phase-C headline gap (see §5).
- **Gaming/AI VRAM queries**: fine on /suggest direct (the "hiccups" were a harness uid bug —
  chat's graceful-degrade masked a 400).
- **Challenge follow-up**: works WITH recent_messages (honest falls-short verdict); screenshot-2's
  miss = context loss in that session flow, not the core path.

---

## 3. Guardrail verdict — keep / fix / redesign

| Guardrail | Verdict | Why |
|---|---|---|
| Claim guard EXISTENCE (narrator-over-evidence) | **KEEP — non-negotiable** | Caught phi4's invented SKUs twice, granite's specs, qwen's off-catalog GPUs. The A/B proves every local model fabricates. |
| Guard's string-matching CORE | **REDESIGN (structured)** | P2 pattern: parse evidence specs (already dicts!) + prose claims into (metric, value, unit), normalize (TB→GB), compare numerically. Deletes squash/reversed/TB heuristics AND the prefix holes in one move. The platform already owns the vocab (spec_extraction_patterns, hard_constraint_metric_map, _humanize_spec_list). |
| Guard evidence scope | **FIX (provenance)** | Platform-authored facts = evidence; conversation-derived text ≠ evidence. Explicit guard_evidence channel. |
| Guard failure mode | **FIX (fail closed + honest telemetry)** | Async excepts→open; blocking stamps "passed" pre-verify. A guard that fails open silently is worse than none — it certifies. |
| Capability registry | **KEEP — fix triggers** | The one mechanism that made every model honest about payment plans. Move money parsing to budget_grammar, share the BNPL vocab with answer_quality, tighten topic regexes, inject at response level (not just prose preamble). |
| Deterministic honesty ladders (VRAM step-up, budget math, ACL returns text) | **KEEP — protect from the swap** | They beat LLM prose on hard fit/math turns. The swap must never downgrade honesty: contradiction-marker suppression. |
| Bounded-autonomy procurement gates | **KEEP — verified intact** | 409 illegal_transition pre-commitment is the system working. |
| Async draft-then-refine | **KEEP — fix the six B4 holes** | Right architecture (instant answer + prose upgrade); the holes are implementation, not design. |
| Force-on narration (or-chain gate) | **SIMPLIFY** | Resolve force once; keep the 7 signal clauses as the documented flag-OFF fallback; real fix is the complexity scorer (mute-layer 1) per the architecture doc. |

## 4. The altitude rule for the refactor

Fix at the CHOKE POINT, not the lane: guard belongs where job results are STORED
(run_narration_job) so no future submit path bypasses it; capability facts belong on the final
RESPONSE (suggest() assembly) so deterministic/knowledge/prose lanes are equally honest; force
policy belongs in ONE resolver. This is also the suggest()-shrinking direction: every lane-level
patch we avoid is a branch recommend.py doesn't grow.

## 5. What the supplier-gap failure teaches (Phase C priority)

The $80k A100-server turn needs, in order: (a) off-catalog CATEGORY detection (query category ∉
store categories → say so, don't pattern-match "GPU"→gaming); (b) capability registry
`sells` enforcement in retrieval framing; (c) supplier-ask offer wired to the EXISTING rfq_fanout
machinery ("We don't stock rack-mount servers. Want me to request quotes from suppliers? [draft
preview]"); (d) autonomy-limit escalation on the $80k figure (registry note must also ride the
deterministic path). That one turn exercises the whole Phase-C surface.
