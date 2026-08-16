# ShopSquire conversational spatiotemporal case roadmap

Date: 2026-08-16

## Verdict

ShopSquire's next problem is not adding another retrieval, graph, forecasting or
supplier engine. Those engines already exist and have meaningful isolated tests.
The missing seam is a canonical procurement case that survives multi-turn edits
and compiles the right bounded query for each engine.

The correct authority split is:

```text
BUYER LANGUAGE / UPLOAD / VOICE
              |
              v
MODEL PROPOSES TYPED PATCHES
              |
              v
DETERMINISTIC CASE REDUCER
  revision + totals + provenance + authority
              |
              v
CANONICAL PROCUREMENT CASE
              |
              +------------------------+
              |                        |
              v                        v
     WORKLOAD RESEARCH          SPATIOTEMPORAL QUERY
 semantic dimensions only      spatial/temporal/commercial
              |                        |
              v                        v
  accepted requirements       ATP / forecast / days cover
              |                allocation / PromiseGraph
              +------------+-----------+
                           v
                REQUIREMENT/CAPABILITY JOIN
                           |
                           v
             TECHNICAL / DEADLINE / COMMERCIAL SHELVES
                           |
                           v
             SUPPLIER SHORTFALL + HUMAN CONFIRMATION
                           |
                           v
               ONE ADJUDICATED DECISION TRACE
```

The model interprets language. It never computes stock, route feasibility,
days-cover, price, fulfilment promises, or commercial authority.

## What was implemented in this slice

- `ProcurementCaseState` is a strict typed contract for objective, workloads,
  quantity, money, destination allocations, temporal scope, requirements,
  research, fulfilment, and authority.
- `CasePatch` supports atomic set/add/remove operations and quantity movement
  between destinations.
- Patch application is revision-bound and validates that destination quantities
  still sum to the requested total.
- A failed operation rejects the entire patch set; earlier operations do not leak.
- `SpatioTemporalQuery` is compiled from retained case state, not the latest
  utterance.
- Workload discovery excludes destination tokens; logistics discovery includes
  them. This prevents the Cairns/Cairn failure without globally banning location.
- Relative date text remains unresolved until a timezone-aware instant exists.
  An unresolved date cannot become a delivery promise.
- The model router may emit case patches, but changed values must be grounded in
  the current buyer utterance before the durable reducer may accept them.
- The existing `conversation_case_state` now carries the typed projection beside
  its legacy flat keys. V2 remains compatible.
- Typed patch history is append-only, idempotent, revision-bound, and explicitly
  grants no cart/RFQ/payment/shipping authority.

## Research assessment

The handoff's research direction is broadly supported, with four caveats.

1. Structured memory is useful, but a model-managed summary is not transactional
   truth. ProductAgent reports gains from structured dialogue memory and iterative
   clarification. COMPASS identifies context management as a long-horizon agent
   bottleneck. ShopSquire should therefore use typed durable state as the context
   manager, not treat raw chat history as the state.

2. Spatial interpretation and spatial computation are separate. Spatial-RAG
   combines semantic intent with a structured spatial database rather than asking
   an LLM to perform geography. ShopSquire should follow the same split for supply
   locations, lanes, calendars, ATP, and PromiseGraph.

3. Relevance is not authority. RA-RAG shows why source reliability must be
   considered separately from topical relevance. ShopSquire should preserve
   separate relevance, authority, and exact-version applicability verdicts; it
   should not average them into one publisher score.

4. Complex allocation belongs in a solver. OPT-Engine reports that tool-integrated
   solving remains more robust as optimization complexity grows and that constraint
   formulation is the bottleneck. The typed case is therefore a prerequisite for
   a later LP/MIP allocation solver, not a replacement for one.

Primary references:

- ProductAgent, EMNLP 2025: https://aclanthology.org/2025.emnlp-industry.25/
- COMPASS, ACL 2026: https://aclanthology.org/2026.acl-long.152/
- Spatial-RAG, ACL 2026: https://aclanthology.org/2026.findings-acl.539/
- DiscoBench, 2026: https://arxiv.org/abs/2606.27669
- Retrieval-Augmented Clarification, 2026: https://arxiv.org/abs/2601.11722
- Reliability-Aware RAG, EMNLP 2025: https://aclanthology.org/2025.emnlp-main.1738/
- DeepPlanning, ACL 2026: https://aclanthology.org/2026.acl-long.335/
- OPT-Engine, 2026: https://arxiv.org/abs/2601.19924
- Temporal GraphRAG, 2025: https://arxiv.org/abs/2510.13590

