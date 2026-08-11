# External Research — Browser Certification and Trigger Defects

**Date:** 2026-08-07
**HEAD:** `532ea387`
**Backend:** restarted 20:10 (after the last commit at 19:56), `scripts/start_official_research_proof_backend.ps1` env
**Method:** live Playwright clickthrough against Vite :5173 + FastAPI :8080 + fake official provider :8099

---

## Verdict in one line

**External research works. The gate that decides when to use it does not.**

The provider leg is certified end-to-end in a real browser. The trigger that is supposed to
route the unfamiliar-workload case into that leg cannot fire on the case in the screenshots,
for three independent and separately provable reasons.

---

## Part 1 — What was certified

### Backend was stale; that is now fixed

The previously running backend started at **15:51**. The five research commits landed
**18:59–19:56**. Every earlier browser observation was made against code that did not
contain the work being assessed. Restarted at **20:10** on HEAD.

`/health` on the fresh process:

```json
{ "requirement_authority_ready": true, "requirements_endpoint_configured": true,
  "requirements_domain_allowlist_size": 1, "tenant_enrollment_count": 1,
  "source_policy_reviewed": true, "reason": "live", "authority_reason": "ready" }
```

### The official-provider journey passes

`frontend/e2e/official-research-authorization.spec.ts` — **PASS, 21.3s.**

Live, in the browser, under one trace: provider selected → called → evidence validated →
requirements compiled → products authorized.

```
official requirements api: selected for official requirements (1800ms deadline)
official requirements api: ok
Evidence-to-requirement compilation   Status: accepted
  ram gb >= 32 GB
  gpu vram gb >= 8 GB
```

Roadmap item 1 is **complete**. This is real and it is the first browser proof of the leg.

### The trace honesty fix shipped

The screenshot string `"No named-workload research was required for this turn."` no longer
exists anywhere in the source. It is replaced by:

> "No governed workload research record was produced. **This does not establish that research
> was unnecessary.**"

That was recommendation #7 in the research notes ("the trace reports absence of need where the
truth is absence of coverage"). It is done, and it is the reason the remaining defects were
findable at all — the trace now refuses to claim what it does not know.

---

## Part 2 — The screenshot bug reproduces on HEAD

Live clickthrough, verbatim screenshot query, fresh session, no consent phrase:

> *"I need help with a laptop for digital twin simulation? I need it to simulate a cyber attack?"*

**Result: 6–10 gaming laptops. No abstention. No consent chip. No research.**

```
1. Model interpretation
   No bounded workload entity was proposed.
Adaptive research assessment - shadow only
   State: catalog sufficient
   Recommendation: catalog first
   Score: 0
   Reasons: none recorded
3. Deterministic authorization
   Status: not run
```

The reply was *"These all handle **engineering student** — they start at $1,199…"* — the
nearest-neighbour snap the research notes predicted, landing on a different wrong persona than
the screenshot's but by the same mechanism.

---

## Part 3 — Root cause, isolated to one variable

Two queries. Identical purpose sentence. Only `a laptop for` differs. Fresh sessions, repeated,
stable (case F is a re-run of case D and is byte-identical in outcome).

| Case | Query | Products | Observer state | Score | Authorization |
|---|---|---|---|---|---|
| **D** | "I need help with **a laptop for** digital twin simulation. I need to simulate a cyber attack." | **6** | `catalog sufficient` | **0** | **not run** |
| **E** | "I need help with digital twin simulation. I need to simulate a cyber attack." | **0** | `unresolved workload` | **0.425** | **blocked** |

Case E is correct behaviour: abstention, a real bounded research plan, prohibited-assumption
lists, a consent chip (*"Check approved sources" / "Do not research"*), and
`Prevented: catalog recommendation | supplier enquiry | commerce execution`.

Case D is the bug. **Naming a product category disables the abstention.**

Note the direction: D contains *more* purpose spans than E (`for digital twin simulation`
**and** `to simulate a cyber attack`; E has only the latter). It produced fewer. This is not
span extraction and it is not model non-determinism.

### Defect 1 — a product-category match suppresses the purpose-coverage check

