# ShopSquire v2.0 Executive Architecture Deck

> **Purpose**: Business-focused architecture presentation for CTOs and AI Architects
> **TOGAF ADM**: 20% Vision | 30% Business | 25% Information Systems | 25% Technology
> **Format**: 16:9 wide, left-to-right flow, visual ASCII art

---

## Slide 1: Architecture Vision
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│      ███████╗██╗  ██╗ ██████╗ ██████╗ ███████╗ ██████╗ ██╗   ██╗██╗██████╗ ███████╗                  │
│      ██╔════╝██║  ██║██╔═══██╗██╔══██╗██╔════╝██╔═══██╗██║   ██║██║██╔══██╗██╔════╝                  │
│      ███████╗███████║██║   ██║██████╔╝███████╗██║   ██║██║   ██║██║██████╔╝█████╗                    │
│      ╚════██║██╔══██║██║   ██║██╔═══╝ ╚════██║██║▄▄ ██║██║   ██║██║██╔══██╗██╔══╝                    │
│      ███████║██║  ██║╚██████╔╝██║     ███████║╚██████╔╝╚██████╔╝██║██║  ██║███████╗                  │
│      ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚══════╝ ╚══▀▀═╝  ╚═════╝ ╚═╝╚═╝  ╚═╝╚══════╝                  │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║            MODULAR AGENTIC E-COMMERCE: COMPLIANCE-FIRST AI AUTOMATION                      ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│                                                                                                      │
│     ┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐                    │
│     │                 │          │                 │          │                 │                    │
│     │   AUTONOMOUS    │    ──►   │   EXPLAINABLE   │    ──►   │    COMPLIANT    │                    │
│     │   OPERATIONS    │          │   DECISIONS     │          │    BY DESIGN    │                    │
│     │                 │          │                 │          │                 │                    │
│     │  80% tasks      │          │  Every AI       │          │  EU AI Act      │                    │
│     │  without human  │          │  decision       │          │  ISO 42001      │                    │
│     │  intervention   │          │  traceable      │          │  NIST AI RMF    │                    │
│     │                 │          │                 │          │                 │                    │
│     └─────────────────┘          └─────────────────┘          └─────────────────┘                    │
│                                                                                                      │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  "Agents handle routine. Humans govern strategy. Every decision is audit-ready."           ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- Solo architect delivery in 3 weeks demonstrates rapid enterprise capability
- Key differentiator: Not just AI automation, but *governable* AI automation
- Addresses emerging regulatory requirements before they become mandatory

---

## Slide 2: The Business Problem We Solve
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    WHY CUSTOM AGENTS? THE COMPLIANCE GAP                                   ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                         TODAY'S AI PLATFORMS                                                │  │
│     │                                                                                             │  │
│     │    ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐                          │  │
│     │    │ ChatGPT  │     │ Generic  │     │ Low-Code │     │ Prompt-  │                          │  │
│     │    │ Wrappers │     │ Copilots │     │ AI Bots  │     │ Only     │                          │  │
│     │    └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘                          │  │
│     │         │                │                │                │                                │  │
│     │         └────────────────┴────────────────┴────────────────┘                                │  │
│     │                                   │                                                         │  │
│     │                                   ▼                                                         │  │
│     │                    ╔═══════════════════════════════╗                                        │  │
│     │                    ║     MISSING FOR ENTERPRISE    ║                                        │  │
│     │                    ╠═══════════════════════════════╣                                        │  │
│     │                    ║  ✗ Decision audit trail       ║                                        │  │
│     │                    ║  ✗ Bi-temporal provenance     ║                                        │  │
│     │                    ║  ✗ Cost control (token burn)  ║                                        │  │
│     │                    ║  ✗ Security shift-left        ║                                        │  │
│     │                    ║  ✗ Human escalation gates     ║                                        │  │
│     │                    ╚═══════════════════════════════╝                                        │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                              │                                                       │
│                                              ▼                                                       │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                         SHOPSQUIRE APPROACH                                                 │  │
│     │                                                                                             │  │
│     │    SECURITY ──► RULES ──► AI ──► TRACE ──► HUMAN (if needed)                               │  │
│     │       │           │       │        │            │                                           │  │
│     │    Scan first  90% no   Budget   Every      $250+ or                                        │  │
│     │    block bad   tokens   capped   decision   low confidence                                  │  │
│     │    inputs      needed   per-user logged     escalates                                       │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- EU AI Act Article 14 requires human oversight for high-risk AI systems
- Most AI platforms are "fire and forget" - no audit trail
- Bi-temporal trace: "What did the AI know, and when did it know it?"
- This is the regulatory moat custom agents provide

