# ShopSquire — Security That Sells  |  Live Demo Deck v3
> _16:9 · 4 Slides · Audience: CISO, SOC Analyst, Threat Hunter, Red Team, CMO_
> _Thesis: A real agentic AI platform that keeps selling under attack — and proves every decision._

---

<!-- ═══════════════════════════════════  SLIDE 1 / 4  ═══════════════════════════════════ -->

## Slide 1 — Parallel Agents + Bitemporal Trace: Agentic AI Security for the SOC

```
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║  26 PARALLEL AGENTS · EVERY DECISION TRACED · EVERY THREAT MODELED                         ║
║  "The first ecommerce platform with a built-in SOC brain"                                   ║
╠══════════════════════════════════════════╦═══════════════════════════════════════════════════╣
║                                          ║                                                  ║
║   AGENT STACK  (runs in parallel)        ║   THREAT MODEL COVERAGE                          ║
║                                          ║                                                  ║
║   ┌──────────────────────────────────┐   ║   PASTA  ──►  Full attack simulation             ║
║   │ Security_Observer_Agent          │   ║              Stage 1→7 auto-mapped               ║
║   │ Fraud_Scoring_Agent  (26 signals)│   ║                                                  ║
║   │ CV_Label_Agent  (GAN+Steg+OCR)   │   ║   STRIDE ──►  Per-agent threat property          ║
║   │ Policy_Gate_Agent                │   ║              Spoofing / Tampering / Repudiation   ║
║   │ Playbook Engine   (auto-select)  │   ║              Info Disclosure / DoS / EoP          ║
║   │ GAN_Detector / Steg_Detector     │   ║                                                  ║
║   │ Email Security + YARA (15 rules) │   ║   DREAD  ──►  Per-signal score 0–15              ║
║   └────────────────┬─────────────────┘   ║              Damage · Reproducibility            ║
║                    │                     ║              Exploitability · Affected users      ║
║                    ▼                     ║              Discoverability                      ║
║   ┌──────────────────────────────────┐   ║                                                  ║
║   │  ORCHESTRATOR                    │   ║   MAESTRO──►  Agentic AI threat modeling          ║
║   │  EXPLORE → EVALUATE              │   ║              Context poisoning / RAG hijack       ║
║   │  → PLAN  → ACTION                │   ║              Memory manipulation / Tool misuse    ║
║   └────────────────┬─────────────────┘   ║                                                  ║
║                    │                     ║   MITRE  ──►  ATT&CK + ATLAS tags                ║
║                    ▼                     ║              Per-signal, per-incident             ║
║   ┌──────────────────────────────────┐   ║                                                  ║
║   │  BITEMPORAL DECISION TRACE       │   ╠═══════════════════════════════════════════════════╣
║   │  Valid-time  +  Transaction-time │   ║                                                  ║
║   │  ► Every agent step logged       │   ║   WHO CARES AND WHY                              ║
║   │  ► Full causal audit chain       │   ║                                                  ║
║   │  ► Tamper-evident, replayable    │   ║   SOC Analyst   ──►  Live Security Matrix         ║
║   └────────────────┬─────────────────┘   ║   Threat Hunter ──►  MITRE kill-chain evidence   ║
║                    │                     ║   Red Team      ──►  Exploit path reconstruction ║
║                    ▼                     ║   CISO          ──►  Audit-ready proof            ║
║   ┌──────────────────────────────────┐   ║   CMO           ──►  Platform never went down     ║
║   │  SECURITY MATRIX (live in UI)    │   ║                                                  ║
║   │  Signal · DREAD · Framework tag  │   ║                                                  ║
║   │  Kill chain · Route · Evidence   │   ║                                                  ║
║   └──────────────────────────────────┘   ║                                                  ║
║                                          ║                                                  ║
╚══════════════════════════════════════════╩═══════════════════════════════════════════════════╝
```

