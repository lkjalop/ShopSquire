# ShopSquire Auditable Procurement Demo Architecture

**Date:** 2026-06-26  
**Status:** Proposed canonical implementation plan  
**Purpose:** Turn the existing buyer recommendation, inventory, supplier-draft, approval, trace, market-intelligence, and experiment foundations into one defensible end-to-end commerce demonstration.

---

## 1. Executive Decision

The next showcase should not be another broad dashboard or a claim that autonomous commerce works in the abstract.

Build one deeply inspectable journey:

> A buyer requests a bulk order. ShopSquire decomposes the request, recommends suitable products, checks stock, detects a shortfall, selects an approved supplier, drafts the exact quote request, stops at a visible approval boundary, sends through a sandbox transport, receives a correlated supplier reply, validates the quote, offers fulfilment choices, records the buyer's selection, and preserves every change in the bitemporal decision trace.

This journey demonstrates the platform's differentiators with evidence:

- complex NLP and multimodal understanding;
- product recommendation and rationale;
- authoritative inventory checks;
- supplier selection and constrained interaction;
- bounded autonomy and human escalation;
- exact external-message provenance;
- quote and delivery reasoning;
- buyer-facing fulfilment options;
- bitemporal state changes;
- policy and audit controls;
- market intelligence as additional context, not unsupported decoration.

The platform should clearly label simulated components:

- `SYNTHETIC MARKET REPLAY`
- `SANDBOX SUPPLIER`
- `SANDBOX EMAIL TRANSPORT`
- `DEMO QUOTE RESPONSE`

The code path must otherwise be the real path used by production adapters.

---

## 2. Browser and Surface Strategy

Use **two browser tabs**, not three.

### Tab A: Buyer Storefront

URL:

```text
http://127.0.0.1:5173
```

Responsibilities:

- accept buyer text and image input;
- display recommendations and evidence;
- display bulk availability;
- show quote progress without exposing supplier-private details;
- present fulfilment choices;
- allow the buyer to select together, split, or substitute fulfilment;
- open the Decision Trace for an authorized demo operator.

### Tab B: Operator Control Room

Recommended URL:

```text
http://127.0.0.1:5173/admin/procurement
```

Alternative if the current admin React application remains separately hosted:

```text
http://127.0.0.1:<admin-port>/procurement
```

Responsibilities:

- show the procurement case journey;
- review and edit pending supplier messages;
- approve or reject outbound contact;
- show the sandbox outbox and inbox;
- inspect the supplier quote and parsed fields;
- compare estimated and confirmed fulfilment;
- inspect market signals, findings, graph context, policy checks, and bitemporal audit;
- trigger deterministic demo actions.

### Backend API

The API remains on:

```text
http://127.0.0.1:8080
```

Do **not** make the API root a third primary demo tab. A backend-served sandbox mailbox page may exist for development, but the recording should expose it inside the Operator Control Room.

### Optional Developer-Only Mailbox

```text
http://127.0.0.1:8080/ui/demo-mailbox
```

This is useful for connector testing, not as a primary audience-facing surface.

---

## 3. Refactor and Excision Before Adding Features

The implementation should reduce ownership confusion before adding the procurement workflow.

### 3.1 `routers/recommend.py`

Current size: approximately 11,500 lines.

Extract the bulk-fulfilment block currently around the late recommendation path into the existing stage pattern:

```text
src/app/services/recommend_fulfillment_stage.py
```

Move:

- quantity and delivery-horizon handoff;
- availability assessment invocation;
- fulfilment summary construction;
- procurement-case creation trigger;
- availability and supplier-draft trace events;
- buyer-facing fulfilment response contract.

Keep in `recommend.py`:

- route dependency wiring;
- stage invocation;
- final payload assembly.

Do not put supplier email parsing, approval mutation, or quote lifecycle logic in `recommend.py`.

### 3.2 `frontend/src/components/DecisionTrace.tsx`

Current size: approximately 193 KB. This is already too large to safely add another substantial tab.

Refactor into a small shell plus grouped concerns:

```text
frontend/src/components/decision-trace/
  DecisionTrace.tsx
  DecisionTraceData.ts
  DecisionTraceCommerce.tsx
  DecisionTraceSecurity.tsx
  DecisionTraceAudit.tsx
  DecisionTrace.module.css
```

Avoid one file per tiny panel. Group related tabs:

- `DecisionTraceCommerce.tsx`
  - Summary
  - Why Recommended
  - Intent
  - Memory
  - Fulfilment Journey
- `DecisionTraceSecurity.tsx`
  - Multimodal
  - Complexity
  - Security Matrix
- `DecisionTraceAudit.tsx`
  - Events
  - Bitemporal Audit
  - Raw