These papers support the architectural direction; they do not certify the
ShopSquire implementation. Browser artifacts and deterministic tests remain the
implementation evidence.

## Required next vertical slice

### 1. Case creation must consume typed patches before retrieval

The response-time integration currently persists patches only when a durable case
already exists in the response. The next change is to create/resolve the case at
the start of the turn, load its current revision, and pass that state into the
router. This removes the remaining post-response side channel.

### 2. Add a temporal authority service

Resolve expressions such as `next Thursday` with:

```text
original expression
buyer/store timezone
interpretation instant
resolved UTC instant
calendar source/version
resolution confidence
```

Ambiguous expressions remain unresolved and produce one clarification. Never
replace an unresolved deadline with prose such as “before the field team leaves.”

### 3. Connect state to deterministic engines

```text
ProcurementCaseState
  -> requirement/capability fit
  -> network ATP by exact configuration and location
  -> demand forecast and post-transfer days cover
  -> route/calendar feasibility
  -> allocation solver
  -> PromiseGraph explanation
  -> supplier shortfall options
```

Use the existing seeded procurement services. Do not build a second conversational
fulfilment implementation.

### 4. Canonical trace adjudication

One reducer must project the visible truth:

```text
research.execution = NOT_ATTEMPTED | DISCOVERY_ONLY | OFFICIAL_FETCH_PARTIAL | COMPLETE
evidence.status     = NONE | CANDIDATE_ONLY | ACCEPTED_PARTIAL | ACCEPTED_COMPLETE
freshness           = CURRENT | STALE | UNKNOWN
decision.status     = PROVISIONAL | CONDITIONAL | QUALIFIED | FAILED
commerce.authority  = NONE | CONFIRMATION_PENDING | ACTION_ALLOWED
```

Diagnostic observers may disagree, but no tab may independently label authority,
freshness, execution, or paid calls.

## Browser acceptance contract

Turn 1:

```text
We need 60 engineering laptops: 40 to Sydney and 20 to Perth.
They need Unreal Engine, large CAD models and simulation.
At least 30 must arrive within four days. Budget is AUD 220,000.
Do not leave an origin below seven days of cover.
```

Expected state:

```text
quantity                  60
destinations              Sydney 40 / Perth 20
workloads                 Unreal / CAD / simulation
required-by               explicit timezone-aware instant or unresolved
minimum early arrival     30
budget                    AUD 220,000 total
post-transfer cover       >= 7 days
external calls            0 before authorization
```

Turn 2:

```text
Reduce Perth by 5 and move those units to Sydney. Keep total 60.
```

Expected state:

```text
Sydney                    45
Perth                     15
total                     60
workloads                 unchanged
deadline                  unchanged
budget                    unchanged
cover policy              unchanged
case revision             +1
```

The platform must not ask again what the laptops are for.

Then authorize research and assert:

- workload queries contain Unreal/CAD/simulation terms but not Sydney or Perth;
- logistics queries may contain Sydney and Perth but cannot establish workload
  requirements;
- every network call has a query hash and typed receipt;
- paid calls remain zero;
- accepted official requirements join the same case revision;
- ATP, days cover and arrival calculations carry independent observation times;
- product rank movement has a typed reason;
- unavailable/unknown never becomes zero or safe;
- supplier shortfall is a proposal only;
- no cart mutation occurs before revision-bound buyer confirmation.

## Metamorphic and adversarial matrix

- `40 Sydney / 20 Perth`, `forty to Sydney and twenty to Perth`, and reordered
  wording produce equivalent typed allocations.
- Changing only Sydney to Melbourne changes only one location dimension.
- Moving five units preserves the total and every unrelated field.
- A stale revision cannot apply a second move.
- Cairns destination never becomes a workload/software token.
- A location may enter logistics/regulatory queries only when query purpose allows it.
- A future inventory observation cannot affect a historical replay.
- Unknown supplier capacity stays unknown.
- One failed destination, publisher, or carrier does not erase successful results.
- Browser disconnect cancels or quarantines late work and never strands the case.

## Honest current status

This slice establishes and persists the missing contract. It does not yet prove
the full natural-language browser journey green. Remaining work is:

1. load the typed case before the model/router call;
2. resolve and persist typed patches before downstream retrieval;
3. add temporal expression authority;
4. wire the compiled query into ATP/forecast/PromiseGraph/allocation/supplier paths;
5. replace contradictory Decision Trace projections with one adjudicator;
6. run and seal the multi-turn browser certificate.

Temporal GraphRAG, forecasting foundation models, and advanced market intelligence
remain later improvements. They will not repair state continuity and should not
precede this wiring.