---

## Slide 3: Build vs Buy Decision Criteria
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                      BUILD vs BUY: THE DECISION MATRIX                                     ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │  EVALUATION CRITERIA                                                                        │  │
│     │                                                                                             │  │
│     │  ┌───────────────────────┬────────────────────────────────────────────────────────────────┐ │  │
│     │  │ Criterion             │ BUILD if...                          BUY if...                 │ │  │
│     │  ├───────────────────────┼────────────────────────────────────────────────────────────────┤ │  │
│     │  │ Competitive Advantage │ Core differentiator logic            Commodity function        │ │  │
│     │  │ Compliance Control    │ Must own audit trail                 Vendor handles compliance │ │  │
│     │  │ Data Sovereignty      │ PII must stay in-region              No sensitive data         │ │  │
│     │  │ Cost at Scale         │ Volume makes custom cheaper          Low volume, SaaS works    │ │  │
│     │  │ Security Boundary     │ Need internal inspection             Trust vendor security     │ │  │
│     │  └───────────────────────┴────────────────────────────────────────────────────────────────┘ │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌────────────────────────────────────┐      ┌────────────────────────────────────┐               │
│     │            BUY (SaaS)              │      │            BUILD (Custom)          │               │
│     │                                    │      │                                    │               │
│     │  ┌────────────────────────────┐    │      │  ┌────────────────────────────┐    │               │
│     │  │ Stripe · PayPal · Afterpay │    │      │  │ Agent Orchestrator         │    │               │
│     │  │ Payment processing         │    │      │  │ Decision routing + trace   │    │               │
│     │  └────────────────────────────┘    │      │  └────────────────────────────┘    │               │
│     │  ┌────────────────────────────┐    │      │  ┌────────────────────────────┐    │               │
│     │  │ Shipping carriers          │    │      │  │ Security Observer          │    │               │
│     │  │ Label generation           │    │      │  │ PII scan, threat detection │    │               │
│     │  └────────────────────────────┘    │      │  └────────────────────────────┘    │               │
│     │  ┌────────────────────────────┐    │      │  ┌────────────────────────────┐    │               │
│     │  │ CDN · Static hosting       │    │      │  │ Transaction Firewall       │    │               │
│     │  │ Global delivery            │    │      │  │ Policy gates, escalation   │    │               │
│     │  └────────────────────────────┘    │      │  └────────────────────────────┘    │               │
│     │                                    │      │  ┌────────────────────────────┐    │               │
│     │  WHY: PCI offloaded               │      │  │ Bi-Temporal Audit          │    │               │
│     │       Fast integration             │      │  │ Immutable decision log     │    │               │
│     │       Vendor handles liability     │      │  └────────────────────────────┘    │               │
│     │                                    │      │                                    │               │
│     │                                    │      │  WHY: Compliance ownership         │               │
│     │                                    │      │       90% cost reduction            │               │
│     │                                    │      │       Audit-ready by design        │               │
│     └────────────────────────────────────┘      └────────────────────────────────────┘               │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- Key insight: BUILD the governance layer, BUY the commodity functions
- Payment processing: Never build - PCI DSS liability belongs with Stripe
- AI decision logic: Always build - this is where compliance risk lives
- The "90% cost reduction" comes from rules-first design (explained next)

---