- `DecisionTraceData.ts`
  - API loading
  - websocket/SSE handling
  - event selectors
  - display normalization

Delete the stale backup after verifying the live component:

```text
frontend/src/components/DecisionTrace.tsx.bak_utf8
```

Do not delete it until the extracted implementation passes component and Playwright tests.

### 3.3 `services/inventory_agent.py`

Current size: large and handling monitoring, supplier ranking, reorder recommendation, approval, PO persistence, and reconciliation.

Extract without duplicating logic:

```text
src/app/services/supplier_selection.py
src/app/services/purchase_order_service.py
```

Move to `supplier_selection.py`:

- candidate supplier lookup;
- cost, lead-time, MOQ, on-time, reliability, and SLA scoring;
- supplier trust calculation;
- supplier-score audit persistence.

Move to `purchase_order_service.py`:

- approval verification;
- purchase-order persistence;
- execution bundle creation;
- PO execution trace events.

Keep in `inventory_agent.py`:

- stock monitoring;
- reorder recommendation calculation;
- inventory-specific rule evaluation;
- orchestration calls to the extracted services.

### 3.4 Supplier Communication Files

Do not create separate services for draft, send, receive, parsing, correlation, and quote validation.

Consolidate the external interaction boundary into:

```text
src/app/services/external_party_communication.py
src/app/ports/external_communication.py
src/app/adapters/email/supplier_email.py
```

`external_party_communication.py` owns:

- message draft contract;
- approval state;
- dispatch request;
- inbound message correlation;
- structured response parsing;
- provenance and trace emission.

`external_communication.py` owns only transport protocols:

- send;
- receive/poll;
- provider reference;
- delivery status.

`supplier_email.py` is an ecommerce adapter:

- supplier quote-request template;
- supplier reply mapping;
- email subject/reference conventions.

Deprecate or turn these into compatibility facades:

```text
src/app/services/supplier_communication.py
src/app/services/reorder_supplier_flow.py
```

Do not maintain two independent send gates.

### 3.5 Approvals

Reuse:

```text
src/app/routers/approvals.py
```

Do not create a second procurement-only approval engine.

Add procurement metadata to the existing approval payload:

```json
{
  "capability": "supplier_contact",
  "case_id": "FC-2026-0041",
  "message_id": "MSG-2026-0091",
  "recipient_domain": "approved-supplier.example",
  "commercial_scope": {
    "sku": "LAP-021",
    "quantity": 6,
    "estimated_value_cents": 669000
  }
}
```

### 3.6 Admin Frontend

Reuse and extend:

```text
src/frontend/admin-react/src/components/Approvals.tsx
src/frontend/admin-react/src/components/InventorySync.tsx
src/frontend/admin-react/src/components/EscalationsConsole.tsx
src/frontend/admin-react/src/components/MerchantBIPro.tsx
```

Create only one new page:

```text
src/frontend/admin-react/src/components/ProcurementCases.tsx
```

This page composes existing approval, inventory, trace, and intelligence APIs. Do not create separate top-level pages for supplier drafts, mailbox, quotes, and fulfilment.

---

## 4. Bounded Context and File Consolidation

Use one fulfilment bounded context rather than a collection of unrelated flat services.

```text
src/app/services/fulfillment/
  domain.py
  repository.py
  workflow.py
  api_models.py
```

### `domain.py`

Contains:

- enums;
- dataclasses;
- state transition rules;
- fulfilment option generation;
- invariant checks.

Core concepts:

```text
DemandRequest
SupplyPosition
ExternalPartyRequest
ExternalPartyResponse
FulfillmentCase
FulfillmentOption
FulfillmentSelection
ApprovalBoundary
```

No words such as laptop, fashion, medicine, GPU, size, dosage, or supplier email belong in this file.

### `repository.py`

Contains:

- durable case persistence;
- version writes;
- current-state reads;
- bitemporal as-of reads;
- message and quote persistence;
- idempotency.

### `workflow.py`

Contains:

- case creation from recommendation output;
- stock-shortfall handling;
- external quote request creation;
- approval handoff;
- dispatch;
- inbound response handoff;
- option recomputation;
- buyer selection;
- execution handoff.

It calls existing policy, approval, inventory, trace, and transport services. It does not reimplement them.

### `api_models.py`

Contains request and response schemas used by the router and frontend.

### Router

Use one router:

```text
src/app/routers/fulfillment_cases.py
```

Do not create separate quote, supplier mailbox, fulfilment option, and procurement routers.

---

## 5. Agnostic Core and Ecommerce Adapters

### Agnostic Core

The core understands:

- requested item references;
- requested quantities;
- available quantities;
- external parties;
- lead times;
- quoted amounts;
- option sets;
- approvals;
- execution state;
- evidence;
- temporal revisions.

