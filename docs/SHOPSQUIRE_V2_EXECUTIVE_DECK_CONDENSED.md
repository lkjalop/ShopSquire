# ShopSquire v2.0 Executive Architecture Deck

> **Purpose**: Business-focused architecture for C-Suite and AI Architects
> **Format**: 16:9 wide, left-to-right flow, visual ASCII art
> **Theme**: How technology solves business outcomes

---

## Slide 1: Title & Value Proposition
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
│     ║            GOVERNABLE AGENTIC AI FOR RETAIL AUTOMATION                                     ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐                    │
│     │   80% TASKS     │    ──►   │   EVERY AI      │    ──►   │   COMPLIANT     │                    │
│     │   AUTOMATED     │          │   DECISION      │          │   BY DESIGN     │                    │
│     │                 │          │   AUDITABLE     │          │                 │                    │
│     │  Rules + Agents │          │  Bi-Temporal    │          │  EU AI Act      │                    │
│     │  reduce human   │          │  Trace answers  │          │  ISO 42001      │                    │
│     │  intervention   │          │  "why did AI    │          │  NIST AI RMF    │                    │
│     │                 │          │  decide this?"  │          │                 │                    │
│     └─────────────────┘          └─────────────────┘          └─────────────────┘                    │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  "Agents handle routine. Humans govern strategy. Every decision is audit-ready."           ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│      12 CUSTOM AGENTS    │    85+ PRE-LLM RULES    │    BI-TEMPORAL TRACE    │   ~90% COST SAVINGS  │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: Governable AI that's audit-ready from day one.

---

## Slide 2: Why Custom Agents + Build vs Buy Matrix
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║           WHY CUSTOM AGENTS? COMPLIANCE DRIVES THE DECISION                                ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │  NEW COMPLIANCE REQUIREMENTS (2024-2026)                                                    │  │
│     │                                                                                             │  │
│     │   ISO 42001 (AI Management)    EU AI Act (Article 14)    NIST AI RMF                       │  │
│     │   • Governable agents          • Human oversight         • Govern, Map, Measure            │  │
│     │   • Decision audit trail       • Right to explanation    • Risk-based approach             │  │
│     │   • Evidence preservation      • Transparency logs       • Continuous monitoring           │  │
│     │                                                                                             │  │
│     │   ═══════════════════════════════════════════════════════════════════════════════════════  │  │
│     │   PROBLEM: SaaS vendors (Salesforce AgentForce, etc.) can't provide audit depth            │  │
│     │            needed for compliance. They control the black box.                              │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌───────────────────────────────────────┐  ┌───────────────────────────────────────┐             │
│     │         BUY (Commodity SaaS)          │  │         BUILD (Custom Agents)         │             │
│     │                                       │  │                                       │             │
│     │  Stripe · PayPal · Afterpay           │  │  Agent Orchestrator                   │             │
│     │  └─► PCI offloaded                    │  │  └─► Decision routing + audit         │             │
│     │                                       │  │                                       │             │
│     │  ShipStation · Carriers               │  │  Security Observer                    │             │
│     │  └─► Label generation                 │  │  └─► Threat detection (OWASP/MITRE)   │             │
│     │                                       │  │                                       │             │
│     │  CDN · Vercel                         │  │  Transaction Firewall                 │             │
│     │  └─► Global delivery                  │  │  └─► Policy gates + escalation        │             │
│     │                                       │  │                                       │             │
│     │  ─────────────────────────────────    │  │  Bi-Temporal Decision Trace           │             │
│     │  WHY BUY: No differentiation          │  │  └─► EU AI Act compliance             │             │
│     │           Vendor handles liability    │  │                                       │             │
│     │           Fast integration            │  │  ─────────────────────────────────    │             │
│     │                                       │  │  WHY BUILD: Compliance ownership      │             │
│     │                                       │  │             Apply latest research     │             │
│     │                                       │  │             Speed to compliance       │             │
│     └───────────────────────────────────────┘  └───────────────────────────────────────┘             │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  EVALUATION CRITERIA: Build when compliance, audit trail, or competitive moat required.    ║   │
│     ║  Buy when commodity function with vendor liability transfer (payments, shipping).         ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: Build governance layer, buy commodity functions.

---