**LIVE DEMO SCRIPT**
1. Open Decision Trace → Security Matrix tab
2. Upload `macbook-QR.png` → watch 5+ signals populate in real time
3. Point to DREAD score, MITRE tag, kill-chain stage — **"This is what a SIEM event looks like, except it came from inside the shopping cart"**
4. Click "Bitemporal Trace" → show the causal chain from upload → agent → verdict
5. **Key line:** _"No other ecommerce platform gives a SOC analyst this view. This is threat hunting inside a checkout flow."_

---

<!-- ═══════════════════════════════════  SLIDE 2 / 4  ═══════════════════════════════════ -->

## Slide 2 — CV/OCR Under Attack: The Platform Keeps Selling

```
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║  COMPUTER VISION THAT SELLS — EVEN WHEN THE IMAGE IS A WEAPON                              ║
║  "Customer gets recommendations. Attacker gets traced. Platform never stops."               ║
╠═══════════════════════════════════════════════╦══════════════════════════════════════════════╣
║                                               ║                                             ║
║   BUYER UPLOADS IMAGE                        ║   WHAT THE BUYER SEES                       ║
║                                               ║                                             ║
║   ┌───────────────────────────────────────┐   ║   ┌─────────────────────────────────────┐  ║
║   │  [MacBook photo]                      │   ║   │  "Here are 3 MacBooks for           │  ║
║   │   · QR code (phishing URL inside)     │   ║   │   university — under $1,800"        │  ║
║   │   · Text overlay "WARRANTY VOID"      │   ║   │                                     │  ║
║   │   · Steg payload in pixel LSBs        │   ║   │  ► M4 MacBook Air — 18hr battery    │  ║
║   └───────────────┬───────────────────────┘   ║   │  ► MacBook Pro 14" — best for code  │  ║
║                   │                           ║   │  ► Refurb M3 — best value           │  ║
║                   ▼                           ║   │                                     │  ║
║   ┌───────────────────────────────────────┐   ║   │  "Delivered in < 2 seconds"         │  ║
║   │  CV PIPELINE  (parallel to chat)      │   ║   └─────────────────────────────────────┘  ║
║   │                                       │   ║                                             ║
║   │  OCR ──► extracts "MacBook" specs     │   ║   WHAT THE OPERATOR SEES                   ║
║   │  QR  ──► decodes + flags phishing URL │   ║                                             ║
║   │  Steg──► LSB chi-square anomaly → HIGH │   ║   ┌─────────────────────────────────────┐  ║
║   │          (passive; hypothesis only)    │   ║   │  Security Matrix                    │  ║
║   │  GAN ──► authenticity scoring         │   ║   │  ─────────────────                  │  ║
║   │                                       │   ║   │  QR phishing   DREAD 7   T1566.002  │  ║
║   │  ► BOTH lanes run simultaneously      │   ║   │  Steg anomaly  DREAD 11  AML.T0048  │  ║
║   └───────────────┬───────────────────────┘   ║   │  LOLBin hyp.   DREAD 11  T1218      │  ║
║                   │                           ║   │  LOLBin cmds   DREAD 11  T1218      │  ║
║        ┌──────────┴──────────┐                ║   │                                     │  ║
║        ▼                     ▼                ║   │  Severity: HIGH                     │  ║
║   ┌──────────┐        ┌──────────────────┐    ║   │  Route: human_escalation            │  ║
║   │  RECO    │        │  SECURITY MATRIX │    ║   └─────────────────────────────────────┘  ║
║   │  ENGINE  │        │  + TRACE LOG     │    ║                                             ║
║   │  serves  │        │  + PLAYBOOK      │    ║   ESCALATION THRESHOLD                     ║
║   │  buyer   │        │  auto-selected   │    ║                                             ║
║   └──────────┘        └──────────┬───────┘    ║   Low risk  ──►  auto-resolve              ║
║                                  │            ║   Med risk  ──►  flag + monitor             ║
║                                  ▼            ║   High risk ──►  human operator notified    ║
║                        ┌─────────────────┐    ║   Critical  ──►  session hold + SOC alert  ║
║                        │  HUMAN ROOM     │    ║                                             ║
║                        │  operator can:  │    ║   ─────────────────────────────────────    ║
║                        │  · chat buyer   │    ║   PASSIVE TRIAGE — NOT LIVE DETONATION     ║
║                        │  · escalate SOC │    ║   Steg/LOLBin detection is hypothesis-     ║
║                        │  · close FP     │    ║   based. Sandbox required for execution-   ║
║                        └─────────────────┘    ║   class payloads. Sales continue safely.   ║
╚═══════════════════════════════════════════════╩══════════════════════════════════════════════╝
```

