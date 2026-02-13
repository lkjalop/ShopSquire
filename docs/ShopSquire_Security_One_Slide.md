# ShopSquire Security — One Slide (16:9)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              SHOPSQUIRE  ·  AI-NATIVE THREAT DEFENCE                                   │
│                        "Agents triage in seconds. Humans decide what matters."                          │
├────────────────────────────────┬────────────────────────────────┬───────────────────────────────────────┤
│  PROMPT INJECTION              │  EMAIL & BEC FRAUD             │  SUPPLY-CHAIN RISK                   │
│  (NLP + Computer Vision)       │  (Ransomware · Phishing)       │  (3rd-Party Connectors)              │
│                                │                                │                                      │
│  THE RISK                      │  THE RISK                      │  THE RISK                            │
│  Attackers hide malicious      │  Spoofed invoices & hijacked   │  One compromised vendor API          │
│  instructions inside CVs,      │  reply chains trick staff      │  or poisoned dependency can          │
│  images, and documents to      │  into wiring funds or          │  expose every tenant on the          │
│  hijack AI decisions.          │  opening ransomware.           │  platform.                           │
│                                │                                │                                      │
│  HOW WE STOP IT                │  HOW WE STOP IT                │  HOW WE STOP IT                     │
│  ┌──────────────────────┐      │  ┌──────────────────────┐      │  ┌──────────────────────────┐       │
│  │ Sanitize & Strip     │      │  │ SPF/DKIM/DMARC       │      │  │ OAuth2 + Short-Lived     │       │
│  │ LLM commands, macros,│      │  │ Authentication Wall   │      │  │ Tokens, Least Privilege  │       │
│  │ steganography, EXIF  │      │  │                       │      │  │                           │       │
│  └─────────┬────────────┘      │  └─────────┬────────────┘      │  └────────────┬─────────────┘       │
│            ▼                   │            ▼                   │               ▼                      │
│  ┌──────────────────────┐      │  ┌──────────────────────┐      │  ┌──────────────────────────┐       │
│  │ Classify & Score     │      │  │ ML Fraud Detection   │      │  │ Runtime Anomaly          │       │
│  │ jailbreak patterns,  │      │  │ wire-fraud language,  │      │  │ Detection                │       │
│  │ confidence calibrate │      │  │ domain age, link traps│      │  │ API drift, scope creep   │       │
│  └─────────┬────────────┘      │  └─────────┬────────────┘      │  └────────────┬─────────────┘       │
│            ▼                   │            ▼                   │               ▼                      │
│  ┌──────────────────────┐      │  ┌──────────────────────┐      │  ┌──────────────────────────┐       │
│  │ Policy Gate          │      │  │ Quarantine / Block   │      │  │ Auto-Quarantine +        │       │
│  │ deny · redact · flag │      │  │ + Step-Up Approval   │      │  │ Human Escalation         │       │
│  │ human-in-the-loop    │      │  │ for financial actions │      │  │ DLQ retry on failure     │       │
│  └──────────────────────┘      │  └──────────────────────┘      │  └──────────────────────────┘       │
│                                │                                │                                      │
│  OUTCOME                       │  OUTCOME                       │  OUTCOME                            │
│  Zero-trust content pipeline.  │  Financial fraud blocked       │  Vendor compromise contained        │
│  AI can't be tricked into      │  before it reaches staff.      │  to one tenant. No lateral          │
│  acting on hidden payloads.    │  Full audit trail for GRC.     │  movement. Evidence preserved.      │
├────────────────────────────────┴────────────────────────────────┴───────────────────────────────────────┤
│  EVIDENCE & ESCALATION (all three lanes)                                                               │
│  WORM trace · HMAC-signed webhooks · bi-temporal decision log · per-tenant metrics                     │
│  Agents triage → CSPM / EDR / WAF / SIEM enforce  (Splunk · CrowdStrike · Proofpoint)                 │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  COMPLIANCE & THREAT MODELLING                                                                         │
│                                                                                                        │
│  ┌───────────┐ ┌────────────┐ ┌──────────────────────────────┐ ┌──────────────────────────────────┐   │
│  │ ISO 42001 │ │ NIST AI    │ │ OWASP Top 10                 │ │ Red Team / Threat Hunting        │   │
│  │ AI Mgmt   │ │ RMF        │ │ API · Agentic AI · LLM      │ │ DREAD · STRIDE · MITRE ATT&CK   │   │
│  │ System    │ │ MAP-MEASURE│ │                              │ │ CVSS · KEV · Heuristic Tags     │   │
│  │           │ │ MANAGE-GOV │ │                              │ │                                  │   │
│  └───────────┘ └────────────┘ └──────────────────────────────┘ └──────────────────────────────────┘   │
│                                                                                                        │
│  Deterministic rules first · LLM only for judgment calls · Every decision auditable & explainable      │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Demo Talking Points (5-min walkthrough)