[`turn_router.py:2423`](../src/app/services/recommendation_core/turn_router.py#L2423)

```python
if not product_type_options and not requirements and not raw_requirements and relationship != "run_on":
    semantic_proposal = unresolved_purpose_proposal(...)
```

The abstention path only runs when the buyer named **no** product type. So "laptop" is treated
as evidence that the purpose was understood.

The module this gate calls into opens with the opposite doctrine, in its own docstring
([`semantic_coverage.py:3`](../src/app/services/recommendation_core/semantic_coverage.py#L3)):

> *"A product category match is not evidence that the buyer's stated purpose was understood."*

The guard contradicts the invariant the module was written to enforce. And because the model
leg produced no valid `semantic_proposal` on this query, the coverage abstention was the only
backstop — so the system is a **single point of failure on the model's semantic proposal for
every query that names a product category**, which is nearly every real buyer query.

### Defect 2 — the observer cannot distinguish "no interpretation" from "confident coverage"

[`research_routing.py:39–79`](../src/app/services/recommendation_core/research_routing.py#L39)

When `semantic_proposal` is empty, every feature evaluates to zero, so
`score = 0` and the state falls through to the `else` branch:

```python
else:
    state = "catalog_sufficient"
```

Silence and confidence produce identical output. The observer has the same missing-null-class
problem as the router it was built to observe. `catalog_sufficient` is an assertion the
function has no evidence for.

### Defect 3 — the threshold is structurally unreachable by the abstention path

The coverage abstention deliberately emits `workload_hypotheses: []` (it has no authority to
invent interpretations), so `hypothesis_ambiguity = 0`. It also generates `concepts` and
`material_unknowns` **1:1 from the same span list**, which pins
`unresolved_ratio = n / (2n) = 0.5` for all `n`:

```
concepts=1 unknowns=1 -> score=0.425  fires=False
concepts=2 unknowns=2 -> score=0.425  fires=False
concepts=5 unknowns=5 -> score=0.425  fires=False
threshold = 0.45
```

Every abstention case scores **exactly 0.425**, forever, regardless of how unresolved the turn
is. Only `commercial_materiality` (+0.05 when qty > 1) can cross the line, at 0.475.

This is why both live abstention cases reported `State: unresolved workload` alongside
`Recommendation: catalog first` — **the observer contradicted itself on every case it correctly
labelled.** If this were promoted to a live trigger at 0.45 today, it would never fire except
on bulk quantity.

Compounding it: the observer defines **seven** features; the only production call site
([`core.py:543`](../src/app/services/recommendation_core/core.py#L543)) populates **two**.
`catalog_coverage`, `retrieval_confidence`, and `unknown_attribute_ratio` are never passed, so
0.35 of the weight is dead.

### Defect 4 — purpose-span extraction ingests the consent sentence

With consent appended, the extractor captured **`that research`** as a material concept and
planned a provider query for *"that research official definition scope"*. The `\bto\s+` pattern
in [`semantic_coverage.py:15`](../src/app/services/recommendation_core/semantic_coverage.py#L15)
matches inside *"I consent to that research."*

Consequence is not cosmetic: that turn obtained real official evidence
(`ram gb >= 32 GB`, `gpu vram gb >= 8 GB`, `Status: accepted`) and **still ended
`Status: blocked — unresolved material concept`**, because a parsing artifact can never be
resolved. Successful research, correct evidence, blocked anyway.

### Defect 5 — concept discovery has no enrolled provider

Visible in the live trace:

```
No configured provider: not configured for concept discovery
official requirements api: selected for official requirements (1800ms deadline)
```

The plan correctly requests two capabilities — `concept discovery` (what *is* this workload?)
and `official requirements` (what does it *need*?). Only the second is enrolled. This is
exactly the discovery-before-named-software stage the GPT notes argued for: the architecture
is present, the provider is not. Requirements can only be fetched for a workload already
named, which is the recognition dependency one layer down.

---

## Part 4 — What the research recommended vs. what is already built

The gap is materially narrower than the research notes assume. Most of the architecture landed
in the five commits; what is missing is the trigger and two providers.

| Recommendation | Status |
|---|---|
| Null class `UNRESOLVED_WORKLOAD` in closed vocabulary | **Built** — `research_routing.py:20` has `unresolved_workload` + `ambiguous_intent` as distinct literals (the MMShopBench split GPT asked for) |
| Fix the trace string | **Built** — "does not establish that research was unnecessary" |
| Bounded query bundles, not free-text search | **Built** — with explicit `prohibited_assumptions` per query |
| Rewrite-don't-enrich for unknown workloads | **Built** — planner emits paraphrase-shaped `identity` / `requirements` strategies, no pseudo-document generation (the SIGIR '25 Q2D failure mode is avoided by construction) |
| Interpretation ledger, bitemporal, retractable | **Built** — `semantic_belief_state.py` with supersession history |
| Consent-gated egress with provenance | **Built** and browser-certified |
| Coverage score + abstain below threshold | **Built but inoperative** — Defects 1–3 |
| Two triggers, gated on novelty not recognition | **Broken** — Defect 1 |
| Discovery research before named-software research | **Planned, no provider** — Defect 5 |
| Clarify slot by information gain over survivors | **Not built** — a single fixed question ("local, remote, or hybrid?") is emitted regardless of what would actually discriminate |
| Requirement floors as the primitive, personas as cache | **Not built** — still persona-keyed `use_case_registry` |
| Spanning/hedged retrieval under unresolved intent | **Not built** |
| Independent research labels | **Not built** — roadmap item 3 |

---

## Part 5 — Roadmap changes

### Item 1 is done

Backend restarted on HEAD, official-provider Playwright journey green with all Research & Fit
trace assertions. Close it.

### Insert a new item 1: make the trigger reachable

This is not on the roadmap and it is what the screenshots are about. Four contained fixes:

1. **Remove `not product_type_options` from the abstention guard**
   ([`turn_router.py:2423`](../src/app/services/recommendation_core/turn_router.py#L2423)).
   A product noun tells you the *form factor*, never the *purpose*. Keep the other three
   conditions. This alone converts case D into case E.
2. **Give the observer a null state.** Empty `semantic_proposal` must not return
   `catalog_sufficient`. Return a distinct `uninterpreted` state, or refuse to emit a
   recommendation at all. Silence is not coverage — the same principle the trace copy already
   applies one layer up.
3. **Re-scale or re-derive the score before calibrating anything.** Either drop the threshold
   below 0.425, or stop deriving `unknowns` 1:1 from `concepts` so the ratio can move, or
   populate the three dead features. Leaving it as-is makes item 4 (calibration) produce a
   model fitted to a constant.
4. **Strip meta-sentences before span extraction.** Consent, politeness, and instructions to
   the assistant are not purposes. Cheapest correct fix: extract spans from the buyer's
   product-intent clause only, or blocklist spans whose head noun is in a small meta set
   (`research`, `sources`, `it`, `that`). Without this, a consenting buyer with valid evidence
   still gets blocked.

Each is small, each is independently testable, and cases D/E above are ready-made regression
tests. Freeze them as a battery.

### Then item 2, with a correction

Provider enrollment is right, but it is **two** providers, not one. `official requirements` is
proven against the fixture. `concept discovery` has no provider at all and is the one that
answers "what is a digital-twin cyber range?" — the actual question in the screenshots.
Enrolling only the requirements provider leaves the recognition dependency intact.

### Item 4 (calibrate the trigger) must move after the new item 1

Running shadow traffic now would calibrate against a score pinned at 0.425 with 0.35 of its
weight unpopulated. The output would be noise wearing a number. Fix the feature pipeline first,
then collect.

### Items 3, 5–10 stand as written

The labels gap (3), split-brain removal (5), latency (6), the eight slates (7), IMAGE/voice
(8), pilot (9), `/suggest` retirement (10) are unaffected by these findings.

---

## Part 6 — Measurement

The research notes proposed four metrics. Two are now cheap to compute and one already has a
value:

- **Silent-misroute rate** — unknown workload routed to a named persona with no abstention
  signal. Case D is a confirmed instance. Currently **100% for product-noun queries** by
  construction of Defect 1.
- **Trigger reachability** — fraction of `unresolved_workload` observations whose
  recommendation is `research_candidate`. Currently **0%** (Defect 3). This one number would
  have caught the whole class.
- **Clarification precision** — fraction of asked questions whose answer changes the surviving
  candidate set. The fixed "local, remote, or hybrid?" question scores unknown but is emitted
  unconditionally, so it cannot be high.
- **Turns-to-resolution**, ambiguous vs unambiguous.

---

## Appendix — reproduction

```powershell
# 1. fixture provider (already running on :8099)
python tests/fixtures/fake_official_requirements_provider.py --port 8099

# 2. backend on HEAD with proof env
./scripts/start_official_research_proof_backend.ps1     # or uvicorn with the same 7 env vars

# 3. certified journey
cd frontend; npx playwright test e2e/official-research-authorization.spec.ts
```

Cases D/E were run via a temporary spec (since removed) that sends one query per fresh session
and reads the Research & Fit → Research Breakdown panel. Worth re-adding as a permanent
`e2e/unresolved-workload-abstention.spec.ts` once Defect 1 is fixed — asserting that
case D abstains rather than recommending.