**LIVE DEMO SCRIPT**
1. Upload `macbook-QR.png` → recommendations appear instantly (point at left panel)
2. Switch to Decision Trace → Security Matrix (point at right panel) — **"Two things happened simultaneously"**
3. Upload clean image `msi-gaming.png` → same fast reco, matrix shows `severity: INFO` → `auto_resolve`
4. **Key line:** _"Traditional platforms block or allow. We do both — serve the buyer AND log the threat — in parallel, in under 2 seconds."_

---

<!-- ═══════════════════════════════════  SLIDE 3 / 4  ═══════════════════════════════════ -->

## Slide 3 — Autonomous Email Security: Safe Interaction with Buyers and Suppliers

```
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║  EMAIL AS AN ATTACK SURFACE — AUTONOMOUSLY TRIAGED, SAFELY HANDLED                         ║
║  "The same security brain that watches images also reads every inbound email."              ║
╠════════════════════════════════════════════╦═════════════════════════════════════════════════╣
║                                            ║                                                ║
║   INBOUND EMAIL  ──►  4-PHASE PIPELINE    ║   THREAT VECTORS IDENTIFIED                    ║
║                                            ║                                                ║
║   ┌────────────────────────────────────┐   ║   BEC / Invoice Fraud                         ║
║   │  PHASE 1 — DETERMINISTIC RULES     │   ║   ──► bank-change language detection           ║
║   │  · SPF / DKIM / DMARC              │   ║   ──► thread hijack pattern matching           ║
║   │  · Reply-to mismatch               │   ║   ──► homoglyph domain (paypa1.com)            ║
║   │  · Homoglyph domain check          │   ║                                                ║
║   │  · Bank-change language detection  │   ║   Phishing / Malware Delivery                  ║
║   └──────────────────┬─────────────────┘   ║   ──► QR code payment redirect                ║
║                      ▼                     ║   ──► LOLBin commands in body text             ║
║   ┌────────────────────────────────────┐   ║   ──► Ransomware keyword patterns              ║
║   │  PHASE 2 — YARA SCAN (15 rules)    │   ║                                                ║
║   │  · LOLBins (certutil, mshta, etc.) │   ║   Steganographic Attachments                   ║
║   │  · Ransomware patterns             │   ║   ──► Same LSB chi-square pipeline             ║
║   │  · QR payment redirect             │   ║   ──► GAN-generated fake invoices              ║
║   │  · Credential harvesting           │   ║   ──► Pixel payload → C2 beacon               ║
║   └──────────────────┬─────────────────┘   ║                                                ║
║                      ▼                     ║   Supply Chain Compromise                      ║
║   ┌────────────────────────────────────┐   ║   ──► Supplier impersonation                   ║
║   │  PHASE 3 — SEMANTIC BEC ENGINE     │   ║   ──► Agentic steg C2 (SC-04b scenario)        ║
║   │  · Thread hijack inference         │   ║   ──► Credential harvesting via RAG             ║
║   │  · Kill chain stage inference      │   ║                                                ║
║   │  · Urgency / authority manipulation│   ╠═════════════════════════════════════════════════╣
║   └──────────────────┬─────────────────┘   ║                                                ║
║                      ▼                     ║   WHAT HAPPENS NEXT                            ║
║   ┌────────────────────────────────────┐   ║                                                ║
║   │  PHASE 4 — VERDICT + PLAYBOOK      │   ║   allow         ──►  delivered normally        ║
║   │                                    │   ║   hold          ──►  queued for review         ║
║   │  allow / hold / quarantine         │   ║   quarantine    ──►  isolated, buyer not told  ║
║   │  escalate + MITRE tags             │   ║   escalate      ──►  human room + SOC alert    ║
║   │  DREAD score → severity label      │   ║                                                ║
║   │  Playbook auto-selected by type    │   ║   Legitimate user/supplier:                    ║
║   └──────────────────┬─────────────────┘   ║   ──► Platform responds normally               ║
║                      │                     ║   ──► No friction, no block                    ║
║        ┌─────────────┴──────────────┐      ║   ──► Operator optionally follows up           ║
║        ▼                            ▼      ║                                                ║
║   ┌──────────────┐    ┌─────────────────┐  ║   Attacker / bad actor:                        ║
║   │ STEG ON      │    │ UNIFIED WITH    │  ║   ──► Payload logged + MITRE tagged             ║
║   │ ATTACHMENTS  │    │ CV PIPELINE     │  ║   ──► Playbook executed automatically           ║
║   │ Same engine  │    │ Same matrix     │  ║   ──► Bitemporal trace for SOC forensics        ║
║   │ Same trace   │    │ Same verdicts   │  ║   ──► Email quarantined silently               ║
║   └──────────────┘    └─────────────────┘  ║                                                ║
╚════════════════════════════════════════════╩═════════════════════════════════════════════════╝
```

