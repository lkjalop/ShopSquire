# ShopSquire

> An evidence-governed commerce decision and bounded-agent platform.

ShopSquire adds a native intelligence and control layer to commerce operations. It can
stand on its own when a retailer does not have mature planning infrastructure, or
complement an existing ERP, commerce, planning or supply-chain platform.

It is **not** a replacement for NetSuite, SAP, Kinaxis, o9, Blue Yonder, Shopify or a
customer's system of record. Those systems remain authoritative. ShopSquire gives their
facts a governed path into recommendations, market intelligence, procurement proposals
and carefully bounded actions.

The core design rule is:

```text
observations -> evidence -> hypotheses -> proposals -> authorization -> execution
```

Model-generated text cannot skip those boundaries and become business authority.

The conversational control path is a constrained semantic proposal architecture: a model may
propose a typed dialogue act and exact references; JSON schema and tenant/case consistency
validate it; a deterministic reducer accepts, clarifies or rejects it. Parallel evidence lanes
remain concurrent, but commercial authority stays in canonical state, policy and explicit
authorization. See [Governed conversation and escalation](docs/architecture/GOVERNED_CONVERSATION_AND_ESCALATION.md).

## Why it exists

Most AI commerce demos optimize for a persuasive answer. ShopSquire explores the harder
problem: what may the system believe and do when customer intent, inventory, supplier
messages, forecasts and external market signals disagree?

It combines:

- conversational product discovery and recommendation;
- canonical inventory, currency and unit-of-measure semantics;
- forecast comparison and replenishment proposals;
- dependency-grounded market and supply-risk intelligence;
- governed procurement and supplier communication;
- tenant-scoped evidence, security gates and decision traces;
- shadow experiments, replay and bounded feedback through Hippograph.

## Three portfolio stories

The public project is intentionally presented through three end-to-end stories rather
than as a catalogue of screens and agents:

1. **Evidence-governed decisions** — a buyer request becomes a recommendation with
   provenance, uncertainty, explicit authority and a replayable Decision Trace.
2. **Supply intelligence to bounded procurement** — a market signal becomes relevant
   only through a time-valid component, supplier, facility, region, freight or substitute
   dependency path; the result is an option or proposal, never an unsupported causal claim.
3. **Attack-resistant bounded autonomy** — untrusted messages and attachments are
   observed, quarantined and enriched without being allowed to mutate quote, purchase-order,
   inventory or payment state. Consequential execution remains policy- and human-gated.

These stories share one canonical fact and control layer. They are not three disconnected
AI demonstrations.

## Platform map

```text
 Buyers / operators / suppliers / public sources / existing systems
                              |
                              v
 +------------------------------------------------------------------+
 | Connector and identity boundary                                  |
 | signed tenant | source authority | licensing | freshness | inbox |
 +-------------------------------+----------------------------------+
                                 |
                                 v
 +------------------------------------------------------------------+
 | Canonical observation and evidence layer                         |
 | products | parties | UoM | FX | inventory events | messages      |
 | append-only history | corrections | bitemporal provenance         |
 +-------------------------------+----------------------------------+
                                 |
              +------------------+------------------+
              v                                     v
 +-----------------------------+       +----------------------------+
 | Decision intelligence       |       | Trust and control          |
 | forecast + inventory        |       | evidence comparison        |
 | market + dependency paths   |       | quarantine + policy gates  |
 | recommendation + Hippograph |       | budgets + human approval   |
 +--------------+--------------+       +-------------+--------------+
                +----------------------+--------------+
                                       v
 +------------------------------------------------------------------+
 | Typed proposals and bounded execution                            |
 | recommendation | replenishment | RFQ draft | lifecycle | pricing |
 | idempotent jobs | durable outbox | rollback / abstention          |
 +-------------------------------+----------------------------------+
                                 |
                                 v
 +------------------------------------------------------------------+
 | Outcomes, calibration and decision trace                         |
 | actuals | counterfactuals | forecast value added | audit | replay |
 +------------------------------------------------------------------+
```

See [Platform architecture](docs/SHOPSQUIRE_PLATFORM_ARCHITECTURE_2026-07-29.md)
for the module-level diagrams and authority boundaries.

## Bounded autonomy