## Slide 3: Architecture Pattern - Tiered Inference
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║        TIERED INFERENCE: COST CONTROL MEETS QUALITY                                        ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │   REQUEST ──►┌────────────┐──►┌────────────┐──►┌────────────────────────┐──► RESPONSE      │  │
│     │              │TIER ROUTER │   │  EXECUTE   │   │     DECISION TRACE     │                  │  │
│     │              └────────────┘   └────────────┘   └────────────────────────┘                  │  │
│     │                    │                                                                       │  │
│     │     ┌──────────────┼──────────────┬──────────────────────┐                                 │  │
│     │     ▼              ▼              ▼                      │                                 │  │
│     │  ┌──────┐     ┌──────────┐   ┌────────────────┐          │                                 │  │
│     │  │  T0  │     │    T1    │   │       T2       │          │                                 │  │
│     │  │RULES │     │SINGLE LLM│   │  INTERLEAVED   │          │                                 │  │
│     │  │ONLY  │     │   PASS   │   │    THINKING    │          │                                 │  │
│     │  └──────┘     └──────────┘   └────────────────┘          │                                 │  │
│     │                                                          │                                 │  │
│     │  "Track order"  "Recommend    "Analyze fraud             │                                 │  │
│     │  "Return policy" product"     patterns"                  │                                 │  │
│     │  "Store hours"  "Explain      "Compare options"          │                                 │  │
│     │                  warranty"                               │                                 │  │
│     │                                                          │                                 │  │
│     │  ┌─────────┐   ┌─────────┐   ┌─────────────┐             │                                 │  │
│     │  │0 tokens │   │~500 tok │   │~2000 tokens │             │                                 │  │
│     │  │<50ms    │   │<500ms   │   │<2000ms      │             │                                 │  │
│     │  │85 rules │   │bounded  │   │4 tool calls │             │                                 │  │
│     │  └─────────┘   └─────────┘   └─────────────┘             │                                 │  │
│     │                                                          │                                 │  │
│     │     ~70%           ~20%           ~10%                   │                                 │  │
│     │   of traffic     of traffic     of traffic               │  Applied Research:             │  │
│     │                                                          │  • GLM 4.7 Interleaved Thinking│  │
│     │  ══════════════════════════════════════════════          │  • Confidence Calibration      │  │
│     │  RESULT: ~90% cost savings vs API-only approach          │  • Bounded Tool Loops          │  │
│     │          <500ms P95 latency                              │                                 │  │
│     │          Predictable GPU/token spend                     │                                 │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  WHY: 70% of queries are predictable. Don't burn tokens on "track my order."              ║   │
│     ║  Reserve LLM for judgment calls. Gate GPU/API spend from the start.                       ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: Pragmatic cost engineering - rules first, LLM when needed.

---

## Slide 4: Logical → Physical Architecture Flow
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    LOGICAL → PHYSICAL: END-TO-END FLOW                                     ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     CUSTOMER                    GOVERNANCE                         EXECUTION                         │
│     REQUEST                     LAYER                              LAYER                             │
│         │                           │                                  │                             │
│         ▼                           ▼                                  ▼                             │
│     ┌───────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌─────────┐    │
│     │       │    │  SECURITY │    │   TIER    │    │  DOMAIN   │    │  POLICY   │    │DECISION │    │
│     │  CDN  │───►│  OBSERVER │───►│  ROUTER   │───►│  AGENTS   │───►│   GATE    │───►│  TRACE  │    │
│     │       │    │           │    │           │    │           │    │           │    │         │    │
│     │ CLOUD │    │  Scan +   │    │ T0/T1/T2  │    │ Execute   │    │ Approve   │    │ Audit   │    │
│     │       │    │  Block    │    │ Route     │    │ Task      │    │ or Deny   │    │ Log     │    │
│     └───────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘    └─────────┘    │
│         │              │                                │                │               │          │
│         │              │                                │                │               │          │
│     ════════════════════════════════════════════════════════════════════════════════════════════    │
│         │              │                                │                │               │          │
│         ▼              ▼                                ▼                ▼               ▼          │
│     ┌───────────────────────────────────────────────────────────────────────────────────────────┐   │
│     │                              PHYSICAL DEPLOYMENT                                          │   │
│     │                                                                                           │   │
│     │  ┌────────────┐        ┌─────────────────────────────────────────────┐        ┌────────┐  │   │
│     │  │            │        │                    COLO                     │        │EXTERNAL│  │   │
│     │  │   CLOUD    │◄──────►│              (70% traffic)                  │◄──────►│  SaaS  │  │   │
│     │  │            │ Private│                                             │  API   │        │  │   │
│     │  │ Storefront │  Link  │  ┌─────────┐  ┌─────────┐  ┌─────────┐     │        │ Stripe │  │   │
│     │  │ Gateway    │ <10ms  │  │CONTROL  │  │  DATA   │  │   GPU   │     │        │ PayPal │  │   │
│     │  │ CDN        │        │  │ PLANE   │  │  PLANE  │  │  NODE   │     │        │Afterpay│  │   │
│     │  │            │        │  │         │  │         │  │         │     │        │        │  │   │
│     │  │ 30%        │        │  │Orchestr │  │PostgreSQL│ │ Ollama  │     │        │  PCI   │  │   │
│     │  │ traffic    │        │  │Redis    │  │Timescale│  │ llama3  │     │        │Offload │  │   │
│     │  │            │        │  │Qdrant   │  │Neo4j    │  │ llava   │     │        │        │  │   │
│     │  └────────────┘        │  └─────────┘  └─────────┘  └─────────┘     │        └────────┘  │   │
│     │                        │          PII NEVER LEAVES COLO             │                    │   │
│     │                        └─────────────────────────────────────────────┘                    │   │
│     └───────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  DATA SOVEREIGNTY: PII in COLO (GDPR). Aggregates to CLOUD (redacted). PCI to vendor.     ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: Clear data boundaries - PII stays, PCI offloaded.