### Ecommerce Adapter

The ecommerce adapter understands:

- SKU;
- supplier;
- unit cost;
- MOQ;
- warehouse;
- purchase order;
- shipment;
- product variant;
- customer-facing delivery promise.

Suggested adapter:

```text
src/app/adapters/ecommerce/fulfillment.py
```

Responsibilities:

- map product results to `DemandRequest`;
- resolve SKU inventory;
- resolve supplier candidates;
- map supplier quote fields;
- identify substitutable products using the active StoreProfile;
- map a fulfilment selection to PO and shipment actions.

### Vertical StoreProfile Data

Keep vertical wording and substitution dimensions in profile data:

```json
{
  "fulfillment_substitution_dimensions": [
    "use_case_fit",
    "price_band",
    "performance_tier",
    "form_factor"
  ],
  "supplier_message_templates": {
    "quote_request": {
      "subject": "...",
      "body": "..."
    }
  }
}
```

Electronics may define GPU, RAM, display, weight, and warranty compatibility in adapter/profile data. The core only receives normalized fit and constraint evidence.

---

## 6. Durable Data Model

Avoid duplicating the complete decision log. The fulfilment tables hold domain state; `decision_logs` and `decision_trace_events` hold the audit narrative.

### 6.1 `fulfillment_case`

```text
id
tenant_id
buyer_uid_hash
source_trace_id
status
requested_by
created_at
updated_at
```

### 6.2 `fulfillment_case_version`

```text
id
case_id
state
state_json
reason_code
actor_type
actor_id
valid_from
valid_to
system_from
system_to
supersedes_version_id
```

This is the bitemporal source for procurement state.

### 6.3 `external_message`

```text
id
case_id
direction
transport
message_type
recipient_ref
sender_ref
subject
body
status
approval_id
provider_ref
correlation_key
created_at
sent_at
received_at
```

Statuses:

```text
draft
pending_approval
approved
rejected
sent
delivered
received
parse_failed
quarantined
```

### 6.4 `external_quote`

```text
id
case_id
message_id
party_ref
currency
quoted_quantity
unit_amount_cents
available_quantity
dispatch_ready_at
estimated_delivery_at
quote_expires_at
substitution_json
confidence
validation_status
evidence_json
created_at
```

### 6.5 `fulfillment_option`

```text
id
case_id
option_type
title
allocation_json
estimated_delivery_at
total_amount_cents
constraints_satisfied_json
tradeoffs_json
status
created_at
```

Option types:

```text
ship_together
ship_available_then_remainder
substitute_all
substitute_shortfall
cancel_or_reduce
```

### 6.6 `fulfillment_selection`

```text
id
case_id
option_id
selected_by
selected_at
execution_status
provider_refs_json
```

---

## 7. State Machine

```text
NEW
  -> AVAILABILITY_ASSESSED
  -> QUOTE_DRAFTED
  -> AWAITING_APPROVAL
  -> QUOTE_SENT
  -> AWAITING_EXTERNAL_RESPONSE
  -> QUOTE_RECEIVED
  -> QUOTE_VALIDATED
  -> OPTIONS_READY
  -> AWAITING_BUYER_SELECTION
  -> SELECTED
  -> PROCUREMENT_APPROVAL_REQUIRED
  -> PROCUREMENT_IN_PROGRESS
  -> PARTIALLY_READY | READY_TO_SHIP
  -> COMPLETED
```

Failure states:

```text
NO_APPROVED_SUPPLIER
RECIPIENT_BLOCKED
QUOTE_EXPIRED
QUOTE_PARSE_FAILED
SUPPLIER_RESPONSE_QUARANTINED
DELIVERY_CONSTRAINT_UNMET
POLICY_BLOCKED
BUYER_DECLINED
```

Every transition must:

1. validate the current state;
2. identify the actor;
3. record evidence IDs;
4. write a new bitemporal version;
5. emit a trace event;
6. preserve the prior version.

---

## 8. Required Trace Events

Use stable event contracts:

```text
bulk_request_decomposed
availability_assessed
supplier_candidates_ranked
external_message_drafted
approval_requested
approval_granted
approval_rejected
external_message_sent
external_message_received
supplier_response_parsed
supplier_quote_validated
fulfillment_options_generated
buyer_fulfillment_selected
purchase_order_proposed
purchase_order_approved
purchase_order_created
shipment_plan_created
fulfillment_state_superseded
```

Each event should contain:

```json
{
  "case_id": "FC-2026-0041",
  "actor": {
    "type": "agent",
    "id": "Availability_Agent"
  },
  "input_evidence_ids": ["INV-SNAPSHOT-22"],
  "output_artifact_ids": ["MSG-2026-0091"],
  "policy": {
    "decision": "human_review",
    "rule_id": "SUP-04"
  },
  "bitemporal": {
    "valid_from": "2026-06-26T09:14:00Z",
    "system_from": "2026-06-26T09:14:01Z"
  }
}
```

Do not persist hidden chain-of-thought. Persist:

- inputs;
- evidence;
- evaluated factors;
- reason codes;
- policy result;
- proposed action;
- confidence;
- outcome.

Call this **decision rationale**, not private model reasoning.

---

## 9. Buyer UX

### 9.1 Initial Bulk Recommendation

```text
+--------------------------------------------------------------------------------+
| ShopSquire                                                      Cart (0)       |
+--------------------------------------------------------------------------------+
| "I need 10 portable laptops for a university design team, under $1,500 each,  |
|  delivered within two weeks. Why these?"                                      |
+--------------------------------------------------------------------------------+
| UNDERSTOOD                                                                     |
|  Quantity 10   Budget <= $1,500 each   Deadline 14 days   Use: design + travel |
+--------------------------------------------------------------------------------+
| RECOMMENDED                                                                    |
|                                                                                |
| Lenovo Pro 14                         $1,449        4 currently available       |
| Strong fit: portable, display, memory and workload requirements                |
| [View evidence] [Compare]                                                      |
|                                                                                |
| Dell Studio 14                        $1,479        10 available                |
| Stronger immediate availability; slightly heavier                              |
| [View evidence] [Compare]                                                      |
+--------------------------------------------------------------------------------+
| PROCUREMENT CHECK                                                              |
| 4 available now. Checking approved suppliers for the remaining 6.              |
| Case FC-2026-0041                                      [View journey]          |
+--------------------------------------------------------------------------------+
```

### 9.2 Quote Pending

```text
+--------------------------------------------------------------------------------+
| Procurement update: FC-2026-0041                                  In progress  |
+--------------------------------------------------------------------------------+
| 4 units reserved locally                                                       |
| 6-unit supplier quote awaiting approval                                        |
| Current estimate: complete order within 7-9 days                               |
|                                                                                |
| No order has been placed and no delivery promise has been confirmed.           |
+--------------------------------------------------------------------------------+
```

### 9.3 Buyer Fulfilment Choice

```text
+--------------------------------------------------------------------------------+
| Supplier availability confirmed                                                |
+--------------------------------------------------------------------------------+
| Requested: 10 Lenovo Pro 14                                                     |
| Available now: 4                                                               |
| Supplier-confirmed: 6, dispatch-ready 3 July                                   |
| Estimated complete delivery: 8 July                                            |
|                                                                                |
| Choose fulfilment                                                              |
|                                                                                |
| (*) Ship all 10 together                                                       |
|     One delivery on or around 8 July.                                           |
|                                                                                |
| ( ) Ship 4 now and 6 later                                                      |
|     Fastest partial fulfilment; two deliveries may create extra handling.       |
|                                                                                |
| ( ) Use Dell Studio 14 for the remaining 6                                     |
|     Complete sooner; mixed fleet and slightly higher total cost.                |
|                                                                                |
| [Confirm selection]                                                            |
+--------------------------------------------------------------------------------+
```

Buyer-facing requirements:

- distinguish estimate from supplier confirmation;
- never present a draft as sent;
- never present a quote as an accepted PO;
- never expose supplier-private cost or contact information;
- clearly identify split shipment tradeoffs;
- provide a trace link without overwhelming the buyer.

---

## 10. Decision Trace: New Fulfilment Journey Tab

Add:

```text
Events | Summary | Why | Intent | Fulfilment Journey | Multimodal | Security | Audit
```

### Wireframe

