# Governed conversation and escalation

ShopSquire keeps parallel intelligence, but removes authority from unconstrained agent
conversation. The architecture separates interpretation, evidence gathering and state
mutation:

```text
buyer/operator turn
        |
        v
strict semantic proposal (dialogue act + exact references)
        |
        +--> JSON-schema rejection
        |
        v
tenant / epoch / case / SKU consistency check
        |
        v
deterministic reducer --> accept | clarify | reject
        |
        +--> accepted amendment invalidates prior temporal dependencies
        |             +--> CacheRAG rebuild queued; stale generation not served
        |             +--> Hippograph supersession edge (evidence-only)
        v
canonical case state
```

The model may propose a dialogue act. It cannot invent a case, product or order-line
reference, and it cannot mutate state. Unknown, ambiguous and model-failure results become
typed clarification rather than optimistic execution.

## Parallel evidence mesh

Evidence lanes remain concurrent and independent. Each lane has a time deadline and a
relative cost allocation. The aggregate result records `healthy`, `empty`, `degraded`,
`failed`, `timed_out` or `cancelled` per lane and groups contradictory claims. An admitted
request can therefore continue with partial read-only assistance without silently treating
missing evidence as clean or authoritative.

Running code cannot always be forcibly cancelled safely, so cancellation is cooperative:
unstarted lanes are cancelled before dispatch; running lanes require their transport-level
deadline and their late result is excluded after the orchestration deadline.

## Canonical escalation lifecycle

Procurement rooms, security incidents and external tickets remain domain-owned adapter
records. They project idempotently into one tenant-scoped escalation lifecycle and append-only
timeline. The canonical queue owns operator priority, SLA, assignment and state; it does not
rewrite the source systems.

```text
procurement room ----+
security incident ---+--> canonical escalation --> operator queue / API / Decision Trace
ticket --------------+             |
                                   +--> projection references retained
```

Legacy records without authoritative tenant ownership are reported as unowned and are not
projected by guessing a default tenant.

## Current proof boundary

- Strict proposal, consistency and reducer contracts are service-tested.
- Case amendments invalidate exact prior dependencies and append Hippograph supersession.
- Escalation APIs and the allocation workbench are tenant-scoped.
- Temporary-chat epoch rotation and the deterministic eight-buyer scenario are permanent
  browser regressions.
- The 20-turn browser contract proves session/correction/pronoun transport; it is not a claim
  that a mocked model response proves semantic quality.
- Live ticketing, supplier providers and tenant outcome data remain adapter/pilot work.

