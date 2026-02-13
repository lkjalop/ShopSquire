# Compliance Dashboard Wireframes (ASCII)

## Admin Navigation

```
┌───────────────────────────────────────────────────────────────────┐
│ Sidebar                                                          │
│ ────────────────────────────────────────────────────────────────  │
│ Overview | Decisions | Security | Approvals | Orders | Analytics  │
│ Incidents | Compliance                                            │
└───────────────────────────────────────────────────────────────────┘
```

## Compliance Overview (Owner-only)

```
┌───────────────────────────────────────────────────────────────────┐
│ Compliance Overview                                               │
│ Range: [7 days ▼]  [Refresh]                                      │
├───────────────────────────────────────────────────────────────────┤
│ ISO27001: 3/4 | PCI-DSS: 2/2 | ISO42001: 2/2 | NIST AI RMF: 3/3   │
│ EU AI Act: 3/3                                                    │
├───────────────────────────────────────────────────────────────────┤
│ Evidence Counts                                                   │
│ ┌─────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐      │
│ │ Security    │ │ Decisions  │ │ Incidents  │ │ Approvals  │      │
│ │ 152         │ │ 387        │ │ 8          │ │ 5          │      │
│ └─────────────┘ └────────────┘ └────────────┘ └────────────┘      │
└───────────────────────────────────────────────────────────────────┘
```

## Control Mapping Panel

```
┌───────────────────────────────────────────────────────────────────┐
│ Control Mapping                                                   │
├────────────┬───────────────────────────────┬──────────────────────┤
│ Framework  │ Control                       │ Signals              │
├────────────┼───────────────────────────────┼──────────────────────┤
│ ISO27001   │ A.8.15 Logging                │ security_events       │
│ PCI-DSS    │ 3.4 PAN unreadable            │ pci                   │
│ ISO42001   │ 7.4 AI system logging         │ decision_logs         │
│ NIST AI RMF│ MANAGE-3 Incident response    │ incidents             │
│ EU AI Act  │ Art. 14 Human oversight       │ approvals             │
└────────────┴───────────────────────────────┴──────────────────────┘
```

## Policy Enforcement Trail (Evidence Export)

```
┌───────────────────────────────────────────────────────────────────┐
│ Policy Enforcement Evidence                                       │
│ [Export JSON]                                                     │
│                                                                   │
│ Decision Logs (last 200) | Decision Audits | Security Events      │
│ ───────────────────────────────────────────────────────────────   │
│ ID       Agent     Status   Policy   Time                          │
│ dec-123  rec_agent executed v1       2026-01-20                    │
│ dec-124  pricing   approved v1       2026-01-20                    │
│                                                                   │
│ Security Events (last 200)                                        │
│ ID       Severity Path                        Tags                │
│ evt-77   high     /recommend/suggest         AML.T0043, LLM01      │
└───────────────────────────────────────────────────────────────────┘
```

## Centralized Security + Compliance Dashboard (Single-pane)

```
┌───────────────────────────────────────────────────────────────────┐
│ Live Security & Compliance (Owner)                                │
├───────────────────────────────────────────────────────────────────┤
│ Timeline: [All] [Security] [Decisions] [Approvals]                │
│ ┌───────────────────────────────────────────────────────────────┐ │
│ │ 10:42 Prompt Injection BLOCKED  AML.T0043  LLM01               │ │
│ │ 10:44 Decision Approved           ISO42001  Art.14             │ │
│ │ 10:48 PII Redaction               PCI-DSS 3.4                  │ │
│ └───────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ Right Pane: Selected Event Detail + Control Mapping               │
│ ┌───────────────────────────────────────────────────────────────┐ │
│ │ Event Detail: evt-77                                           │ │
│ │ Tags: MITRE/STRIDE/DREAD/CVSS/OWASP/KEV                        │ │
│ │ Controls: ISO27001 A.8.15, EU AI Act Art.12                    │ │
│ │ Mitigation: blocked + incident created                         │ │
│ └───────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```