## Slide 4: Business Capability Map
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    BUSINESS CAPABILITY → AGENT MAPPING                                     ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                CUSTOMER JOURNEY                                             │  │
│     │                                                                                             │  │
│     │     DISCOVER          EVALUATE          PURCHASE          RECEIVE          SUPPORT         │  │
│     │         │                 │                 │                │                │             │  │
│     │         ▼                 ▼                 ▼                ▼                ▼             │  │
│     │    ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐         │  │
│     │    │ Recommend│      │  Fraud  │      │  Order  │      │Inventory│      │Complaint│         │  │
│     │    │  Agent   │      │ Scorer  │      │Processor│      │  Agent  │      │  Agent  │         │  │
│     │    └─────────┘      └─────────┘      └─────────┘      └─────────┘      └─────────┘         │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                              │                                                       │
│                           ┌──────────────────┼──────────────────┐                                    │
│                           ▼                  ▼                  ▼                                    │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                              GOVERNANCE LAYER                                               │  │
│     │                                                                                             │  │
│     │      ┌──────────────┐       ┌──────────────┐       ┌──────────────┐                         │  │
│     │      │   Security   │       │  Transaction │       │    Policy    │                         │  │
│     │      │   Observer   │  ───► │   Firewall   │  ───► │  Evaluator   │                         │  │
│     │      │              │       │              │       │              │                         │  │
│     │      │  Block bad   │       │  Cap $250    │       │  Compliance  │                         │  │
│     │      │  inputs      │       │  Escalate    │       │  checks      │                         │  │
│     │      └──────────────┘       └──────────────┘       └──────────────┘                         │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                              │                                                       │
│                                              ▼                                                       │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                              ORCHESTRATION LAYER                                            │  │
│     │                                                                                             │  │
│     │      ┌──────────────┐       ┌──────────────┐       ┌──────────────┐                         │  │
│     │      │    Tier      │       │ Orchestrator │       │   Decision   │                         │  │
│     │      │   Router     │  ───► │   (RLM)      │  ───► │    Trace     │                         │  │
│     │      │              │       │              │       │              │                         │  │
│     │      │  T0/T1/T2    │       │  Agent       │       │  Bi-temporal │                         │  │
│     │      │  cost tiers  │       │  dispatch    │       │  audit log   │                         │  │
│     │      └──────────────┘       └──────────────┘       └──────────────┘                         │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- Customer journey maps directly to domain agents
- Governance layer is the differentiator - sits between user and AI
- Every request flows: Security → Rules → AI → Trace
- 12 agents total, each with specific business capability

---

## Slide 5: Business Outcomes Through Tiered Inference
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                HOW ARCHITECTURE DELIVERS BUSINESS VALUE                                    ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                         TIERED INFERENCE: THE COST ENGINE                                  │  │
│     │                                                                                             │  │
│     │                                                                                             │  │
│     │      REQUEST ──►  ┌───────────────────────────────────────────────────────────────┐        │  │
│     │                   │                                                               │        │  │
│     │                   │   T0: RULES ONLY        T1: SINGLE LLM       T2: MULTI-AGENT  │        │  │
│     │                   │                                                               │        │  │
│     │                   │   "Track order"         "Recommend for      "Analyze fraud    │        │  │
│     │                   │   "Return policy"        budget X"           patterns in      │        │  │
│     │                   │   "Store hours"         "Explain warranty"   customer Y"      │        │  │
│     │                   │                                                               │        │  │
│     │                   │   ┌─────────────┐       ┌─────────────┐     ┌─────────────┐   │        │  │
│     │                   │   │  0 tokens   │       │ ~500 tokens │     │ ~2000 tokens│   │        │  │
│     │                   │   │  <50ms      │       │ <500ms      │     │ <2000ms     │   │        │  │
│     │                   │   │  85 rules   │       │ bounded     │     │ 3 iterations│   │        │  │
│     │                   │   └─────────────┘       └─────────────┘     └─────────────┘   │        │  │
│     │                   │                                                               │        │  │
│     │                   │        ~70%                 ~20%                ~10%          │        │  │
│     │                   │     of traffic           of traffic          of traffic       │        │  │
│     │                   │                                                               │        │  │
│     │                   └───────────────────────────────────────────────────────────────┘        │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │      BUSINESS          ┌──────────────┐    ┌──────────────┐    ┌──────────────┐            │  │
│     │      OUTCOME  ────►    │   ~90%       │    │  <500ms      │    │  Per-User    │            │  │
│     │                        │ Cost Savings │    │  P95 Latency │    │ Token Budget │            │  │
│     │                        │              │    │              │    │              │            │  │
│     │                        │ vs API-only  │    │ vs 2-5s      │    │ Predictable  │            │  │
│     │                        │ approach     │    │ typical      │    │ OpEx         │            │  │
│     │                        └──────────────┘    └──────────────┘    └──────────────┘            │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  KEY INSIGHT: 70% of e-commerce queries are predictable. Don't burn tokens on "track my   ║   │
│     ║  order" - use rules. Reserve LLM for judgment calls.                                      ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- GLM 4.7-style thinking tiers adapted for e-commerce
- Rules-first is not "dumb" - it's cost engineering
- Token budget per user prevents runaway costs
- Competitive moat: Same quality at 10% of the cost

---