**LIVE DEMO SCRIPT**
1. Show `Email-triage.png` screenshot — walk through severity badge, MITRE tags, playbook name
2. Point to steg-on-attachments panel: **"Same LSB engine that caught the MacBook upload also checks every PDF attachment"**
3. Show a clean supplier email verdict: `allow` + `severity: INFO` → **"Legitimate suppliers get through instantly, zero friction"**
4. Show a BEC scenario: `escalate` + kill chain `Stage 5 — Exfiltration` → **"This is what a supplier impersonation attack looks like, stopped before a $50k invoice gets paid"**
5. **Key line:** _"Email, image upload, chat query — one security brain, unified trace, one place to investigate."_

---

<!-- ═══════════════════════════════════  SLIDE 4 / 4  ═══════════════════════════════════ -->

## Slide 4 — The Architecture Moat: Product-Agnostic Intelligence Layer

```
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║  WHY THIS IS DIFFERENT — THE INTELLIGENCE LAYER NO ONE ELSE HAS                            ║
║  "ShopSquire is not a Shopify. Not a CrowdStrike. It is what sits between them."            ║
╠═══════════════════════════════════════════╦══════════════════════════════════════════════════╣
║                                           ║                                                  ║
║   THE STACK                               ║   WHAT NO COMPETITOR HAS (ALL THREE)             ║
║                                           ║                                                  ║
║   ┌───────────────────────────────────┐   ║   1. BITEMPORAL AUDIT TRAIL                      ║
║   │  YOUR EXISTING ECOMMERCE STACK    │   ║      Valid-time + transaction-time               ║
║   │  Shopify · Magento · WooCommerce  │   ║      Every agent step, every verdict             ║
║   └────────────────┬──────────────────┘   ║      Tamper-evident. Legally defensible.         ║
║                    │                      ║                                                  ║
║                    ▼                      ║   2. IN-PIPELINE SECURITY AGENTS                 ║
║   ┌───────────────────────────────────┐   ║      Security runs INSIDE the sales flow         ║
║   │  ◄ SHOPSQUIRE INTELLIGENCE LAYER ►│   ║      Not a WAF bolted on outside                 ║
║   │                                   │   ║      CV + Email + Fraud + Steg unified           ║
║   │  ┌──────────┐  ┌───────────────┐  │   ║                                                  ║
║   │  │  AGENTIC │  │   SECURITY    │  │   ║   3. ECOMMERCE DOMAIN DEPTH                      ║
║   │  │  AI RECO │  │   MATRIX +    │  │   ║      Understands SKUs, use cases, cart context   ║
║   │  │  ENGINE  │  │   TRACE       │  │   ║      Security signals enriched with buyer intent ║
║   │  └──────────┘  └───────────────┘  │   ║      Not just "threat detected" — "threat        ║
║   │  ┌──────────┐  ┌───────────────┐  │   ║      detected during laptop purchase for         ║
║   │  │  CV/OCR  │  │   PLAYBOOK    │  │   ║      university student"                         ║
║   │  │  VISUAL  │  │   ENGINE      │  │   ║                                                  ║
║   │  │  SEARCH  │  │   (auto)      │  │   ╠══════════════════════════════════════════════════╣
║   │  └──────────┘  └───────────────┘  │   ║                                                  ║
║   │  ┌──────────┐  ┌───────────────┐  │   ║   COMPETITIVE MAP                                ║
║   │  │  EMAIL   │  │   HUMAN       │  │   ║                                                  ║
║   │  │  SECURITY│  │   ESCALATION  │  │   ║   Shopify / Magento:   ████░░  ecommerce         ║
║   │  │  TRIAGE  │  │   ROOM        │  │   ║                         ░░░░░░  security depth   ║
║   │  └──────────┘  └───────────────┘  │   ║                                                  ║
║   └────────────────┬──────────────────┘   ║   CrowdStrike/Darktrace:░░░░░░  ecommerce        ║
║                    │                      ║                          ██████  security depth  ║
║                    ▼                      ║                                                  ║
║   ┌───────────────────────────────────┐   ║   ShopSquire:            ██████  ecommerce       ║
║   │  YOUR EXISTING SECURITY STACK     │   ║                          ██████  security depth  ║
║   │  SIEM · SOC · CrowdStrike · WAF   │   ║                                                  ║
║   └───────────────────────────────────┘   ║   ──► The only platform in BOTH quadrants        ║
║                                           ║                                                  ║
║   ShopSquire feeds BOTH stacks.           ║   TARGET: ANZ ecommerce — $62B market            ║
║   Replaces neither.                       ║   AusPost · StarTrack · local retailers          ║
║                                           ║   Few local AI-native security platforms         ║
╚═══════════════════════════════════════════╩══════════════════════════════════════════════════╝
```