**[SCREENSHOT OPPORTUNITY: Network topology from admin dashboard]**

---

## Slide 5: Security Architecture (OWASP + MITRE)
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    SECURITY: SHIFT-LEFT FOR AGENTIC AI                                     ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │   REQUEST ──► LAYER 1-2 ──► LAYER 3 ──► LAYER 4-5 ──► LAYER 6 ──► RESPONSE                │  │
│     │               Perimeter     AI Security   Access       Audit                               │  │
│     │               + App         Observer      + Firewall   Evidence                            │  │
│     │                                                                                             │  │
│     │   ┌─────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                        │  │
│     │   │TLS 1.3  │  │ PII (8 types)│  │ JWT + RBAC   │  │ Bi-Temporal  │                        │  │
│     │   │WAF      │  │ Jailbreak    │  │ $250 cap     │  │ WORM logs    │                        │  │
│     │   │Rate Lim │  │ Prompt Inject│  │ Escalation   │  │ 5-year retain│                        │  │
│     │   │HMAC     │  │ 25+ patterns │  │ Idempotency  │  │              │                        │  │
│     │   └─────────┘  └──────────────┘  └──────────────┘  └──────────────┘                        │  │
│     │                                                                                             │  │
│     │   STANDARD       AGENTIC-         BUSINESS          COMPLIANCE                             │  │
│     │   WEB SEC        SPECIFIC         RULES             AUDIT                                  │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌───────────────────────────────────────┐  ┌───────────────────────────────────────┐             │
│     │     THREAT FRAMEWORK COVERAGE         │  │     CV FRAUD + INVENTORY SECURITY     │             │
│     │                                       │  │                                       │             │
│     │  OWASP LLM Top 10         ✓ 9/10     │  │  Image forensics:                     │             │
│     │  OWASP Agentic Top 10     ✓ 10/10    │  │  • pHash duplicate detection          │             │
│     │  OWASP API Top 10         ✓ 9/10     │  │  • Serial number OCR                  │             │
│     │  MITRE ATLAS              ✓ Mapped    │  │  • EXIF metadata analysis             │             │
│     │  STRIDE                   ✓ Covered   │  │  • DREAD risk scoring                 │             │
│     │  DREAD                    ✓ Scoring   │  │                                       │             │
│     │                                       │  │  Verdict: APPROVE / FLAG / REJECT    │             │
│     │  Security Observer: read-only scan   │  │  with confidence + evidence hash      │             │
│     │  runs BEFORE any agent processes     │  │                                       │             │
│     └───────────────────────────────────────┘  └───────────────────────────────────────┘             │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  SHIFT-LEFT: Block threats at the gate, not after damage. Security before AI processing.  ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: Multi-framework security coverage for agentic AI.

**[SCREENSHOT OPPORTUNITY: Security Observer UI with MITRE/OWASP tagging]**