## Slide 6: Data Architecture & Compliance
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    DATA SOVEREIGNTY & BI-TEMPORAL AUDIT                                    ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │       PII ZONE                    CONTROL ZONE                  EXTERNAL                    │  │
│     │     (Data Stays)                 (Processing)                  (Offloaded)                  │  │
│     │                                                                                             │  │
│     │    ┌────────────┐              ┌────────────┐              ┌────────────┐                   │  │
│     │    │            │              │            │              │            │                   │  │
│     │    │ PostgreSQL │              │   Redis    │              │  Stripe    │                   │  │
│     │    │            │              │            │              │            │                   │  │
│     │    │ • Orders   │              │ • Session  │              │ • Cards    │                   │  │
│     │    │ • Customers│     ◄───     │ • Cache    │     ───►     │ • Tokens   │                   │  │
│     │    │ • Decision │    Query     │ • Semantic │    API       │ • PCI      │                   │  │
│     │    │   Trace    │              │   Search   │              │            │                   │  │
│     │    │            │              │            │              │            │                   │  │
│     │    └────────────┘              └────────────┘              └────────────┘                   │  │
│     │                                                                                             │  │
│     │    NO EGRESS                   EPHEMERAL                   VENDOR OWNED                     │  │
│     │    GDPR boundary               TTL-controlled              PCI boundary                     │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                          BI-TEMPORAL DECISION TRACE                                         │  │
│     │                                                                                             │  │
│     │      EVENT        ──►     TRANSACTION     ──►      VALID         ──►      QUERY            │  │
│     │     OCCURS                  TIME                   TIME                  ANYTIME            │  │
│     │                                                                                             │  │
│     │   "Customer        "When did            "When was this        "Show me what               │  │
│     │    refund           system record        decision              AI knew at                   │  │
│     │    requested"       this?"               effective?"           2pm yesterday"               │  │
│     │                                                                                             │  │
│     │                    ┌─────────────────────────────────────────────────────────┐              │  │
│     │                    │  WHY THIS MATTERS FOR COMPLIANCE                        │              │  │
│     │                    │                                                         │              │  │
│     │                    │  EU AI Act: "Right to explanation" requires knowing     │              │  │
│     │                    │  what information the AI had when it made a decision.   │              │  │
│     │                    │  Standard logs only capture "what" - bi-temporal        │              │  │
│     │                    │  captures "what the AI knew at decision time."          │              │  │
│     │                    └─────────────────────────────────────────────────────────┘              │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- Three data zones with clear boundaries
- PII never leaves PostgreSQL zone - GDPR/CCPA compliant
- Bi-temporal is the secret weapon for AI audits
- WORM (Write Once Read Many) logs for immutable audit trail

---

## Slide 7: Agent Architecture - Logical View
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                       12 AGENTS: SECURITY-FIRST DESIGN                                     ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │                           REQUEST FLOW (LEFT TO RIGHT)                                      │  │
│     │                                                                                             │  │
│     │                                                                                             │  │
│     │   USER ──►  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ──► RESP  │  │
│     │             │ Security │  │   Tier   │  │ Domain   │  │ Policy   │  │ Decision │            │  │
│     │             │ Observer │  │  Router  │  │  Agent   │  │Evaluator │  │  Trace   │            │  │
│     │             │          │  │          │  │          │  │          │  │          │            │  │
│     │             │ BLOCK or │  │ T0/T1/T2 │  │ Execute  │  │ Approve  │  │ Log      │            │  │
│     │             │ PASS     │  │ route    │  │ task     │  │ or deny  │  │ decision │            │  │
│     │             └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │  │
│     │                  │                           │                                              │  │
│     │                  │                           │                                              │  │
│     │             ┌────┴────┐              ┌───────┴───────┐                                      │  │
│     │             │ 8 PII   │              │ DOMAIN AGENTS │                                      │  │
│     │             │ types   │              │               │                                      │  │
│     │             │ 35+     │              │ • Inventory   │                                      │  │
│     │             │ jailbrk │              │ • Fraud       │                                      │  │
│     │             │ OWASP   │              │ • Recommend   │                                      │  │
│     │             │ LLM01-09│              │ • Complaints  │                                      │  │
│     │             └─────────┘              │ • CV Vision   │                                      │  │
│     │                                      └───────────────┘                                      │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌───────────────────────────────────────┐  ┌───────────────────────────────────────┐             │
│     │        SECURITY SHIFT-LEFT            │  │        HUMAN ESCALATION               │             │
│     │                                       │  │                                       │             │
│     │  Security Observer runs BEFORE        │  │  Automatic escalation when:           │             │
│     │  any agent processes the request.     │  │  • Transaction > $250                 │             │
│     │                                       │  │  • Confidence < 70%                   │             │
│     │  Unlike bolt-on security, threats     │  │  • Policy violation detected          │             │
│     │  are blocked at the gate, not         │  │  • Fraud score > threshold            │             │
│     │  detected after damage is done.       │  │                                       │             │
│     └───────────────────────────────────────┘  └───────────────────────────────────────┘             │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- Security Observer is read-only - scans but never modifies
- "Shift-left" means security happens early in the pipeline
- Domain agents are swappable - modular architecture
- Human escalation is a feature, not a failure mode