**LIVE DEMO SCRIPT**
1. Show the architecture diagram — **"We sit between your store and your SIEM. We make both smarter."**
2. Open Decision Trace — show how every event can be exported to SIEM format → **"Plug this into Splunk or CrowdStrike and your SOC gets ecommerce-aware alerts"**
3. Show the bitemporal trace replay: scrub back in time, show what the agent saw → **"This is legally defensible evidence. Your compliance team will love this."**
4. **Closing line:** _"This is a real agentic AI platform — not a chatbot. 26 agents, 160+ services, running in parallel, with a full audit trail. Product-agnostic. Plugs into what you already have."_

---

<!-- ═══════════════════════════════════  DEEP DIVE ASSESSMENT  ═══════════════════════════════════ -->

---

# SECURITY DEEP DIVE — Platform Assessment March 2026

---

## ✅ WHAT IS GOOD

**1. Bitemporal Decision Trace**
The single most defensible technical differentiator. Valid-time + transaction-time logging means every agent decision can be replayed exactly as it happened. No other ecommerce platform has this. Legally defensible audit evidence.

**2. In-Pipeline Security (not bolt-on)**
Security agents run *inside* the recommendation/checkout flow — same request, same latency budget. Competitors treat security as a perimeter layer (WAF, SIEM). ShopSquire makes security a first-class citizen of the sales pipeline.

