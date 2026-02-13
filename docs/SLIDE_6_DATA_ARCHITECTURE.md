# Slide 6: Data Architecture & Business Intelligence

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║              DATA ARCHITECTURE: FROM AGENT DECISIONS TO BUSINESS INSIGHT                   ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
│     ┌────────────────────────────────────────────────────────────────────────────────────────────┐   │
│     │  AGENT DECISION ──► DATA LAYER ──► MONITORING ──► ADMIN DASHBOARD ──► BUSINESS ACTION     │   │
│     └────────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                      │
│     ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐                            │
│     │  REDIS      │   │ POSTGRESQL  │   │ TIMESCALEDB │   │   NEO4J     │                            │
│     │  CacheRAG   │   │   OLTP      │   │   EVENTS    │   │CONTEXT GRAPH│                            │
│     ├─────────────┤   ├─────────────┤   ├─────────────┤   ├─────────────┤                            │
│     │ Session +   │   │ Orders      │   │ LLM calls   │   │ Bi-Temporal │                            │
│     │ RAG cache   │   │ Customers   │   │ Metrics     │   │ Decision    │                            │
│     │ TTL: 3h     │   │ Products    │   │ Agent logs  │   │ Provenance  │                            │
│     ├─────────────┤   ├─────────────┤   ├─────────────┤   ├─────────────┤                            │
│     │ WHY: Fast   │   │ WHY: ACID   │   │ WHY: Time-  │   │ WHY: "What  │                            │
│     │ context     │   │ transactions│   │ series for  │   │ did AI know │                            │
│     │ retrieval   │   │ + PII zone  │   │ trend BI    │   │ when?"      │                            │
│     └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘                            │
│           │                 │                 │                 │                                    │
│           └─────────────────┴─────────────────┴─────────────────┘                                    │
│                                       │                                                              │
│                                       ▼                                                              │
│     ┌────────────────────────────────────────────────────────────────────────────────────────────┐   │
│     │                        MONITORING + BUSINESS INTELLIGENCE                                  │   │
│     │                                                                                            │   │
│     │   PROMETHEUS ──► GRAFANA              TIMESCALE ──► POWER BI / METABASE                   │   │
│     │   • Agent latency (P95)               • Sales trends by agent recommendation              │   │
│     │   • Token spend per tier              • Fraud detection rate + savings                    │   │
│     │   • Escalation rate                   • Inventory turnover from agent queries             │   │
│     │   • Error + fallback counts           • Customer satisfaction vs automation %             │   │
│     └────────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                       │                                                              │
│                                       ▼                                                              │
│     ┌────────────────────────────────────────────────────────────────────────────────────────────┐   │
│     │                        ADMIN EMPOWERMENT: IMPROVE BUSINESS                                 │   │
│     │                                                                                            │   │
│     │   AGENT INSIGHT                      ACTION                       OUTCOME                  │   │
│     │   ───────────────────────────────────────────────────────────────────────────────────────  │   │
│     │   High escalation on pricing    ──►  Tune rules / adjust caps  ──►  Lower human workload  │   │
│     │   CV fraud flagging X product   ──►  Audit supplier / SKU      ──►  Reduce loss           │   │
│     │   Recommend agent low convert   ──►  Retrain or adjust ranking ──►  Increase revenue      │   │
│     │   Inventory queries spike       ──►  Reorder / supplier alert  ──►  Prevent stockout      │   │
│     └────────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                      │
│     ╔════════════════════════════════════════════════════════════════════════════════════════════╗   │
│     ║  RESILIENCE: Agent error → Retry 3x → Rules fallback → Human escalate. Never silent fail. ║   │
│     ╚════════════════════════════════════════════════════════════════════════════════════════════╝   │
│                                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