---

## Slide 8: Logical to Physical Mapping
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    LOGICAL → PHYSICAL: DEPLOYMENT STRATEGY                                 ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌────────────────────────────────────────────────────────────────────────────────────────────┐   │
│     │                                                                                            │   │
│     │   LOGICAL MODULE         PHYSICAL TYPE           DEPLOYMENT           RATIONALE           │   │
│     │                                                                                            │   │
│     │   ┌──────────────┐      ┌──────────────┐       ┌────────────┐                              │   │
│     │   │ Agent        │      │   Custom     │       │   COLO /   │     IP protection           │   │
│     │   │ Orchestrator │ ───► │ Microservice │  ───► │  Private   │     Audit control           │   │
│     │   └──────────────┘      └──────────────┘       └────────────┘                              │   │
│     │                                                                                            │   │
│     │   ┌──────────────┐      ┌──────────────┐       ┌────────────┐                              │   │
│     │   │ Decision     │      │   Managed    │       │   COLO     │     Data sovereignty        │   │
│     │   │ Store        │ ───► │  PostgreSQL  │  ───► │  PII Zone  │     GDPR boundary           │   │
│     │   └──────────────┘      └──────────────┘       └────────────┘                              │   │
│     │                                                                                            │   │
│     │   ┌──────────────┐      ┌──────────────┐       ┌────────────┐                              │   │
│     │   │ LLM          │      │   Ollama     │       │   GPU Node │     Cost control            │   │
│     │   │ Inference    │ ───► │  (Self-host) │  ───► │  Optional  │     Data never leaves       │   │
│     │   └──────────────┘      └──────────────┘       └────────────┘                              │   │
│     │                                                                                            │   │
│     │   ┌──────────────┐      ┌──────────────┐       ┌────────────┐                              │   │
│     │   │ Storefront   │      │   React SPA  │       │   CLOUD    │     Global CDN              │   │
│     │   │ UI           │ ───► │    + CDN     │  ───► │  Edge      │     Elastic scale           │   │
│     │   └──────────────┘      └──────────────┘       └────────────┘                              │   │
│     │                                                                                            │   │
│     │   ┌──────────────┐      ┌──────────────┐       ┌────────────┐                              │   │
│     │   │ Payments     │      │    SaaS      │       │  EXTERNAL  │     PCI offloaded           │   │
│     │   │              │ ───► │   (Stripe)   │  ───► │  Vendor    │     Liability transfer      │   │
│     │   └──────────────┘      └──────────────┘       └────────────┘                              │   │
│     │                                                                                            │   │
│     └────────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                      │
│     ┌────────────────────────────────────────────────────────────────────────────────────────────┐   │
│     │                                                                                            │   │
│     │   ┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐            │   │
│     │   │      COLO       │ ◄─────── │ Private Link    │ ───────► │     CLOUD       │            │   │
│     │   │   (70% traffic) │  <10ms   │ (Secure tunnel) │          │  (30% traffic)  │            │   │
│     │   │                 │          │                 │          │                 │            │   │
│     │   │ Agents + Data   │          │ No public       │          │ CDN + Gateway   │            │   │
│     │   │ GPU + Secrets   │          │ internet        │          │ AutoScale       │            │   │
│     │   └─────────────────┘          └─────────────────┘          └─────────────────┘            │   │
│     │                                                                                            │   │
│     └────────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- COLO = Colocation (on-prem or dedicated) for sensitive workloads
- CLOUD = Public cloud for elastic, internet-facing components
- Private Link ensures secure connection without internet exposure
- Docker-native MVP maps cleanly to K8s/COLO production

---