---

## Slide 6: Agent Ecosystem & Graceful Escalation
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    12 AGENTS: DETERMINISTIC ESCALATION PATH                                ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │  ORCHESTRATOR (Central Router)                                                              │  │
│     │       │                                                                                     │  │
│     │       ├──► SECURITY OBSERVER ──► Scan first, block bad inputs (99% no LLM needed)          │  │
│     │       │                                                                                     │  │
│     │       ├──► DOMAIN AGENTS                                                                    │  │
│     │       │    ├── Recommendation    DB filters → Rank → llama3:8b if needed                   │  │
│     │       │    ├── Inventory         Stock check → Supplier query → bulk availability          │  │
│     │       │    ├── Fraud Scorer      pHash + OCR → llava:13b (CV fraud detection)              │  │
│     │       │    ├── CV Agent          Image forensics → DREAD scoring → verdict                 │  │
│     │       │    └── Complaints        Intent classify → escalate or resolve                     │  │
│     │       │                                                                                     │  │
│     │       ├──► POLICY GATE ──► Compliance check (rules + LLM if ambiguous)                     │  │
│     │       │                                                                                     │  │
│     │       └──► TRANSACTION FIREWALL ──► >$250 or low confidence → HUMAN APPROVAL               │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌───────────────────────────────────────────────────────────────────────────────────────────┐    │
│     │  GRACEFUL ESCALATION: T0 → T1 → T2 → HUMAN                                                │    │
│     │                                                                                           │    │
│     │  Agent Error    ──► Retry (3x) ──► Rules Fallback ──► Human Escalate                     │    │
│     │  LLM Timeout    ──► Circuit Breaker ──► Rules-Only Mode                                   │    │
│     │  Low Confidence ──► Corrective RAG (broaden + verify)                                     │    │
│     │  Prompt Inject  ──► Block + Alert Security Observer                                       │    │
│     │                                                                                           │    │
│     │  ══════════════════════════════════════════════════════════════════════════════════════   │    │
│     │  BUSINESS QUERY: "Do you have 500 units of laptop model X for bulk purchase?"            │    │
│     │  FLOW: Orchestrator → Inventory Agent → Supplier Agent → Stock Check → Price Quote       │    │
│     │        → Transaction Firewall (bulk = human approval) → Decision Trace                   │    │
│     └───────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  PATTERN: Orchestrated Multi-Agent with Tiered Inference (not swarm, not flat RAG).       ║   │
│     ║  All agent-to-agent calls go through Orchestrator. No direct agent communication.         ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: Deterministic escalation prevents AI overreach.

**[SCREENSHOT OPPORTUNITY: Recommendation flow or inventory agent bulk query]**

---

## Slide 7: Decision Trace & Compliance
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    BI-TEMPORAL TRACE: THE COMPLIANCE DIFFERENTIATOR                        ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │  STANDARD AUDIT LOG              vs        BI-TEMPORAL DECISION TRACE                       │  │
│     │                                                                                             │  │
│     │  "What happened"                           "What AI knew when it decided"                   │  │
│     │  └─► timestamp + action                    └─► transaction_time + valid_time               │  │
│     │                                                                                             │  │
│     │  ─────────────────────────────────────────────────────────────────────────────────────────  │  │
│     │                                                                                             │  │
│     │  EU AI Act Article 14: "Right to explanation"                                              │  │
│     │  QUESTION: Why did the AI approve this refund at 2pm yesterday?                            │  │
│     │                                                                                             │  │
│     │  ┌────────────────┐    ┌────────────────┐    ┌────────────────┐    ┌────────────────┐      │  │
│     │  │    EVENT       │───►│  TRANSACTION   │───►│    VALID       │───►│    QUERY       │      │  │
│     │  │   OCCURS       │    │     TIME       │    │     TIME       │    │   ANYTIME      │      │  │
│     │  │                │    │                │    │                │    │                │      │  │
│     │  │ "Refund        │    │ "When did      │    │ "When was      │    │ "Show what     │      │  │
│     │  │  requested"    │    │  system record │    │  this decision │    │  AI knew at    │      │  │
│     │  │                │    │  this?"        │    │  effective?"   │    │  2pm"          │      │  │
│     │  └────────────────┘    └────────────────┘    └────────────────┘    └────────────────┘      │  │
│     │                                                                                             │  │
│     │  ANSWER: At 2pm, the AI had: order history (30 days), customer tier (Gold),               │  │
│     │          policy v2.3 (refunds <$100 auto-approve), confidence 0.92 (above threshold)      │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌───────────────────────────────────────┐  ┌───────────────────────────────────────┐             │
│     │     TRACE EVENTS CAPTURED             │  │     COMPLIANCE FRAMEWORKS             │             │
│     │                                       │  │                                       │             │
│     │  • security_scan (threats detected)   │  │  EU AI Act                            │             │
│     │  • tier_decision (T0/T1/T2 chosen)    │  │  ✓ Article 14 Human oversight         │             │
│     │  • tool_result (each tool call)       │  │  ✓ Article 13 Transparency            │             │
│     │  • inventory_check (stock status)     │  │                                       │             │
│     │  • cv_analysis (image verdict)        │  │  ISO 42001 AI Management              │             │
│     │  • fraud_score (risk assessment)      │  │  ✓ Decision audit trail               │             │
│     │  • policy_verdict (approve/deny)      │  │  ✓ Evidence preservation              │             │
│     │  • human_escalation (if triggered)    │  │                                       │             │
│     │                                       │  │  NIST AI RMF                          │             │
│     │  WORM logs: immutable, 5-year retain  │  │  ✓ Govern, Map, Measure, Manage       │             │
│     └───────────────────────────────────────┘  └───────────────────────────────────────┘             │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: Bi-temporal trace answers "what did AI know when it decided?"