```text
+--------------------------------------------------------------------------------+
| Decision Trace: TRACE-92A...                                      [Close]       |
+--------------------------------------------------------------------------------+
| Events | Summary | Why | Intent | FULFILMENT JOURNEY | Security | Audit        |
+--------------------------------------------------------------------------------+
| FC-2026-0041                                             Awaiting buyer choice  |
| Buyer request: 10 units | deadline 14 days | budget <= $1,500 each             |
+--------------------------------------------------------------------------------+
| 09:14  Buyer Request                                                            |
|        Quantity and deadline extracted with 0.94 confidence                     |
|        Evidence: query text, QueryPlan v1                                       |
|                                                                                |
| 09:14  Inventory Assessment                                                     |
|        LAP-021: 4 local, shortfall 6                                             |
|        Snapshot INV-22 | warehouse SYD-01                                       |
|                                                                                |
| 09:14  Supplier Selection                                                       |
|        Selected SUP-7 from 3 approved suppliers                                 |
|        Cost 35% | lead time 25% | on-time 20% | reliability 10% | MOQ 5%       |
|        [Inspect candidates]                                                     |
|                                                                                |
| 09:15  Outbound Quote Request                                      APPROVAL     |
|        Rule SUP-04: external commercial contact requires review                 |
|        [Inspect exact email] [View approval]                                    |
|                                                                                |
| 09:18  Human Approval                                                          |
|        Approved by owner-01 | content hash 9ac...                               |
|                                                                                |
| 09:18  Sandbox Email Sent                                                       |
|        Provider ref DEMO-MSG-82910 | trusted domain yes                         |
|                                                                                |
| 09:26  Supplier Reply Received                                                  |
|        Correlation FC-2026-0041 | DKIM/demo trust accepted                      |
|                                                                                |
| 09:26  Quote Parsed and Validated                                                |
|        Qty 6 | dispatch 3 July | expiry 28 June | confidence 0.96               |
|                                                                                |
| 09:27  Fulfilment Options Generated                                             |
|        Together | split | substitute                                             |
+--------------------------------------------------------------------------------+
| Bitemporal comparison                                                           |
| Initial estimate: 7 days     valid 09:14-09:26                                  |
| Confirmed dispatch: 3 July   valid from 09:26                                   |
+--------------------------------------------------------------------------------+
```

### Exact Email Drawer

```text
+--------------------------------------------------------------------------+
| Outbound message MSG-2026-0091                        PENDING APPROVAL     |
+--------------------------------------------------------------------------+
| From: procurement@merchant.example                                      |
| To: quotes@approved-supplier.example                                     |
| Subject: Availability and quote request - LAP-021 x 6 - FC-2026-0041     |
| Recipient trust: Approved supplier domain                                |
|                                                                          |
| Hello TechData Procurement,                                              |
|                                                                          |
| Please confirm availability for LAP-021, quantity 6...                   |
|                                                                          |
| This request does not constitute a purchase order.                       |
|                                                                          |
+--------------------------------------------------------------------------+
| Policy SUP-04: human review required                                     |
| [Edit draft] [Reject] [Approve and send]                                 |
+--------------------------------------------------------------------------+
```

Edits must create a new message version and preserve the prior body/hash.

---

## 11. Operator Control Room

### Navigation

```text
Procurement Cases | Pending Approvals | Mailbox | Market Intelligence | Audit
```

These are tabs inside one operator page, not separate browser tabs.

### 11.1 Procurement Cases

```text
+--------------------------------------------------------------------------------+
| Procurement Cases                                             [Run demo case]  |
+--------------------------------------------------------------------------------+
| Case          Buyer request       Status                 Deadline   Action       |
| FC-0041       10 x LAP-021         Awaiting buyer choice  12 Jul     [Open]       |
| FC-0040       25 x MON-009         Quote pending          15 Jul     [Open]       |
+--------------------------------------------------------------------------------+
| Selected case                                                                   |
| [Journey] [Inventory] [Supplier] [Messages] [Options] [Audit]                  |
+--------------------------------------------------------------------------------+
```

### 11.2 Pending Approvals

```text
+--------------------------------------------------------------------------------+
| Pending External Actions                                                       |
+--------------------------------------------------------------------------------+
| Quote request to approved supplier                                             |
| Case FC-0041 | LAP-021 x 6 | estimated commercial scope $6,690                 |
|                                                                                |
| Why review is required                                                         |
| - external commercial communication                                             |
| - recipient and message must be verified                                       |
| - request may cause a supplier to reserve stock                                |
|                                                                                |
| [Inspect evidence] [Edit message] [Reject] [Approve and send]                  |
+--------------------------------------------------------------------------------+
```

### 11.3 Sandbox Mailbox

```text
+--------------------------------------------------------------------------------+
| SANDBOX MAILBOX                                    Outbox | Inbox | Quarantine |
+--------------------------------------------------------------------------------+
| OUT 09:18  FC-0041  Quote request sent                    Delivered            |
| IN  09:26  FC-0041  Re: quote request                     Parsed 96%            |
+--------------------------------------------------------------------------------+
| Supplier reply                                                                 |
| We can supply 6 units at $1,115 each. Ready to dispatch on 3 July...           |
|                                                                                |
| Parsed                                                                         |
| Quantity 6 | unit cost $1,115 | dispatch 3 Jul | quote expires 28 Jun          |
| [View raw] [Compare parsed] [Accept evidence] [Quarantine]                     |
+--------------------------------------------------------------------------------+
```

### 11.4 Market Intelligence

Do not attempt to simulate a continuous production dashboard. Show a labelled replay:

```text
+--------------------------------------------------------------------------------+
| Market Intelligence                                      SYNTHETIC REPLAY      |
+--------------------------------------------------------------------------------+
| Replay: "University procurement demand - 7 compressed days"                   |
| [Reset] [Load days 1-5] [Advance day 6] [Advance day 7]                       |
+--------------------------------------------------------------------------------+
| Signals 95 | Active findings 3 | Shadow actions 2 | Graph entities 18         |
|                                                                                |
| Demand index       10  11  10  12  11  25  60                                 |
| Conversion rate    8%  8%  7%  8%  8%  6%  2%                                 |
| Inventory          32  29  24  18  12   7   4                                 |
|                                                                                |
| Findings                                                                       |
| CRITICAL Demand spike       60 vs baseline 11                                  |
| WARN     Conversion drop    2% vs baseline 7.8%                                |
| CRITICAL Inventory mismatch repeated zero/insufficient results                 |
|                                                                                |
| [Graph] [Evidence rows] [Shadow proposals]                                     |
+--------------------------------------------------------------------------------+
```

Graph presentation:

- show nodes and edges;
- show edge provenance;
- show reward and human-feedback influence;
- show before/after counts;
- do not rely on decorative animation as proof.

---

## 12. Supplier Response Handling

### Correlation

Every outbound message includes:

```text
Case reference: FC-2026-0041
Message reference: MSG-2026-0091
```

Inbound matching order:

1. provider thread/message reference;
2. reply headers;
3. case reference in subject/body;
4. approved supplier identity;
5. quarantine if correlation remains ambiguous.

### Parsing

Parse into a strict schema:

```json
{
  "quoted_quantity": 6,
  "unit_amount_cents": 111500,
  "currency": "AUD",
  "dispatch_ready_at": "2026-07-03",
  "estimated_delivery_at": "2026-07-08",
  "quote_expires_at": "2026-06-28",
  "substitutions": [],
  "confidence": 0.96,
  "evidence_spans": [
    {
      "field": "quoted_quantity",
      "text": "supply 6 units"
    }
  ]
}
```

The parser may use an LLM, but:

- the raw message remains authoritative evidence;
- every field carries evidence spans;
- low-confidence or contradictory fields route to review;
- parsed output never directly creates a PO.

### Demo Supplier

Implement one deterministic sandbox adapter:

```text
src/app/adapters/email/demo_supplier_mailbox.py
```

It should:

- store the outbound message;
- wait for an explicit demo action;
- produce one of several deterministic replies;
- preserve provider-like message IDs and timestamps.

Scenarios:

```text
full_quote
partial_availability
late_delivery
substitute_offer
expired_quote
untrusted_sender
contradictory_quantity
```

---

## 13. Fulfilment Option Logic

The core planner receives normalized facts:

```text
requested quantity
local quantity
confirmed external quantity
delivery dates
allowed substitutes
buyer constraints
shipping capabilities
cost and policy bounds
```

It returns ranked options with explicit tradeoffs.

### Ship Together

Use when:

- complete quantity can arrive before deadline;
- buyer did not request partial urgency;
- consolidated handling is preferred.

### Ship Available Then Remainder

Use when:

- partial shipment is supported;
- buyer benefits from immediate units;
- split-shipping cost/policy is acceptable.

### Substitute

Use when:

- the original product cannot satisfy deadline;
- substitute satisfies hard constraints;
- product fit remains within configured tolerance;
- buyer explicitly confirms the changed product.

### Never Do Automatically

- silently mix product variants;
- exceed buyer budget;
- claim a delivery date not supported by inventory or quote evidence;
- send a PO based only on parsed email text;
- expose wholesale cost to the buyer;
- contact an unapproved supplier;
- use an expired quote.

---

## 14. API Contract

Use one bounded router:

```text
GET    /api/v1/fulfillment/cases
POST   /api/v1/fulfillment/cases
GET    /api/v1/fulfillment/cases/{case_id}
GET    /api/v1/fulfillment/cases/{case_id}/journey
GET    /api/v1/fulfillment/cases/{case_id}/as-of
POST   /api/v1/fulfillment/cases/{case_id}/draft-quote
POST   /api/v1/fulfillment/cases/{case_id}/request-approval
POST   /api/v1/fulfillment/cases/{case_id}/dispatch
POST   /api/v1/fulfillment/cases/{case_id}/demo-reply
POST   /api/v1/fulfillment/cases/{case_id}/validate-quote
POST   /api/v1/fulfillment/cases/{case_id}/select-option
POST   /api/v1/fulfillment/cases/{case_id}/execute
```

Existing approval endpoints remain authoritative:

```text
GET  /api/v1/approvals
POST /api/v1/approvals/{approval_id}/approve
POST /api/v1/approvals/{approval_id}/reject
```

Do not add separate approval endpoints under fulfilment.