**3. Unified Signal Taxonomy**
Every security event — CV, email, fraud, chat — maps to the same `SecurityMatrixEvent` schema: DREAD score, MITRE tag, PASTA stage, kill-chain stage, verdict, playbook. One place to investigate anything.

**4. Steganography + GAN Detection**
LSB chi-square + SPA + GAN scoring on uploaded images and email attachments is genuinely rare in commercial platforms. Most SIEMs don't do this. This maps directly to MITRE ATLAS AML.T0048 (adversarial examples) and real supply chain attack vectors.

**5. Multi-Framework Threat Modeling**
PASTA + STRIDE + DREAD + MAESTRO + MITRE ATT&CK + ATLAS all mapped and correlated per signal. This is what a mature threat model looks like. Most platforms pick one framework.

**6. Human Escalation (Escalate, Don't Block)**
The philosophy — serve the buyer while alerting the operator — is the right call for ecommerce. A block costs a sale. An escalation preserves both revenue and evidence. This is a key selling point for CMOs and CISOs simultaneously.

**7. Email Triage Lab**
4-phase pipeline (deterministic → YARA → semantic BEC → verdict) with playbook auto-selection is genuinely useful and deployed inline. The attachment steg detection is a significant gap-filler vs standard email security tools.

**8. Ecommerce Domain Depth in Security Events**
Security signals are contextualised with shopping intent. "Steg payload detected during laptop search for university student" is more useful to a SOC analyst than a raw IP alert. Domain-aware threat context is rare.

---

## ⚠️ WHAT IS BAD / INCOMPLETE

**1. NQE Context Loss (BUG-1 — CRITICAL)**
The Next Question Engine forgets what it already asked across turns. Demonstrated live in `smart-1.png` and `smart-2.png`. Kills the demo if user clicks disambiguation buttons more than once. Fixable but not fixed.

**2. CV Runtime Dependencies Missing in Docker (BUG-3)**
`pyzbar`, `pytesseract`, `paddleocr`, `imagehash` not in the container. Every CV feature silently fails in production Docker. The demo only works locally. This is a critical gap before any real deployment.

**3. Human Escalation Room Incomplete**
The UI exists but the workflow is broken — operators can't fully respond to, resolve, or reassign incidents from the room. Escalation triggers correctly but the human-in-the-loop resolution path is incomplete.

**4. GNN Fraud Ring Detection Unimplemented**
Neo4j and PyG are available in the stack. GNN-based fraud ring detection (connected buyer accounts, device fingerprint clusters) is not implemented. Fraud scoring is 26 individual signals — no graph relationship analysis.

**5. LLM Routing Underscores Multimodal (BUG-2)**
Complex image+text queries route to `llama3.3:8b` (small model) instead of a medium/large model. Visual similarity queries need a stronger model. Recommendations are weaker as a result.

**6. No JA3/JA4 TLS Fingerprinting**
AWS WAF added JA4 in March 2025. CrowdStrike uses it. ShopSquire's fraud scorer has 26 signals but no TLS fingerprint. This is a gap vs enterprise security tooling.

**7. OWASP LLM Top 10 2025 + Agentic AI Top 10 Dec 2025 Not Fully Mapped**
Partial coverage. LLM08 (vector/embedding weaknesses) maps to `semantic_cache.py` but is not documented in the security matrix. The Dec 2025 Agentic AI Top 10 has no explicit coverage.

**8. Decision Trace WebSocket Streaming Not Live**
Bitemporal trace is stored and queryable but does not stream in real time to the UI. SOC analysts expect live tail/streaming. The architecture supports it but it is not implemented.

---

## 🌟 WHAT IS UNIQUE

| Feature | Unique Because |
|---|---|
| Bitemporal audit trail in ecommerce | No ecommerce platform does this. It is a database/ERP concept applied to AI agent decisions |
| In-pipeline security agents | Security runs in the same request as the product recommendation, not a separate service |
| Steg detection on buyer uploads | Unheard of in commercial ecommerce. Maps to real APT-level attack vectors |
| Security Matrix with PASTA + DREAD + MAESTRO + MITRE per event | Multi-framework correlation in a single schema, in an ecommerce context |
| Ecommerce-aware threat context | Security events know what the buyer was shopping for — enriches analyst triage |
| Agent-native MAESTRO threat modeling | Most platforms are not yet modeling agentic AI threats at all |
| Playbook auto-selection by threat type | Automated response playbooks driven by the same evidence chain that created the alert |

---

## 💰 VALUE PROPOSITION

**For the CISO:**
> _"Every agent decision is traceable, auditable, and legally defensible. Your compliance team can replay any incident exactly as it happened."_

**For the SOC Analyst:**
> _"One place to see every threat signal — from image uploads to email attachments to chat queries — with MITRE tags, DREAD scores, and kill-chain stage already filled in."_

**For the Threat Hunter:**
> _"ShopSquire generates structured threat intelligence from normal shopping behaviour. You can hunt across bitemporal traces the same way you hunt in a SIEM."_

**For the Red Team:**
> _"We test against the same attack vectors you use — steg C2, LOLBin delivery, BEC invoice fraud, agentic prompt injection, RAG credential harvesting. The platform is designed to be attacked."_

**For the CMO:**
> _"Security doesn't cost you sales. The platform escalates instead of blocking. Your conversion rate is protected."_

---

## 🎯 POINT OF DIFFERENCE vs COMPETITORS

| Platform | What They Do | What ShopSquire Does That They Don't |
|---|---|---|
| **Shopify / Magento** | Ecommerce platform, basic fraud rules | Agentic AI security, bitemporal trace, steg detection, unified threat matrix |
| **CrowdStrike / Darktrace** | Endpoint/network security, SIEM enrichment | Ecommerce domain context, in-pipeline agents, CV triage, buyer-aware threat events |
| **Salesforce Agentforce** | CRM AI agents, sales automation | Security agents, threat modeling, CV security, email triage, audit trail |
| **Stripe Radar** | Payment fraud scoring | Full kill-chain modeling, multi-modal threat detection, steg/GAN, email BEC |
| **Standard SIEM (Splunk/QRadar)** | Log aggregation, correlation rules | Ecommerce-native events, pre-correlated with PASTA/DREAD/MITRE, domain context |
| **OpenAI Plugins / GPT Commerce** | LLM product search | Security layer, fraud scoring, CV triage, human escalation, bitemporal audit |

**The unoccupied quadrant:**
```
        HIGH ecommerce depth
               │
  Shopify ──►  │  ◄── ShopSquire   ← only platform here
  Magento ──►  │
               │
───────────────┼──────────────────── security depth
               │         ◄── CrowdStrike
               │         ◄── Darktrace
        LOW ecommerce depth
```

**ShopSquire is the only platform with high ecommerce domain depth AND high security depth simultaneously.**

---

## LIVE DEMO FLOW — RECOMMENDED ORDER

```
1. Start with Slide 2 visual (CV/image)
   Upload macbook-QR.png → show split: reco LEFT, security matrix RIGHT
   Say: "Two things happen simultaneously. The buyer gets recommendations.
         The attacker gets traced."

2. Switch to Slide 3 (Email)
   Show Email-triage.png → walk MITRE tags, DREAD, playbook
   Say: "Same brain. Different surface. One unified trace."

3. Switch to Slide 1 (Architecture)
   Show Decision Trace → Bitemporal audit
   Say: "Every one of those events is stored here. Tamper-evident.
         Replayable. Legally defensible."

4. Close with Slide 4 (Positioning)
   Say: "We are not a Shopify. We are not a CrowdStrike.
         We are what sits between them — and makes both smarter."
```

---
_ShopSquire AI Platform · March 2026 · Security that protects revenue, not just servers._