**[SCREENSHOT OPPORTUNITY: Decision Trace Timeline UI showing bi-temporal query]**

---

## Slide 8: Applied Research & Model Strategy
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║                    APPLIED RESEARCH: WHY THESE TECHNOLOGY CHOICES                          ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │  RESEARCH APPLIED                 IMPLEMENTATION                    BUSINESS VALUE          │  │
│     │                                                                                             │  │
│     │  GLM 4.7 Interleaved Thinking     InterleavingController            Mitigates context rot  │  │
│     │  └─► Think→Tool→Observe loops     └─► Bounded iterations (max 4)    + controls token spend │  │
│     │                                                                                             │  │
│     │  Confidence Calibration           Platt scaling + Isotonic          Reduces false positives│  │
│     │  └─► Raw confidence unreliable    └─► calibrate_confidence()        + enables escalation   │  │
│     │                                                                                             │  │
│     │  Kimi K2 Parallel Agent RL        Tier Router parallel evaluation   Faster T2 decisions    │  │
│     │  └─► Multiple reasoning paths     └─► Best-of-N with budget cap     + quality improvement  │  │
│     │                                                                                             │  │
│     │  Self-Hosted LLM (Ollama)         llama3:8b, mixtral, llava         Data sovereignty       │  │
│     │  └─► No data leaves boundary      └─► GPU node in COLO              + supply chain control │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │  MODEL SELECTION STRATEGY (Tiered by Cost + Capability)                                    │  │
│     │                                                                                             │  │
│     │   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐            │  │
│     │   │   TIER 0      │   │   TIER 1      │   │   TIER 2      │   │  ESCALATION   │            │  │
│     │   │   RULES       │   │  llama3:8b    │   │ mixtral:8x7b  │   │    HUMAN      │            │  │
│     │   │               │   │               │   │               │   │               │            │  │
│     │   │ 0 tokens      │   │ ~500 tokens   │   │ ~2000 tokens  │   │ N/A           │            │  │
│     │   │ <50ms         │   │ <500ms        │   │ <2000ms       │   │ Async queue   │            │  │
│     │   │               │   │               │   │               │   │               │            │  │
│     │   │ Deterministic │   │ Single-pass   │   │ Interleaved   │   │ Full context  │            │  │
│     │   │ 70% traffic   │   │ 20% traffic   │   │ 10% traffic   │   │ <5% traffic   │            │  │
│     │   └───────────────┘   └───────────────┘   └───────────────┘   └───────────────┘            │  │
│     │                                                                                             │  │
│     │   CV Agent: llava:13b (image forensics, pHash, EXIF, serial OCR)                           │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  WHY PRAGMATIC: Hard-gate GPU/API spend from day one. Graceful fallback at every tier.    ║   │
│     ║  Deterministic > probabilistic for compliance. Reserve AI power for judgment calls.       ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: Research-informed, cost-controlled model selection.