## Slide 9: Security & Governance Architecture
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    6-LAYER DEFENSE: AGENTIC AI SECURITY                                    ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │   LAYER 1          LAYER 2          LAYER 3          LAYER 4          LAYER 5          L6  │  │
│     │   Perimeter        App Security     AI Security      Access           Transaction      Audit│  │
│     │                                                                                             │  │
│     │  ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌───┐│  │
│     │  │         │      │         │      │         │      │         │      │         │      │   ││  │
│     │  │  TLS    │ ───► │  Rate   │ ───► │Security │ ───► │  RBAC   │ ───► │ Policy  │ ───► │BI-││  │
│     │  │  1.3    │      │  Limit  │      │Observer │      │  ABAC   │      │  Gate   │      │TMP││  │
│     │  │  WAF    │      │  CORS   │      │         │      │  JWT    │      │         │      │   ││  │
│     │  │  HMAC   │      │  CSRF   │      │ PII     │      │         │      │ $250    │      │TRC││  │
│     │  │         │      │         │      │ Jailbrk │      │         │      │ Cap     │      │   ││  │
│     │  └─────────┘      └─────────┘      └─────────┘      └─────────┘      └─────────┘      └───┘│  │
│     │                                                                                             │  │
│     │  EXTERNAL          STANDARD         AGENTIC-         IDENTITY         BUSINESS        AUDIT│  │
│     │  THREATS           WEB SECURITY     SPECIFIC         BOUNDARIES       RULES           TRAIL│  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌───────────────────────────────────────┐  ┌───────────────────────────────────────┐             │
│     │      OWASP LLM TOP 10 COVERAGE        │  │      COMPLIANCE FRAMEWORKS            │             │
│     │                                       │  │                                       │             │
│     │  LLM01 Prompt Injection    ✓ Layer 3  │  │  EU AI Act                            │             │
│     │  LLM02 Insecure Output     ✓ Layer 5  │  │  • Article 14: Human oversight  ✓     │             │
│     │  LLM03 Training Poison     ✓ Self-host│  │  • Article 13: Transparency     ✓     │             │
│     │  LLM04 Model DoS           ✓ Budget   │  │                                       │             │
│     │  LLM05 Supply Chain        ✓ Ollama   │  │  ISO 42001 (AI Management)            │             │
│     │  LLM06 Sensitive Info      ✓ Layer 3  │  │  • Decision audit trail         ✓     │             │
│     │  LLM07 Insecure Plugin     ✓ Firewall │  │  • Risk assessment              ✓     │             │
│     │  LLM08 Excessive Agency    ✓ Layer 5  │  │                                       │             │
│     │  LLM09 Overreliance        ✓ Escalate │  │  NIST AI RMF                          │             │
│     │                                       │  │  • Govern, Map, Measure, Manage  ✓    │             │
│     └───────────────────────────────────────┘  └───────────────────────────────────────┘             │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- Layer 3 (AI Security) is what's missing from most platforms
- OWASP LLM Top 10 is the new checklist for AI systems
- Bi-temporal trace = Layer 6 = the compliance differentiator
- Self-hosted LLM (Ollama) addresses supply chain concerns

---