---

## 15. Security and Bounded Autonomy

### Draft

Automatic:

- allowed supplier candidates may be evaluated;
- a message may be drafted;
- evidence may be collected;
- a case may be opened.

### Send

Requires:

- explicit approval;
- exact message hash approval;
- approved sender identity;
- approved supplier domain;
- MAESTRO boundary pass;
- execution-gate authorization;
- configured non-null transport;
- idempotency key.

### Receive

Requires:

- sender/domain verification;
- thread/reference correlation;
- attachment/link security checks;
- quarantine on identity mismatch;
- immutable raw-message retention policy.

### PO Creation

Requires:

- validated quote;
- quote not expired;
- quantity and cost within approval scope;
- supplier trust above configured floor;
- buyer option selected;
- authorization gate;
- PO idempotency.

---

## 16. Market Intelligence in the Procurement Journey

Market intelligence should inform, not dominate, the buyer recommendation.

Example:

```text
Buyer fit             highest priority
hard constraints      mandatory
inventory truth       mandatory
supplier confirmation mandatory for future availability
market findings       supporting context
historical outcomes   supporting context
```

Useful procurement findings:

- demand rising while stock is falling;
- recurring bulk demand;
- conversion drop caused by unavailable products;
- supplier lead-time deterioration;
- returns increasing for a product or substitute;
- quote rejection rate increasing;
- fulfilment option preference by segment.

The demo should show:

```text
Finding -> shadow action -> procurement case evidence
```

It should not automatically convert:

```text
Demand spike -> send campaign
```

until experiment, contact, and campaign governance are fully proven.

---

## 17. Realistic Demo Script

### Setup

Seed:

- 4 local units of `LAP-021`;
- buyer requests 10;
- one approved supplier can provide 6;
- supplier lead time 7 days;
- one substitute has 10 local units but a meaningful tradeoff;
- deterministic seven-day market replay.

### Recording

1. Open Buyer Storefront.
2. Ask:

   > I need 10 portable laptops for a university design team under $1,500 each within two weeks. Why these?

3. Show decomposition:
   - quantity 10;
   - budget ceiling;
   - use cases;
   - delivery horizon;
   - constraints.
4. Show recommendations with evidence.
5. Show inventory:
   - 4 local;
   - 6 shortfall;
   - no unsupported delivery promise.
6. Open Decision Trace, Fulfilment Journey.
7. Switch to Operator Control Room.
8. Show supplier candidate factors and selected approved supplier.
9. Open the exact pending email.
10. Edit one harmless field and show a new message version/hash.
11. Approve and send through the sandbox transport.
12. Show outbox provider reference.
13. Trigger deterministic supplier reply.
14. Show raw reply beside parsed quote fields and evidence spans.
15. Return to Buyer Storefront.
16. Show:
   - ship together;
   - split shipment;
   - substitute option.
17. Select one option.
18. Show the bitemporal state change and approval requirement.
19. Show the audit tab:
   - actors;
   - policy rule;
   - message hash;
   - valid/system times;
   - superseded estimates.
20. Open Market Intelligence in the operator tab.
21. Advance the compressed replay and show signals/findings change.
22. Explain that the replay uses synthetic events but the ingestion, analysis, decision, policy, and trace path is real.

---

## 18. Implementation Roadmap

### Phase 0: Correctness Prerequisites

Before building the showcase:

- remove runtime market-signal index drop/recreation;
- preserve demand spike/slowdown direction in finding evidence;
- expire findings that are no longer observed;
- fix the ranking-nudge integration test;
- enforce experiment assignment and attribution windows;
- make contact-history failures fail closed.

Exit:

- focused adaptive-growth suite green;
- no known contradictory market action;
- no campaign or supplier action can bypass a gate.

### Phase 1: Extraction and Contracts

Build:

- `recommend_fulfillment_stage.py`;
- Decision Trace extraction;
- supplier selection extraction;
- purchase order extraction;
- fulfilment core contracts;
- external communication port.

Exit:

- no buyer-visible behavior change;
- contract and parity tests green;
- no-flavour and silent-except ratchets green.

### Phase 2: Durable Fulfilment Case

Build:

- migration;
- repository;
- workflow;
- state machine;
- bitemporal versions;
- case journey API.

Exit:

- bulk recommendation creates one idempotent case;
- current and as-of state queries work;
- every transition emits a trace event.

### Phase 3: Exact Draft and Approval

Build:

- actual supplier identity/contact resolution;
- exact quote-request draft;
- message versioning;
- existing approvals integration;
- policy and MAESTRO evidence;
- pending email UI.

Exit:

- operator can inspect/edit/reject/approve;
- editing invalidates the prior approval hash;
- default transport sends nothing.

