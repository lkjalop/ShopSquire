# David's Feedback — Response, Currency Check, and a Better Video (2026-07-30)

*David reviewed a build from ~2026-07-06. This assesses which of his points are still live, which are
now answerable with mechanism, and how to structure the next video.*

---

## 0. The context that reframes everything

**573 commits have landed since 2026-07-06.** More importantly, the things David asked about did not
merely improve — most of them **did not exist** when he reviewed:

| Component | First committed | Existed for David? |
|---|---|---|
| `recommendation_core/core.py` — the V2 engine | **2026-07-11** | ❌ no |
| `authoritative_business_feed.py` — canonical facts | **2026-07-28** | ❌ no |
| `account_intelligence.py` — party/identity | **2026-07-28** | ❌ no |
| `currency_authority.py` — FX refusal | **2026-07-28** | ❌ no |
| `inventory_event_projection.py` — ATP/conservation | **2026-07-29** | ❌ no |
| `market_source_registry.py` — licence/origin/trust | **2026-07-29** | ❌ no |
| `recommend.py` (12,403 ln monolith) | — | ✅ **still alive** (deleted 2026-07-29) |

**David reviewed the previous architecture.** He was looking at the bounded-agentic prototype running
on the monolith. The authority layer that answers most of his hard questions was built in the last
72 hours.

**This is not a reason to dismiss his feedback. It is the opposite.** Read his review again with that
timing in mind and something striking emerges: *the gaps he identified became the roadmap, and the
roadmap got executed.* That is what good senior feedback does — it finds the real seams, not the
cosmetic ones. He was right about all of it.

---

## 1. Point-by-point: what's live, what's answered

### ✅ What he praised — all still true, and stronger
| His point | Status now |
|---|---|
| End-to-end business workflow | Deeper: canonical feed → ATP → procurement → supplier reply projection |
| Bounded agentic AI | Now **authority boundaries**, not just bounds — the model cannot construct an unfounded claim |
| Decision trace | 14 tabs, market/procurement/evidence panels, per-decision persistence |
| "Not everything should be an LLM" | Now measurable: retrieval is model-independent; ~99% of turn latency was one model call |
| FinOps awareness | Sharper: BYO-model, zero marginal cost per conversation self-hosted |
| Human-in-the-loop before supplier outreach | Unchanged invariant, now with four-eyes on identity execution too |

### 🟠 STILL LIVE — every communication point
**None of this was fixed by code, because none of it is a code problem.**

| His point | Status | Why it matters more now |
|---|---|---|
| "Tighten the narrative — lead with architecture and business problem before the demo" | ❌ **unaddressed** | The system is 416k lines now. Without a narrative it is *less* comprehensible, not more |
| "Explain agents, data sources, model tiers, guardrails more clearly" | ❌ **unaddressed** | There are now far more of each to explain |
| "'Agentic', 'bounded', 'decision trace', 'market intelligence' need cleaner definitions" | ❌ **unaddressed** | These now have *precise* technical meanings — define them |
| "Don't expose live bugs without framing" | ❌ **unaddressed** | Same risk, higher stakes |

### 🟢 NOW ANSWERABLE WITH MECHANISM — his nonfunctional asks

| His question | The answer that now exists |
|---|---|
| **Scalability** | Honest: ~40 concurrent turns/replica (48 sync routes hold a threadpool thread for the ~7s model call). Scale horizontally; real concurrency needs vLLM/batching. **Measured, not guessed** |
| **Security** | 136 security modules, `no_fail_open_in_security` ratchet, SSRF allowlist, fail-closed attachment guards, hostile supplier reply quarantine |
| **Supplier integration** | NetSuite (real), Xero, Shopify, CSV/SFTP, generic HTTP; `connector_runtime.py` with circuit-breaking, CAS cursors, stalled-run recovery |
| **Data freshness** | `market_evidence_policy.py`: `resolution_basis = "trust_tier_then_freshness_then_confidence"`; `as_of` on every fact; `fx_authority_stale_or_future` refuses stale FX |
| **Latency** | p95 6,906ms measured against an 8,000ms gate; router = ~99% of turn |
| **Governance** | Human-only send, four-eyes identity execution, `simulation_only` authority, per-decision audit |
| **Exception handling** | Outbound queue `dead_letter` + claim reclamation; quarantine dispositions; conservation-failure detection; `v2_unavailable` typed degradation |

### 🎯 His two hard questions — now the platform's strongest material

**"How does the platform know competitor prices are accurate?"**

The honest 2026-07-30 answer is better than a defence — it's a *decision*:

> "It doesn't, so it doesn't rely on them. Every external source is registered with a `licence_id`,
> `licence_url` and pinned origin. Sources carry a trust tier, and contradictions resolve by trust
> tier, then freshness, then confidence — never by averaging, because the average of two incompatible
> facts is a third fact nobody asserted. A competitor price is tier 3: hedged, attributed, and never
> the sole basis for an automated action. For the wholesale case I've deferred competitor price
> collection entirely — the valuable comparison is supplier quotes the customer already owns, and
> scraping carries legal surface for a benefit that segment doesn't need."

**"What happens if inventory data is stale or the RFQ email is wrong?"**

> "Stale inventory: ATP is never inferred from on-hand. If reservations aren't supplied, ATP returns
> `unknown` with a reason, not a number. Projections are event-sourced with conservation checks, so a
> mismatch surfaces as an exception rather than a plausible-looking balance. Every reading carries
> `as_of` and a basis of observed/derived/estimated/unknown.
>
> Wrong RFQ: nothing sends without a human. Beyond that — outbound is a durable queue with idempotent
> dedup, exponential backoff, claim reclamation for crashed workers, and dead-lettering. Inbound
> supplier replies are quarantined and projected as *observations*, never as instructions, and
> attachment guards fail closed. Supplier channel can't silently switch on an amendment."