## Slide 10: Vision & Strategic Roadmap
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│      ███████╗██╗  ██╗ ██████╗ ██████╗ ███████╗ ██████╗ ██╗   ██╗██╗██████╗ ███████╗                  │
│      ██╔════╝██║  ██║██╔═══██╗██╔══██╗██╔════╝██╔═══██╗██║   ██║██║██╔══██╗██╔════╝                  │
│      ███████╗███████║██║   ██║██████╔╝███████╗██║   ██║██║   ██║██║██████╔╝█████╗                    │
│      ╚════██║██╔══██║██║   ██║██╔═══╝ ╚════██║██║▄▄ ██║██║   ██║██║██╔══██╗██╔══╝                    │
│      ███████║██║  ██║╚██████╔╝██║     ███████║╚██████╔╝╚██████╔╝██║██║  ██║███████╗                  │
│      ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚══════╝ ╚══▀▀═╝  ╚═════╝ ╚═╝╚═╝  ╚═╝╚══════╝                  │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    MODULAR · COMPLIANT · COST-OPTIMIZED                                    ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │      DELIVERED                    NEXT QUARTER                   FUTURE VISION             │  │
│     │                                                                                             │  │
│     │   ┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐            │  │
│     │   │                 │          │                 │          │                 │            │  │
│     │   │ 12 Custom       │          │ CV Agent        │          │ Multi-Tenant    │            │  │
│     │   │ Agents          │    ──►   │ 5-Tier Vision   │    ──►   │ SaaS Platform   │            │  │
│     │   │                 │          │                 │          │                 │            │  │
│     │   │ 85+ Pre-LLM     │          │ RAGAS           │          │ Agent           │            │  │
│     │   │ Rules           │          │ Evaluation      │          │ Marketplace     │            │  │
│     │   │                 │          │                 │          │                 │            │  │
│     │   │ Bi-Temporal     │          │ Neo4j           │          │ Compliance      │            │  │
│     │   │ Decision Trace  │          │ Context Graph   │          │ Certification   │            │  │
│     │   │                 │          │                 │          │                 │            │  │
│     │   │ ~90% Cost       │          │ Real-Time       │          │ Vertical        │            │  │
│     │   │ Savings         │          │ WebSocket       │          │ Expansions      │            │  │
│     │   │                 │          │                 │          │                 │            │  │
│     │   └─────────────────┘          └─────────────────┘          └─────────────────┘            │  │
│     │                                                                                             │  │
│     │        MVP READY                   ENTERPRISE                   PLATFORM                   │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │      ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐          │  │
│     │      │AUTONOMOUS│    │EXPLAINABLE│   │ COMPLIANT│    │  COST-   │    │ MODULAR  │          │  │
│     │      │   80%    │    │  100%    │    │ EU AI Act│    │OPTIMIZED │    │  AGENT   │          │  │
│     │      │ No Human │    │ Decisions│    │ISO 42001 │    │   90%    │    │   SWAP   │          │  │
│     │      └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘          │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  ARCHITECTURE DEMONSTRATES: Enterprise AI governance is achievable with custom agents.     ║   │
│     ║  The build/buy framework and security-first design are transferable to any AI platform.   ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker Notes:**
- 3-week solo delivery demonstrates architectural velocity
- Key transferable patterns: Tiered inference, bi-temporal audit, security shift-left
- Platform vision: From e-commerce to any domain requiring governed AI
- Call to action: Custom agents aren't just possible - they're necessary for compliance

---

## Appendix A: Build vs Buy Quick Reference

| Component | Decision | Rationale |
|-----------|----------|-----------|
| Agent Orchestrator | **BUILD** | Core IP, audit control, compliance ownership |
| Security Observer | **BUILD** | Must inspect before external vendors see data |
| Transaction Firewall | **BUILD** | Business rules, escalation logic |
| Bi-Temporal Trace | **BUILD** | Compliance differentiator, EU AI Act readiness |
| Payment Processing | **BUY** | PCI DSS liability, commodity function |
| Shipping Labels | **BUY** | Carrier integration complexity, low differentiation |
| Database (PostgreSQL) | **MANAGE** | Use managed service, don't self-host infra |
| LLM Inference | **HYBRID** | Ollama for sensitive data, API for scale |
| CDN / Static Hosting | **BUY** | Commodity, global scale |
| Observability | **MANAGE** | Prometheus/Grafana self-hosted for cost |

---

## Appendix B: TOGAF ADM Alignment

| Phase | Coverage | ShopSquire Elements |
|-------|----------|---------------------|
| **A: Vision** | 20% | Slides 1-2: Business problem, compliance gap |
| **B: Business** | 30% | Slides 3-5: Capability map, outcomes, build/buy |
| **C: Information Systems** | 25% | Slides 6-7: Data architecture, agent ecosystem |
| **D: Technology** | 25% | Slides 8-9: Physical mapping, security layers |

---

## Appendix C: Proof Points for "Solo Architect, 3 Weeks"

| Evidence | What It Demonstrates |
|----------|---------------------|
| Git commit history | Timestamps prove development timeline |
| Architectural consistency | Coherent patterns across 12 agents (not copy-paste) |
| Honest gaps documented | CV at 60%, Neo4j deferred - shows real judgment |
| Trade-off rationale | "Why PostgreSQL JSONB vs Neo4j for MVP" - only builder knows |
| Novel patterns applied | GLM 4.7 thinking tiers adapted to e-commerce - not tutorial code |
| Working code + UI | Not slideware - functional Decision Trace UI |

---

*Document Version: 2.0 Executive Deck*
*TOGAF ADM Phases: A (Vision), B (Business), C (Info Systems), D (Technology)*