ShopSquire grants authority by action type, tenant, confidence, value limit and operating
mode. It does not have one global "autonomous" switch.

| Level | Behaviour | Current evidence |
|---|---|---|
| Observe | Ingest, normalize, trace and detect conflicts | Implemented locally |
| Advise | Forecast, explain, rank and propose options | Implemented locally |
| Prepare | Create case snapshots, RFQ drafts and bounded action plans | Implemented locally |
| Execute low-risk action | Only through policy, experiment and rollback gates | Narrow and feature-gated |
| Consequential execution | Purchase, payment and material lifecycle changes | Human/policy authorization required |

The platform is best described today as **strongly agentic in analysis and preparation,
selectively autonomous in low-risk reversible actions, and deliberately non-autonomous
for consequential commercial commitments**.

## Hippograph

Hippograph is ShopSquire's tenant-scoped feedback and relationship graph. It projects
decision traces, conversions, catalog relationships, market findings and optional human
feedback into a recall surface.

```text
 observed trace + outcome + finding + human correction
                         |
                         v
             tenant-scoped graph projection
                         |
                         v
           reward-weighted, decayed related recall
                         |
              +----------+-----------+
              v                      v
      evidence annotation     bounded shadow nudge
                                   |
                           experiment + rollback gate
```

It helps the platform remember which products, findings and relationships have mattered
in similar contexts without treating graph recall as truth. Recall is advisory by default.
A ranking nudge is capped, auditable, reversible and experiment-gated; the current offline
evaluation does not justify enrolling Hippograph as a general V2 ranking authority.

## Trust architecture

Trust comes from inspectable constraints, not an assertion that an agent is trustworthy:

- signed or authoritative tenant context at production boundaries;
- append-only observations with provenance, event time and availability time;
- explicit `observed`, `derived`, `estimated`, `simulation_only` and unknown states;
- currency and UoM comparability gates;
- dependency paths before external signals become product exposure claims;
- contradiction and incomparable-scope handling;
- bounded tools, deadlines, idempotency and durable job state;
- quarantine for untrusted supplier content;
- separate proposal, authorization and execution records;
- immutable case-context snapshots and bitemporal audit;
- kill switches, shadow modes, counterfactual replay and rollback.

These mechanisms are exercised with deterministic replay, adversarial tests and local
production-shaped browser tests. They are not a substitute for real-world outcome evidence.

## What is proven, and what is not

| Claim | Status |
|---|---|
| Canonical contracts, governance boundaries and deterministic replay | Tested locally |
| V2 recommendation routing and archived legacy router | Implemented and characterized |
| Forecast model discrimination on replayable synthetic histories | Tested locally |
| Tenant-scoped supply-risk and procurement workbenches | Implemented locally |
| Malicious supplier content cannot directly change economic state | Covered by service/browser regressions |
| Hosted worker/browser, service, V2 and security workflows | Proven on the publication branch; general contract matrix still being closed |
| PostgreSQL production-shaped migration evidence | Empty PostgreSQL migration rehearsal is proven; retained hosted upgrade/rollback evidence remains a release gate |
| Live Gmail/M365 and ERP/provider certification | Not claimed |
| Reduced stockouts, increased margin or supplier performance | Requires a design-partner shadow pilot |

Synthetic data is used to prove invariants, failure behaviour, model discrimination and
replayability. It is permanently marked `simulation_only`; it is not evidence of business lift.

## A 12-minute demo

1. **Buyer decision:** enter a constrained request and show the recommendation, authority
   path and decision trace.
2. **Forecast:** compare seasonal naive, EWMA, Croston/SBA and TSB, including WAPE, MASE,
   bias, uncertainty and explicit insufficient states.
3. **Supply risk:** open a disruption scenario and show the time-valid dependency path,
   source licence, contradictions, alternative explanations and bounded impact range.
4. **Procurement:** open the immutable case snapshot, supplier evidence, landed-cost
   comparison and gated RFQ proposal.
5. **Attack resistance:** replay a malicious trusted-domain supplier response and show
   unchanged quote, PO, economics and payment state.
6. **Replay:** show the seed, event ledger, correction/reversal and counterfactual result.