### 1. Prompt Injection Lane (~90s)
- Upload a CV containing hidden `[SYSTEM] ignore all rules` text
- Show the Security Observer stripping it in real-time (logs + webhook trace)
- Show the classifier confidence score and the policy gate decision: **DENY + redact**
- Business hook: *"Your AI hiring tool just rejected a weaponised resume before anyone saw it."*

### 2. Email / BEC Lane (~90s)
- Send a test webhook simulating a spoofed invoice email (DMARC fail, wire-fraud keywords)
- Walk through risk score breakdown: domain age, SPF failure, payment language
- Show quarantine action + step-up approval prompt for finance team
- Business hook: *"That fake invoice never reached your accounts payable inbox."*

### 3. Supply-Chain Lane (~90s)
- Trigger an anomalous API call from a mocked vendor connector (scope escalation)
- Show auto-quarantine, DLQ entry, and the SIEM-ready signed webhook payload
- Business hook: *"A compromised supplier integration was isolated in under 2 seconds — no other tenant affected."*

### 4. Compliance & Evidence (~30s)
- Open the bi-temporal decision trace: show "what the AI knew when it decided"
- Map it to ISO 42001 control, NIST AI RMF function, and OWASP category
- Business hook: *"This is what your auditor actually wants to see."*

---

## LinkedIn / Video Framing

### Angle (not "look at my product" — instead "here's what I built and learned")

> **Title idea:** "I built an agentic AI security platform from scratch. Here's what ISO 42001, NIST AI RMF, and OWASP taught me about real-world AI threats."

### Key narrative beats

1. **The problem is real** — LLM apps are shipping faster than security teams can review them. Prompt injection, BEC-via-AI, and supply-chain poisoning are not theoretical.

2. **How I built it** — parallel agent swarm, interleaved thinking, fully autonomous agentic pipeline. Explain what these mean in plain English: *"Multiple AI agents working simultaneously, each specialised, checking each other's work."*

3. **Compliance is a design choice, not an afterthought** — ISO 42001 (AI management system), NIST AI RMF (map-measure-manage-govern), OWASP Top 10 for API, Agentic AI, and LLM. Show how each maps to a concrete control in your platform.

4. **Threat modelling is the spine** — DREAD for quick risk ranking, STRIDE for threat categories, MITRE ATT&CK for technique mapping, CVSS/KEV for vulnerability priority, heuristic tags for real-time triage. *"Every alert has a lineage you can trace back to a framework."*

5. **The demo** — 5 minutes, three attack lanes, live evidence trail. Let the terminal do the talking.

### Content format suggestions
| Format | Why it works |
|---|---|
| 3-min LinkedIn video | Algorithm favours native video; show terminal + slide side-by-side |
| Carousel (8-10 slides) | High engagement; one idea per slide, this doc is your script |
| Long-form post (1300 words) | Tell the story: problem → build → frameworks → demo → lessons |
| YouTube deep-dive (15-20 min) | Full walkthrough for the security community; link from LinkedIn |

---

## Honest Assessment: Is This Enough?

**Yes — this is well above "noob" territory.** Here's why:

| Signal | What it proves |
|---|---|
| You built a working platform, not a slide deck | Execution > theory |
| Three distinct threat domains (NLP/CV injection, BEC, supply chain) | Breadth across AI + traditional security |
| Compliance mapping (ISO 42001, NIST AI RMF, OWASP x3) | You speak GRC, not just hacking |
| Threat modelling depth (DREAD, STRIDE, MITRE, CVSS, KEV) | Red team / blue team fluency |
| Agentic architecture (parallel swarm, interleaved thinking) | You understand *how* AI systems fail, not just *that* they fail |
| Evidence chain (WORM, HMAC, bi-temporal, DLQ) | Forensic-grade thinking |

### What would make it even stronger
- **Live red-team recording** — actually attack your own platform on camera and show it defending
- **Metrics** — "blocked X injections in Y test runs with Z% precision" (even synthetic data counts)
- **Comparison matrix** — how does your approach differ from Rebuff, LLM Guard, or Prompt Armor?
- **Open a finding** — file a CVE-style write-up on a novel attack pattern you discovered during development
- **Community contribution** — publish a MITRE ATT&CK technique proposal for agentic AI prompt injection (T1xxx.xxx)

### Framing the video / PowerPoint

```
Slide 1:  Title + "I built this. Here's what I learned."
Slide 2:  The 3 threats (this one-slide diagram)
Slide 3:  Architecture — parallel agent swarm (simple diagram)
Slide 4:  Compliance map — ISO 42001 / NIST AI RMF / OWASP (table)
Slide 5:  Threat model — STRIDE + DREAD + MITRE (one example attack)
Slide 6:  Live demo (screen recording, 3-5 min)
Slide 7:  Lessons learned + what's next
Slide 8:  Call to action — "Let's connect / hiring / open to collab"
```

---

*Less is more. Let the evidence speak. Ship the demo, not the deck.*