**[SCREENSHOT OPPORTUNITY: Grafana dashboard showing model tier distribution]**

---

## Slide 9: Summary & Call to Action
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
│     ║                    GOVERNABLE · AUDITABLE · COST-OPTIMIZED                                 ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │      DELIVERED                           ARCHITECTURE DEMONSTRATES                         │  │
│     │                                                                                             │  │
│     │   ┌─────────────────┐                 ┌─────────────────────────────────────────────────┐  │  │
│     │   │                 │                 │                                                 │  │  │
│     │   │ 12 Custom       │                 │  Custom agents are NECESSARY for compliance    │  │  │
│     │   │ Agents          │                 │  not just possible.                            │  │  │
│     │   │                 │                 │                                                 │  │  │
│     │   │ 85+ Pre-LLM     │                 │  Tiered inference controls cost from day one.  │  │  │
│     │   │ Rules           │                 │                                                 │  │  │
│     │   │                 │                 │  Bi-temporal trace is the compliance moat.     │  │  │
│     │   │ Bi-Temporal     │                 │                                                 │  │  │
│     │   │ Decision Trace  │                 │  Security shift-left is non-negotiable.        │  │  │
│     │   │                 │                 │                                                 │  │  │
│     │   │ ~90% Cost       │                 │  Build governance + trace. Buy commodity.      │  │  │
│     │   │ Reduction       │                 │                                                 │  │  │
│     │   │                 │                 │  Applied research (GLM, Kimi K2) is practical. │  │  │
│     │   │ Production-     │                 │                                                 │  │  │
│     │   │ Ready Platform  │                 │                                                 │  │  │
│     │   └─────────────────┘                 └─────────────────────────────────────────────────┘  │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ┌─────────────────────────────────────────────────────────────────────────────────────────────┐  │
│     │                                                                                             │  │
│     │      ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐          │  │
│     │      │AUTONOMOUS│    │AUDITABLE │    │ COMPLIANT│    │  COST-   │    │ MODULAR  │          │  │
│     │      │   80%    │    │  100%    │    │ EU AI Act│    │OPTIMIZED │    │  AGENT   │          │  │
│     │      │ No Human │    │ Decisions│    │ISO 42001 │    │   90%    │    │   SWAP   │          │  │
│     │      └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘          │  │
│     │                                                                                             │  │
│     └─────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  THIS IS NOT SLIDEWARE: Working platform with decision trace, security observer, agents.  ║   │
│     ║  Patterns are transferable to any domain requiring governable AI automation.              ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key Message**: This architecture is replicable and compliance-ready.

---

## Appendix A: Screenshot Placement Guide

| Slide | Screenshot | What to Capture |
|-------|------------|-----------------|
| 4 | Network topology | Admin dashboard showing COLO/CLOUD split |
| 5 | Security Observer | Threat detection UI with MITRE/OWASP tags |
| 6 | Agent flow | Recommendation or inventory bulk query |
| 7 | Decision Trace | Bi-temporal timeline modal |
| 8 | Model metrics | Grafana dashboard: tier distribution |

---

## Appendix B: Architecture Classification

| Question | Answer | Evidence |
|----------|--------|----------|
| **Framework** | Orchestrated Multi-Agent | `Orchestrator` class routes all requests |
| **Pattern** | Tiered Inference (T0/T1/T2) | `TierRouter` with `TOOL_BUDGETS = {0:0, 1:1, 2:4}` |
| **Thinking Style** | GLM-style Interleaving | `InterleavingController` with bounded loops |
| **NOT** | Agent Swarm | Too orchestrated, no self-organization |
| **NOT** | Flat Multi-Agent RAG | RAG is one component (T1), not architecture |

---

## Appendix C: Compliance Mapping

| Requirement | Implementation | Evidence |
|-------------|----------------|----------|
| ISO 42001 Decision Audit | Bi-temporal trace | `decision_log.py` |
| EU AI Act Article 14 | Human escalation gates | `firewall.py` $250 cap |
| NIST AI RMF Govern | Policy gate + observer | `observer.py`, `policy_gate.py` |
| OWASP Agentic Top 10 | Security Observer | 25+ threat signals mapped |

---

*Document Version: 2.0 Executive Deck (Condensed)*
*9 Slides + 3 Appendices*
