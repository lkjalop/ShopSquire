# Ambiguous procurement execution status

Date: 2026-08-08

This is the implementation checkpoint for the canonical ambiguous procurement
journey. It is deliberately stricter than a feature inventory: a phase is green
only where executable assertions prove the buyer-visible result, provider
accounting, decision authority, and retained compatibility.

## Acceptance contract

The canonical journey remains:

```text
clear stale cart
  -> ambiguous request
  -> immediate provisional local shelves
  -> one material question and four evidence choices
  -> upload/OCR claim review
  -> buyer accepts, rejects, or corrects claims
  -> optional governed discovery and authoritative corroboration
  -> verified/conditional/failed rerank
  -> budget, quantity, and deadline choices
  -> supplier enquiry only after authorization
  -> cart mutation only after explicit confirmation
```

The acceptance test must not be weakened to match incomplete implementation.
The deprecated V2 compatibility endpoint stays registered until every external
and operational gate below is green.

## Phase status

| Phase | Status | Executable evidence | Remaining red boundary |
|---|---|---|---|
| 0. Freeze contract | Green for clear-cart, local ambiguity exploration, upload review, and trace assertions | `canonical-ambiguous-procurement.spec.ts`; `uploaded-requirements-journey.spec.ts`; compatibility/cart regressions | Full supplier continuation is not yet in this one browser journey |
| 1. Catalog identity and evidence | Green for additive schema and reviewed seed | migration `20260860`; seed/unit tests | Real publisher refresh observations and wider reviewed ingest |
| 2. Buyer requirement acceptance | Backend green; UI partially green | exact requested accept endpoint; ownership, version, idempotency, accepted/rejected/corrected claims tests | Inline typed correction controls and PDF/TXT UI upload |
| 3. Ambiguous interpretation | Reducers green; live fallback partially green | bounded hypothesis compiler; provisional browser flow; normal-persona zero-call policy tests | If the model returns no hypotheses, the live fallback still needs a deterministic/model-independent bounded interpretation proposal and one high-information question |
| 4. Deterministic shelves | Reducer and provisional UI green | shared, hypothesis, budget/stretch, architecture, qualified/conditional/failed, top-3/next-5 tests | Follow-up constraints are not yet retained and rebound to the same shopping case in the live chat path |
| 5. Evidence acquisition | Policy and reachability green; live certification red | zero-cost ladder tests; concept+web effort allowance is reachable; paid accounting is explicit | No enrolled local SearXNG and authoritative-origin fixture has completed the browser rerank journey |
| 6. Narration and UX | Shadow critic and core panels green; integration partial | ambiguity, requirement-review, and shelf panels; narration adversarial tests | Shadow narration is not yet the live evidence-led copy; research delta and persistent retained-purpose rail are incomplete |
| 7. Quantity/deadline/supplier | Reducer/API green; browser continuation red | enough/split/wait/next-best/supplier/architecture/relax choices; no cart or supplier authority | RFQ fixture responses, buyer selection, and exact confirmed cart mutation are not wired into the canonical browser test |
| 8. Operational gates | Red by design | no dishonest promotion | Human labels, real-source certification, physical image/mic, hosted ASR/TTS, pilot identities, deliberate rollback |

## What is green now

### Exact configuration and evidence model

The additive schema records:

- manufacturer MPN, retailer SKU, retailer and source URL;
- exact configuration hash;
- device class, form factor and mobility;
- OS edition, GPU class, VRAM and TGP;
- installed RAM, ceiling and upgradeability;
- storage, warranty type and duration;
- per-location quantity and lead time;
- attested, derived, behavioural and substitutable claims;
- contradictory observations as separate rows;
- independent specification, price, and availability freshness.

The reviewed seed intentionally starts small: HP ZBook, HP Z2 Mini, MSI
Titan, ASUS Zephyrus, and GMR desktop. It preserves the RTX 5090 laptop versus
desktop VRAM distinction, GMR conflicting observations, and substitutable BOM
claims instead of manufacturing false certainty.

### Buyer-supplied requirement evidence

OCR or extracted text produces buyer-supplied, unverified claims. Screenshot 55
is parsed into reviewable CPU, virtualisation, RAM, storage, GPU, network, and OS
claims. The buyer can accept/reject them, and the endpoint supports corrected
typed values. Acceptance grants provisional exploration only:

```text
qualification authority: none
cart mutation: not authorized
external calls: 0
paid calls: 0
```

Endpoint:

```text
POST /api/v1/shopping-cases/{case_id}/requirement-proposals/{proposal_id}/accept
```

### Ambiguity, shelves and architecture alternatives

The core components are vertical-agnostic. They accept evidence-grounded
hypotheses and typed claims rather than hard-coding digital twins, Skyrim, AI,
CAD, or any other vertical. They compute shared intersections, divergent axes,
one eligible high-information question, and deterministic shelves.

All five infrastructure classes are projected without silently selecting one:
laptop, mobile workstation, fixed workstation, server, and cloud.

### Trace truth

`ambiguity_exploration_projected` and
`buyer_requirement_proposal_accepted` are first-class trace event types. They no
longer collapse into `feedback_loop`. The browser test reads the durable trace
event and verifies local execution, provisional evidence, no cart authority,
zero external calls, and zero paid calls.

## Next red browser journey

The next implementation slice must make this test pass without mocks that skip
the real adapters:

```text
Given:
  empty evidence cache
  paid discovery disabled
  tenant-authorized local SearXNG fixture
  allowlisted official-origin fixture

When:
  buyer authorizes "Research and corroborate"

Then trace must show:
  concept resolution        completed
  local discovery           completed, call count 1
  official origin fetches   exact expected count
  buyer upload claims       accepted provisional
  official claims           corroborated / contradicted / unresolved
  exact product identity    MPN + configuration hash
  paid calls                0
  cart authority            none

And the right panel must show:
  retained purpose
  before/after research delta
  reranked shared and hypothesis shelves
  each product's meets / conditional / unknown / misses / freshness
```

After that passes, extend the same browser test with budget AUD 6,000 each,
quantity 30, deadline 10 days, fixture availability 12, normalized supplier
responses, split selection, and one explicitly confirmed cart mutation.

## External dependencies that code cannot honestly fabricate

- An enrolled SearXNG endpoint or equivalent free discovery service.
- Allowlisted publisher/OEM origins and their retrieval policy.
- Credentials for sources that require them.
- Measured freshness observations and SLA breach behavior.
- Independent human judgments for the eight relevance slates.
- Physical microphone/device and hosted ASR/TTS access.
- Real pilot identities and an observed rollback exercise.

Until those are supplied and exercised, compatibility retirement remains
ineligible.

## Commit policy in the current worktree

The repository contains extensive pre-existing tracked and untracked work.
Do not use `git add -A`, bulk cleanup, or a mixed feature/hygiene commit. Finish
one acceptance slice, stage only its reviewed files/hunks, inspect the staged
diff, and keep generated cache cleanup separate. No compatibility file should
be deleted or rewritten as part of this work.