**Those two answers are the video.** They are the difference between "promising prototype" and
"someone who has thought about failure."

---

## 2. What his feedback should change — and what it shouldn't

### The uncomfortable observation
David gave two classes of feedback. **You executed massively on the engineering class and did
essentially nothing on the communication class.** 573 commits fixed the reliability questions. Zero
of them tightened a narrative.

That's not a criticism of the engineering — the engineering needed doing and the work is excellent.
But it means **communication is now the binding constraint**, and it has been for three weeks. A
416,000-line system that nobody can follow in 12 minutes is worth less than a 40,000-line one that
lands.

### What should NOT change
- **Do not build more before the next video.** His feedback is not a feature request. Every point he
  raised is now either answered or is a presentation problem.
- **Do not make the demo longer.** More capability makes narrative discipline more important, not
  less.

---

## 3. How to make the video better

### 3.1 The structural fix — lead with the problem, not the product

**Old (what he saw):** demo → features → architecture mentioned along the way.
**New:** problem → principle → proof → demo as *evidence*, not as content.

```
0:00–1:00  THE PROBLEM
           A distributor commits stock they don't have, orders against a stale number,
           or an agent emails a supplier something wrong. All three are expensive and
           all three are invisible until after the fact.

1:00–2:30  THE PRINCIPLE  (define the terms here, once, precisely)
           "Bounded"      = the model chooses from a closed vocabulary; it cannot emit
                            a value the system doesn't already recognise.
           "Authority"    = a value can only be used if its evidence is present, fresh
                            and permitted. No FX rate → no cross-currency comparison.
           "Decision trace" = the per-decision record of what was known, what was used,
                            what was refused, and who authorized it.
           "Market intelligence" = licensed, origin-pinned external facts with a trust
                            tier — not scraping.

2:30–5:00  THE ARCHITECTURE  (one diagram, held on screen)
           model proposes → gate authorizes → connector executes → observer records
           Say where each agent runs, which model tier, and what it is NOT allowed to do.

5:00–9:00  THE PROOF  (three scripted moments — see 3.2)

9:00–11:00 NONFUNCTIONAL  (his explicit ask — one slide, real numbers)
           latency p95 · concurrency ceiling · failure modes · governance · freshness

11:00–12:00 WHAT IT CAN'T DO YET  (the credibility close)
```

### 3.2 The three moments — this is the whole video

**Moment 1 — A refusal, with its reason.**
Ask it to compare a USD product against an AUD one. It declines and shows the missing FX authority.
Then cut to `currency_authority.py` — 188 lines, 8 refusals, one every 23 lines.
> "Most systems would have shown you a number. This one can't construct one."

**Moment 2 — The archive test.** *(30 seconds; the strongest artifact in the repo)*
Show `test_recommend_v1_archive.py`: 12,403 lines deleted, hash-sealed, and the manifest recording
`"failed": 36`, `"status": "non_executable_historical_evidence"`.
> "I deleted the engine this platform started as. The archive records that 36 of its tests were
> failing when I retired it — so nobody, including me, can later claim it was green."

**Moment 3 — `gates_pass: False`.**
Show a replay where every individual metric passes and the harness still refuses to certify.
> "Nineteen open divergences against the old engine, each with an owner and a disposition. The
> measurement apparatus is allowed to tell me no."

### 3.3 Specific fixes to his criticisms
- **The cart bug:** rehearse and re-record. If something breaks live, **name it immediately** —
  *"that's a real bug, it's in the tracker, here's what it doesn't affect."* Unframed bugs read as
  unawareness; framed bugs read as ownership.
- **Definitions:** one slide, four terms, before any demo. Never use "agentic" without saying what
  bounds it.
- **Model tiers:** state explicitly — router model, vision model, narration model, and which
  decisions use no model at all.
- **Don't lead with the chatbot.** It is the most commoditised thing you have and it invites the
  comparison you lose.

### 3.4 The close that beats a polished ending
> "To be clear about what this isn't: there's no customer, no production traffic, and every number
> you've seen is synthetic. What I can prove is that the engineering is real and that the measurement
> apparatus is honest enough to tell me when I'm wrong. What I can't prove is that it saves anyone
> money — that needs a design partner, and that's what I'm looking for."

David's review said "promising prototype." That paragraph is what moves it to "engineer I'd hire."

---

## 4. How this changes things

1. **Send him a delta, not a new video.** A short note: *"Since you reviewed the July 6 build, the
   V2 core replaced the monolith, the monolith was deleted, and an authority layer landed that
   directly answers your two questions about price accuracy and stale inventory. Here's a 2-page
   summary."* Senior reviewers remember people who close the loop; almost nobody does.
2. **Communication is now the bottleneck, not capability.** Three weeks of extraordinary engineering
   velocity did not move the thing he flagged first.
3. **His questions are now assets.** "How do you know prices are accurate?" is the best question
   anyone can ask you, because you have a real answer including the part where you decided not to
   collect them.
4. **Reinforces the standing recommendation.** Every analysis in this series converges on the same
   point: the platform doesn't need more capability, it needs outside contact. David *is* outside
   contact. Use him properly — a delta note and a specific ask ("would a distributor you know take a
   shadow pilot?") is worth more than another 573 commits.

---

*Assessment only. No code changed.*