### Phase 4: Sandbox Send and Reply

Build:

- demo supplier mailbox adapter;
- provider-like references;
- deterministic inbound scenarios;
- reply correlation;
- raw/parsed comparison;
- quote validation.

Exit:

- approved message appears in outbox;
- correlated reply appears in inbox;
- invalid/untrusted reply quarantines;
- quote never directly creates a PO.

### Phase 5: Fulfilment Options and Buyer Choice

Build:

- together/split/substitute planner;
- buyer-facing option UI;
- option selection endpoint;
- superseding case state;
- delivery-promise wording.

Exit:

- buyer can select an option;
- hard constraints cannot be silently relaxed;
- every option includes evidence and tradeoffs.

### Phase 6: Operator Control Room

Build:

- `ProcurementCases.tsx`;
- journey;
- pending approvals;
- mailbox;
- market intelligence;
- audit composition.

Exit:

- recording requires only two browser tabs;
- no raw DB console is necessary;
- every demo claim is inspectable from the UI.

### Phase 7: Market Replay

Build:

- versioned replay fixture;
- reset/load/advance controls;
- signal/finding/graph counts;
- evidence table;
- explicit synthetic labels.

Exit:

- before/after state is deterministic;
- replay does not modify non-demo tenants;
- graph and findings link back to raw synthetic events.

### Phase 8: Production Adapters

Only after the sandbox journey is proven:

- SendGrid/M365/SMTP outbound adapter;
- inbound mailbox/webhook adapter;
- NetSuite/SAP/Coupa/Ariba PO adapter;
- carrier/shipping adapter;
- real supplier portal/API adapter.

Exit:

- connector contract tests;
- secret management;
- retry/idempotency;
- provider reconciliation;
- production rollout remains default-off.

---

## 19. Test Strategy

### Unit

- state transition invariants;
- quote parsing;
- option generation;
- message hashing;
- supplier ranking;
- bitemporal supersession;
- adapter mapping.

### Integration

- recommendation -> case creation;
- inventory -> shortfall;
- shortfall -> draft;
- approval -> sandbox send;
- reply -> validated quote;
- quote -> options;
- selection -> PO proposal;
- policy block and quarantine paths.

### Playwright

1. Buyer submits bulk query.
2. Procurement status appears.
3. Operator sees pending draft.
4. Operator edits and approves.
5. Sandbox outbox updates.
6. Supplier reply appears.
7. Buyer options update without page reload.
8. Buyer selects split shipment.
9. Decision Trace shows the new version.
10. Audit shows valid/system times and message hash.

Avoid fixed waits. Wait for:

- specific status;
- case event;
- mailbox row;
- websocket/SSE update;
- trace event type.

---

## 20. What Is Real, Simulated, and Deferred

### Real

- buyer query and image handling;
- query decomposition;
- recommendation logic;
- inventory reads;
- supplier ranking foundation;
- draft generation;
- approval system;
- execution and MAESTRO gates;
- trusted-domain control;
- decision trace;
- bitemporal decision columns;
- experiment and rollback foundation;
- market-signal and finding foundation.

### Simulated but Production-Shaped

- market traffic history;
- supplier mailbox;
- supplier reply;
- provider message references;
- quote and dispatch confirmation;
- elapsed time.

### Deferred

- real supplier send;
- real inbound mailbox;
- real supplier reservation;
- real PO transmission;
- carrier booking;
- payment terms;
- tax and landed cost;
- multi-warehouse optimization;
- autonomous campaigns and offers.

---

## 21. Defensible Claims

Safe:

> ShopSquire demonstrates a governed buyer-to-procurement workflow using the real recommendation, inventory, policy, approval, communication-contract, and decision-trace architecture. Synthetic market and supplier adapters provide deterministic inputs for the demonstration.

Safe:

> Every external action is inspectable, approval-bound, provenance-linked, replayable, and represented as a bitemporal state change.

Unsafe until production adapters exist:

> ShopSquire autonomously emails real suppliers and places live purchase orders.

Unsafe until production traffic exists:

> ShopSquire has proven conversion uplift from market adaptation.

---

## 22. Immediate Build Order

1. Complete Phase 0 correctness fixes.
2. Extract the fulfilment stage and Decision Trace shell.
3. Add durable fulfilment cases and trace events.
4. Surface the exact supplier draft and approval boundary.
5. Add the sandbox mailbox and deterministic supplier replies.
6. Add fulfilment options and buyer selection.
7. Add the Operator Control Room.
8. Add the compressed market replay.
9. Run the full Playwright recording path.
10. Only then wire real external transports.

This order produces a credible showcase early while keeping the agnostic core, ecommerce adapter, policy boundary, and audit model suitable for production expansion.
