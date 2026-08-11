# Research Gate — Adjudication, Narration Contract, Panel Design

**Date:** 2026-08-08 · **HEAD:** `58d87b03` · **Screenshot:** 54 "why is not researching"
**Prior:** [delta retest](SHOPSQUIRE_DELTA_RETEST_2026-08-08.md) · [cart/explain UX](SHOPSQUIRE_CART_EXPLAIN_UX_ASSESSMENT_2026-08-08.md)

---

## 0. The finding both analyses missed

Both read `Provider status: cost budget exceeded` as a spend governor doing its job.
Claude: *"governance cap tripped before the call."* GPT: *"the cost budget gate fired."*

It is not a spend guard. It is an integer that makes the leg **unreachable by construction**.

- [`evidence_orchestrator.py:107-115`](../src/app/services/evidence_orchestrator.py#L107) — `_LEG_COST_UNITS = {concept_resolution: 3, web: 5, market: 3, image: 2, …}`
- [`evidence_orchestrator.py:41`](../src/app/services/evidence_orchestrator.py#L41) — `EvidenceBudget.max_cost_units` default **12**
- [`core.py:960`](../src/app/services/recommendation_core/core.py#L960) — the semantic research path passes **`max_cost_units=3`**
- [`evidence_orchestrator.py:653-659`](../src/app/services/evidence_orchestrator.py#L653) — `if used_cost + cost > max: → cost_budget_exceeded`

```
semantic research budget = 3 units
  concept_resolution   cost=3  -> admitted (used=3)
  web                  cost=5  -> REJECTED (3+5 > 3)

web alone, on an empty budget: UNREACHABLE (5 > 3)
```

**The web leg has never run on this path. Not once. It cannot.** Even with every other leg
disabled, 5 > 3. There is no money involved — these are local effort units, not currency.

Two consequences that matter for the "don't spend money" constraint:

1. **You have never been billed for this**, because no call was ever made. The scary line in the
   trace costs nothing and always fires.
2. **Fixing it is a one-integer change**, and until you decide the provider question, the correct
   fix is to make the *message* honest rather than to raise the number.

This is the third instance of the same underlying disease I have now traced three times: a
**config/plumbing state rendering as an epistemic state**. A timed-out leg read as "catalog
sufficient". An unpopulated fit ledger read as "cannot explain". An unreachable leg reads as
"research budget exhausted". Every time, the buyer is told something about *knowledge* when the
truth is something about *wiring*.

---

## 1. Adjudication

### Where GPT is right, and it is the more important half

**"A search provider is not an authority."** This is the correct architectural correction and it
reframes the whole problem. Brave/Exa/Serper are *discovery*; the vendor document is the
*authority*. Separating `discovered_via` from `source_origin` / `authority_tier` makes the
discovery provider swappable and stops the provider choice from being load-bearing.

**"Explore before authority → assert fit after evidence → act only after authorization."**
Correct, and strictly better than the current `authority before catalog` policy, which is visible
in the live trace. Blocking *catalog exploration* on missing evidence is the single behaviour that
makes the product look incapable. Nothing is risked by showing laptops; what needs gating is the
*claim* ("verified fit") and the *action* (autonomous cart/RFQ/payment).

**The three-dimensional status model** — `execution` × `evidence` × `decision` — is cleaner than
Claude's flat five-value enum, and it is what the trace actually needs. Adopt GPT's version.

**"A supplier enquiry is an evidence-gathering action."** Sharp point. Gating an
information-request on lack of information is circular. That inverts one line of the current
`state_prevented` tuple.

### Where Claude is right

**Outcome vocabulary is collapsed.** This is the core observation and Claude made it first. GPT
refined it; the credit is Claude's.

**Sealed requirements corpus first.** Highest value per hour, zero cost, replayable, demo-safe —
and genuinely *more* defensible than live search, because pinned provenance beats "whatever the
index served that morning". For a procurement-audit product this is not a fallback, it is the
better artifact.

**"Blocking the conversation looks incapable; blocking authorization looks disciplined."** Same
insight as GPT's ladder, stated more memorably.

**The `use_case_kb.json` diagnosis is factually correct** — I verified it: exactly 11 personas
(`gaming, game_development, university, engineering_student, creative, corporate,
calls_productivity, ai_ml_workstation, general, primary_school, high_school`). No OT, no
cyber-range, no digital-twin. Which is exactly why "CGI video rendering" silently resolves to
`creative` and returns an 8GB-VRAM gaming laptop.

### Where both are wrong or off-target

1. **The cost-budget misdiagnosis** above.
2. **Both over-invest in provider selection.** Between them there are ~30 lines of Brave-vs-Exa-vs-
   Serper-vs-Tavily pricing. Given your constraint, that is the *least* urgent decision in the
   stack — you need approximately zero live searches to ship the demo and a pilot. I have not
   verified any of the quoted prices and would not act on them; the two analyses already
   contradict each other on Brave's attribution terms and Tavily's latency. **Defer the whole
   comparison.**
3. **Both treat this as a research problem.** It is a *state-model* problem that happens to be
   visible in the research lane. The same missing state model produced the turn-4 context loss and
   the empty fit ledger. Fixing providers without fixing the state model buys one screenshot.
4. **Neither addresses the panel**, which is where the buyer actually reads the answer.

### Verdict

**GPT's architecture, Claude's sequencing.** Adopt GPT's discovery/authority split, action ladder,
and 3-dimensional status. Execute in Claude's order: sealed corpus → provisional tier → outcome
codes → and only then, maybe, a provider.

---

## 2. The money answer

**You do not need a paid search provider for the demo or the first pilot.** The domain is bounded:
a laptop catalogue and a finite set of workload families. Live general web search is the wrong
tool for a bounded domain.

Cost ladder, cheapest first — stop as soon as it is good enough:

| Tier | Mechanism | Cost | Covers |
|---|---|---|---|
| 0 | **Local hypothesis** — embeddings over a workload hierarchy, not 11 flat personas | £0 | ~most turns |
| 1 | **Sealed requirements corpus** — approved docs, captured, hashed, tiered | £0 after capture | named workloads + demo path |
| 2 | **Evidence cache** keyed by normalised concept, freshness-tiered TTL (24h+ for spec material) | £0 | repeat + demo replay |
| 3 | **Self-hosted discovery** (SearXNG) + local extraction (Trafilatura/Crawl4AI) | £0, self-hosted | dev + novel concepts |
| 4 | **Paid discovery**, one provider, escalation-only | pennies/1k, rarely invoked | genuine long tail |

Tier 4 fires only when: concept confidence < τ **and** cache miss **and** corpus miss **and** the
turn is commercially material. That is a small fraction of turns, and it is the only tier that
costs anything.

Note your current TTL posture is inverted: session memory TTL is ~600s (right for utterances,
wrong for evidence). Spec material should cache for **days**, not minutes.

---

## 3. Reasoning from research, not deterministic code

The specific request: *reasoning based on research, not deterministic code*. The way to get that
without a regex treadmill is to change **what the model is asked to produce**, not how much
freedom it has.

Today the model is asked, effectively, "which of 11 personas is this?" — a closed classification
that must snap. Instead ask it for a **hypothesis distribution over a workload hierarchy**, then
let deterministic code do only what it is good at: arithmetic, thresholds, and refusal.

```
industrial_simulation
├── digital_twin
│   ├── physics_compute
│   └── 3d_visualisation
└── cyber_range
    ├── multi_vm
    ├── network_emulation
    └── ics_emulation
```

Model output (clamped to the hierarchy, never free text):

```
cyber_range        0.84
digital_twin       0.77
3d_visualisation   0.44
ai_training        0.11
```

Deterministic code then computes the **intersection floor** — requirements shared by all
hypotheses above τ — and the **divergent axes** — requirements the hypotheses disagree on:

```
SHARED (high confidence, all live hypotheses agree)
  cpu_cores >= 8      ram_gb >= 32      storage_nvme >= 1TB      virtualisation = required
DIVERGENT (hypotheses disagree — this is what to ask or research about)
  gpu_vram_gb: cyber_range says ~0 | 3d_visualisation says >= 12
```

That yields three things at once, with no new regex:

- an immediate shortlist (anything failing the **shared** floor is eliminated — 8GB/16GB laptops go
  regardless of which hypothesis is true),
- the **one** clarifying question worth asking (the divergent axis, chosen by which split reduces
  the candidate set most — not a budget question),
- an honest confidence label.

This is the same clamped-model doctrine already in the codebase, applied to *world description*
rather than *action selection*. The model gets more interpretive freedom; deterministic code keeps
all the authority. **Personas become cached floors, not the addressable object.**

---

## 4. Recommendation with and without a budget constraint

The current failure — asking "what budget range should I stay within?" after a $179,970 cart — is
because budget is treated as a retrieval slot rather than a **degree of freedom in a
constraint set**. There are four variables: *floor*, *budget*, *quantity*, *date*. A buyer
normally fixes two or three; the system's job is to name which one has to move.

**No budget stated** — do not ask. Derive it. Show the floor-satisfying set across the price range
and state the entry point:

> "Everything below meets the shared floor (8+ cores, 32GB+, NVMe, virtualisation). They start at
> $2,899. GPU need is unresolved — if your simulator does 3D, the $3,499+ tier applies."

Budget becomes an *observation* the buyer can react to, not a gate they must pass first.

**Budget stated and satisfiable** — normal ranking, plus headroom:

> "6 meet the floor within $3,000. The cheapest is $2,899; $101 headroom at 30 units = $3,030."

**Budget stated and NOT satisfiable** — this is the case that is currently missing entirely, and it
is where a procurement product earns its keep. Never silently return the nearest thing. Name the
conflict and enumerate the moves:

```
The accepted floor for this workload starts at $2,899/unit.
At 30 units that is $86,970 — your stated budget is $60,000.

  RELAX BUDGET     +$26,970 -> meets floor at 30 units
  REDUCE QUANTITY  20 units at $2,899 = $57,980  (within budget)
  SUBSTITUTE       [SKU] $1,999 meets 3 of 4 -- fails ram_gb (16 < 32)
                   -> would not run the workload; shown for completeness only
  SOURCE           draft supplier RFQ for a 30-unit price at this floor (human review)
  SPLIT            7 now within budget, 23 on a dated commitment
```

Each move is computed, not narrated — the arithmetic is deterministic, the *framing* is the model's
job. This also gives `align_catalog`'s existing `alternatives` bucket
([`core.py:1174`](../src/app/services/recommendation_core/core.py#L1174)) somewhere to be useful.

---

## 5. Narration contract

**Rule zero: never report a wiring state as a knowledge state.** Every research line must carry
`execution` and `evidence` separately.

```
execution : COMPLETED | TIMEOUT | ERROR | SKIPPED_BUDGET | NOT_CONFIGURED | CACHED
evidence  : NONE | PARTIAL | SUFFICIENT | CONTRADICTORY | NOT_ASSESSED
decision  : VERIFIED | PROVISIONAL | BLOCKED
```

Rendering rules:

| Condition | Say |
|---|---|
| `NOT_CONFIGURED` | "Live source lookup isn't enabled in this deployment." — a **configuration** statement, reads as deliberate |
| `SKIPPED_BUDGET` | "I didn't spend a live lookup on this turn." — never "pending" |
| `COMPLETED` + `NONE` | "I checked the approved source; it has nothing for this workload." |
| `COMPLETED` + `CONTRADICTORY` | "Two approved sources disagree; I won't pick one silently." |
| any + `PROVISIONAL` | "Shortlisted on a provisional profile — not a verified-fit claim." |

Three honesty bugs visible in screenshot 54, all in the same frame:

1. **`FRESHNESS: Current` while nothing was fetched.** Must be `Not assessed`.
2. **`UNCERTAINTY: Uncertainty unknown`** on a turn that is blocked *for* uncertainty. Must be
   `Material`.
3. **The refusal renders three times**, once inside "HELP ME NARROW THIS DOWN" — an affordance that
   must contain a *narrowing question*, never a block message. Same class as D3.

Replacement copy for the screenshot turn:

> This looks like an OT cyber-range / digital-twin workload. I can shortlist now on a provisional
> profile — 8+ cores, 32GB+ RAM, NVMe, virtualisation — which rules out most of the catalogue
> regardless of the exact simulator. GPU is the open question: heavy 3D changes the pick.
> Live vendor verification isn't enabled here, so these are provisional, not verified-fit.
> **Tell me the simulator, or [upload an approved requirements doc], and I'll tighten it.**

Capable and epistemically honest, rather than blocked.

---

## 6. Right panel — driven by the turn's dominant obligation

The panel is currently a fixed Cart/Upsell surface, so it shows an empty cart on a turn that is
about *research*. It should switch on the dominant obligation already computed by
`decompose_case_obligations` ([`cart_compound_response.py:105`](../src/app/services/recommendation_core/cart_compound_response.py#L105)).

| Dominant obligation | Panel mode | Persistent rail |
|---|---|---|
| unresolved / ambiguous workload | **Interpretation** | Purpose + hypotheses + floor |
| explain / compare | **Fit** | same rail, ledger expanded |
| product search | **Shortlist** | floor shown as active filter |
| qty / amend / clear | **Cart + pending plan** | floor stays visible |
| deadline / bulk | **Fulfilment** | floor + shortfall moves |
| policy / support | **Policy** | collapsed |

Crucially the **top rail never changes** — retained purpose, accepted floor, confidence. That rail
is the structural fix for "multi-turn isn't going back to the first reason why": if the floor is
always on screen, it cannot be lost between turns.

### Interpretation mode — what screenshot 54 should have shown

```
+-- [Interpretation] [Shortlist] [Cart] [Delivery] -------+
|                                                         |
| PURPOSE (retained)                              [edit]  |
|   "laptop for digital twin project, OT cyber            |
|    attack simulation"                                   |
|                                                         |
| WORKLOAD HYPOTHESES            local, unverified        |
|   cyber_range           0.84  ############              |
|   digital_twin          0.77  ##########                |
|   3d_visualisation      0.44  #####                     |
|                                                         |
| SHARED FLOOR      applies whichever is true             |
|   cpu_cores      >= 8                                   |
|   ram_gb         >= 32                                  |
|   storage_nvme   >= 1 TB                                |
|   virtualisation  required                              |
|   -> 6 of 42 catalogue items qualify                    |
|                                                         |
| OPEN QUESTION    the hypotheses disagree here           |
|   gpu_vram_gb    0  vs  >= 12                           |
|   [ heavy 3D ]  [ mostly VMs ]  [ not sure ]            |
|                                                         |
| EVIDENCE                                                |
|   concept discovery   NOT_CONFIGURED   not attempted    |
|   web lookup          SKIPPED_BUDGET   not attempted    |
|   official reqs api   COMPLETED        no match         |
|   local corpus        CACHED           2 claims  tier B |
|                                                         |
|   Provisional. Not a verified-fit claim.                |
|   [Upload approved requirements]  [Proceed provisional] |
+---------------------------------------------------------+
```

Every previously-hidden state is now a distinct, named line — and the buyer has three moves
instead of a dead end.

---

## 7. Roadmap

### Phase 0 — honesty, no new capability (hours)

1. **Three-dimensional status** through the evidence lane and into the trace.
   [`evidence_orchestrator.py:653-659`](../src/app/services/evidence_orchestrator.py#L653), [`trace_ontology.py`](../src/app/services/recommendation_core/trace_ontology.py), [`WorkloadResearchTrace.tsx`](../frontend/src/components/WorkloadResearchTrace.tsx).
2. **Fix the badges** — `FRESHNESS: Not assessed`, `UNCERTAINTY: Material` when blocked for uncertainty.
3. **Stop rendering the refusal inside "HELP ME NARROW THIS DOWN"** ([`gates.py:41-48`](../src/app/services/recommendation_core/gates.py#L41)); that affordance takes questions only.
4. **Decide the `max_cost_units=3` question deliberately** ([`core.py:960`](../src/app/services/recommendation_core/core.py#L960)). Either raise it so `web` (5) is reachable, or leave it and say `NOT_ENABLED` — but stop calling an unreachable leg "budget exceeded".

### Phase 1 — provisional tier (the demo unlock)

5. **Split the gate.** `PROVISIONAL` shortlists with an explicit unverified label; `VERIFIED` needs
   evidence; commerce actions stay gated. Loosen `authority before catalog` to
   *authority before **claims and autonomous actions***.
6. **Unblock supplier enquiry when it is evidence-gathering** — remove `supplier_enquiry` from
   `state_prevented` for information requests ([`semantic_resolution.py:611`](../src/app/services/semantic_resolution.py#L611) region).
7. **Buyer as authority** — real upload/paste affordance + a recorded "proceed unverified" consent
   event in the bitemporal decision log.

### Phase 2 — reasoning, zero marginal cost

8. **Workload hierarchy replaces 11 flat personas**; requirement floor becomes the addressable
   object, persona becomes a cached floor. Closes the CGI class.
9. **Intersection floor + divergent axis**; clarify slot selected by candidate-set reduction, not
   by a fixed question or by budget.
10. **Sealed requirements corpus** — capture date, licence, origin, trust tier; generalise the
    9 Steam fixtures and the `official_workload_sources.json` shape already present.
11. **Evidence cache**, normalised concept key, freshness-tiered TTL (days, not 600s).

### Phase 3 — budget/quantity/date reasoning

12. Constraint-conflict engine and the five moves in §4; wire `alternatives` into narration.

### Phase 4 — only now, a provider

13. SearXNG + local extraction for dev. One paid discovery provider behind an escalation gate, if
    tiers 0–3 measurably miss. Re-verify pricing at that point; do not act on either analysis's
    current figures.

### Prerequisite, from prior findings

Persisting the compiled floor + belief state across turns remains the highest-leverage item overall
— §6's persistent rail depends on it, and it is already half-landed in `78e5b408`.