The concise interview narrative and the concepts behind the demo are in the
[AI/ML portfolio guide](docs/SHOPSQUIRE_AI_ML_PORTFOLIO_DEMO_GUIDE_2026-07-29.md).
Hosted run IDs, artifact boundaries and the recording sequence are pinned in the
[procurement demonstration evidence index](docs/demo/PROCUREMENT_DEMONSTRATION_EVIDENCE.md).

## Local start

Prerequisites vary by profile. The default development profile uses Python, Node, Docker,
PostgreSQL and Redis; model and external-provider credentials are optional for the
credential-free demo paths.

```powershell
Copy-Item .env.example .env
docker compose up -d --build
Invoke-RestMethod http://127.0.0.1:8080/healthz
```

| Surface | Default URL |
|---|---|
| Storefront | `http://127.0.0.1:5173` |
| Admin workbench | `http://127.0.0.1:3001` |
| API and integrated merchant surfaces | `http://127.0.0.1:8080` |
| API documentation | `http://127.0.0.1:8080/docs` |

For targeted development:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d db redis
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn src.app.main:create_app --factory --port 8080
```

Run the storefront or admin app from its own package directory with `npm install` and
`npm run dev`.

## Verification

```powershell
# Focused AI/ML and UI portfolio proof
.\scripts\run_ai_ml_portfolio_proof.ps1 -IncludeUi

# Python tests
.\.venv\Scripts\python.exe -m pytest -q

# Storefront
Push-Location frontend
npm test
npm run build
Pop-Location

# Admin
Push-Location src/frontend/admin-react
npm test
npm run build
Pop-Location
```

The repository includes isolated service-test sharding and a production-shaped browser
harness. A local green run is reported as local evidence; hosted-runner and live-provider
claims require retained artifacts from those environments.

## Integration position

ShopSquire can use a customer's platform as the authority:

```text
 ERP / OMS / WMS / planning / commerce / CRM
                    |
           read facts and constraints
                    v
              ShopSquire
 evidence + proposals + governed communication + bounded actions
                    |
         write back only when authorized
```

Where a smaller operator lacks those capabilities, ShopSquire's canonical event model,
forecasting, procurement casework and operator workbenches provide a useful native base.
The same contracts allow later replacement by an authoritative enterprise source without
rewriting the decision layer.

## Current priorities

The highest-value next step is proof, not another broad feature wave:

1. publish reproducible hosted CI and PostgreSQL migration artifacts;
2. close the remaining general-suite failures as V2, compatibility, characterization,
   protocol, certification-fixture or current-policy contracts;
3. run a design-partner shadow pilot using real orders, ATP, receipts, invoices and outcomes;
4. seal independent human relevance judgments;
5. deploy one minimal cloud reference environment after the hosted gates are green;
6. strangle remaining oversized composition surfaces such as `chat.py` and simplify `main.py`
   only where this reduces duplicate authority or operational risk.

External email and ERP credentials are deliberately outside the credential-free demo claim.

## Documentation

- [Platform architecture](docs/SHOPSQUIRE_PLATFORM_ARCHITECTURE_2026-07-29.md)
- [AI/ML portfolio and demo guide](docs/SHOPSQUIRE_AI_ML_PORTFOLIO_DEMO_GUIDE_2026-07-29.md)
- [Agnostic market and procurement roadmap](docs/AGNOSTIC_MARKET_PROCUREMENT_ROADMAP_2026-07-27.md)
- [Auditable procurement architecture](docs/SHOPSQUIRE_AUDITABLE_PROCUREMENT_DEMO_ARCHITECTURE_2026-06-26.md)
- [Attribution backbone](docs/SHOPSQUIRE_ATTRIBUTION_BACKBONE_ARCHITECTURE_2026-06-25.md)

## Honest limitations

- The public repo is an engineering portfolio and prototype, not a deployed customer product.
- Real commercial uplift has not been established.
- External provider activation and authoritative ERP reconciliation remain environment-specific.
- Broad codebase size and older surfaces still create maintenance cost despite the V2 cutover.
- Security and governance controls reduce risk; they do not make prompt injection, data
  poisoning or operational error impossible.

ShopSquire's defensible claim is not "AI runs the company." It is that AI can participate in
commerce decisions while facts, uncertainty, authority and outcomes remain inspectable.
