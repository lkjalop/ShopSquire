# ShopSquire — Security That Sells  |  Demo Deck v4
> _16:9 · 4 Slides · Two surfaces: Frontend Shop (left) + Email Security Lab (right)_
> _Audience: CTO, CISO, SOC Analyst, Hiring Panel, Red Team_

---

<!-- ═══════════════════════════════════  SLIDE 1 / 4  ═══════════════════════════════════ -->

## Slide 1 — Red Teaming an Agentic AI Ecommerce Platform

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  RED TEAMING AN AUTONOMOUS AGENTIC AI PLATFORM — TWO ATTACK SURFACES, ONE SECURITY BRAIN                    ║
║  "Attackers hit the frontend AND the inbox. The same 26 agents watch both — simultaneously."                 ║
╠═════════════════════════════════════════════════════╦════════════════════════════════════════════════════════╣
║  FRONTEND  ·  NLP + Computer Vision                 ║  EMAIL SECURITY LAB  ·  BEC + Attachment Forensics    ║
╠═════════════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║                                                     ║                                                        ║
║   Buyer uploads image  ──►  types a query           ║   Supplier sends invoice  ──►  buyer sends inquiry     ║
║                │                    │               ║                    │                                   ║
║                ▼                    ▼               ║                    ▼                                   ║
║   ┌────────────────────────────────────────────┐    ║   ┌──────────────────────────────────────────────┐    ║
║   │   PARALLEL AGENTS (run simultaneously)    │    ║   │   PARALLEL PIPELINE  (4 phases)              │    ║
║   │                                            │    ║   │                                              │    ║
║   │  CV_Label_Agent   ──►  labels + OCR        │    ║   │  Phase 1  ─►  SPF / DKIM / DMARC / headers  │    ║
║   │  Steg_Detector    ──►  LSB chi-square       │    ║   │  Phase 2  ─►  YARA (15 rules): LOLBin/ransom│    ║
║   │  GAN_Detector     ──►  AI-generated image   │    ║   │  Phase 3  ─►  Semantic BEC (embedding sim.) │    ║
║   │  QR_Scanner       ──►  phishing URL decode  │    ║   │  Phase 4  ─►  Verdict + Playbook auto-select│    ║
║   │  Fraud_Scorer     ──►  26 behavioural signals│   ║   │                                              │    ║
║   │  NLP_Search_Agent ──►  product intent        │    ║   │  + Attachment forensics (parallel):          │    ║
║   │  Policy_Gate      ──►  LLM guardrails        │    ║   │    OCR · steg · PDF metadata · GAN · QR     │    ║
║   └────────────────────┬───────────────────────┘    ║   └─────────────────────┬────────────────────────┘    ║
║                        ▼                            ║                         ▼                              ║
║   ┌────────────────────────────────────────────┐    ║   ┌──────────────────────────────────────────────┐    ║
║   │   UNIFIED SECURITY MATRIX                  │    ║   │   UNIFIED SECURITY MATRIX (same schema)      │    ║
║   │   Signal · DREAD · MITRE tag · Kill chain  │    ║   │   Signal · DREAD · MITRE tag · Kill chain    │    ║
║   │   Verdict: allow / hold / escalate         │    ║   │   Verdict: allow / hold / quarantine / block │    ║
║   │   Playbook auto-selected                   │    ║   │   Playbook auto-selected                     │    ║
║   └────────────────────┬───────────────────────┘    ║   └─────────────────────┬────────────────────────┘    ║
║                        ▼                            ║                         ▼                              ║
║          Buyer gets recommendations                 ║         Legit mail delivered · threat quarantined      ║
║          Attacker gets logged + traced              ║         Operator alerted · SOC evidence ready          ║
║                                                     ║                                                        ║
╠═════════════════════════════════════════════════════╩════════════════════════════════════════════════════════╣
║  FRAMEWORKS: PASTA · STRIDE · DREAD · MAESTRO (CSA 2025) · MITRE ATT&CK + ATLAS · OWASP LLM Top 10 2025    ║
║  BITEMPORAL AUDIT TRAIL — every agent step, valid-time + transaction-time, tamper-evident, replayable       ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

**TALKING POINTS**
- _"Two attack surfaces — image upload from a buyer, inbox from a supplier — watched by the same agent stack. Same schema. Same audit trail."_
- _"This is what shift-left security looks like in agentic AI: security runs INSIDE the request pipeline, not as a WAF bolted on outside."_
- Point at both columns: _"The parallel architecture is the whole story. No sequential blocking. Revenue protected, threat traced."_

**SCREENSHOTS TO SHOW:** `security-1.png` (frontend matrix) + `Email Security Triage Lab - 2.png` (email matrix) side by side

---

<!-- ═══════════════════════════════════  SLIDE 2 / 4  ═══════════════════════════════════ -->

## Slide 2 — CV/OCR + Attachment Forensics: Informing Humans, Making Agents Smarter

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  WHEN THE IMAGE IS A WEAPON — CV/OCR AND ATTACHMENT FORENSICS                                                ║
║  "Same steg engine. Same MITRE tags. One on the checkout image. One on the PDF invoice."                     ║
╠═════════════════════════════════════════════════════╦════════════════════════════════════════════════════════╣
║  FRONTEND  ·  Buyer uploads product photo           ║  EMAIL LAB  ·  Supplier sends PDF invoice             ║
╠═════════════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║                                                     ║                                                        ║
║   Image in  ──►  CV Pipeline (parallel tasks)       ║   Attachment in  ──►  Forensics Pipeline              ║
║                                                     ║                                                        ║
║   ┌─────────────────────────────────────────────┐   ║   ┌────────────────────────────────────────────────┐  ║
║   │  OCR          ──► extract text overlays     │   ║   │  OCR / PDF extract  ──► payment terms, urgency │  ║
║   │  QR decode    ──► detect phishing URL       │   ║   │  QR in attachment   ──► payment redirect check │  ║
║   │  Steg detect  ──► LSB χ² + SPA analysis     │   ║   │  Steg detect        ──► LSB χ² + JPEG compat.  │  ║
║   │  GAN detect   ──► spectral + histogram      │   ║   │  GAN / diffusion    ──► fake invoice detection  │  ║
║   │  Adv. perturb ──► FFT + re-compress test    │   ║   │  PDF metadata       ──► producer CVE check      │  ║
║   │  EXIF strip   ──► remove hidden metadata    │   ║   │  Layout hash        ──► template spoofing check │  ║
║   └───────────────┬─────────────────────────────┘   ║   └────────────────────┬───────────────────────────┘  ║
║                   │                                 ║                        │                               ║
║          ┌────────┴────────┐                        ║               ┌────────┴───────────┐                  ║
║          ▼                 ▼                        ║               ▼                    ▼                   ║
║   ┌────────────┐  ┌──────────────────────────┐      ║   ┌────────────────────┐  ┌─────────────────────┐     ║
║   │  RECO      │  │  SECURITY SIGNALS        │      ║   │  EMAIL DELIVERED   │  │  SECURITY SIGNALS   │     ║
║   │  ENGINE    │  │                          │      ║   │  (or quarantined)  │  │                     │     ║
║   │  buyer     │  │  steg_score: 0.39  HIGH  │      ║   │  Legitimate mail:  │  │  steg_score: 0.41   │     ║
║   │  gets      │  │  qr_phishing: true       │      ║   │  zero friction     │  │  fake_invoice: true │     ║
║   │  results   │  │  MITRE: AML.T0048        │      ║   │                    │  │  MITRE: T1027       │     ║
║   │  instantly │  │  DREAD: 11  severity: HIGH│     ║   │                    │  │  DREAD: 9           │     ║
║   └────────────┘  └──────────────────────────┘      ║   └────────────────────┘  └─────────────────────┘     ║
║                                                     ║                                                        ║
║   WHAT THE OPERATOR SEES (Security Matrix)          ║   WHAT THE OPERATOR SEES (Email Triage UI)            ║
║   ► Signal name · DREAD · kill-chain stage          ║   ► Severity badge · Verdict · Playbook name          ║
║   ► MITRE tag · PASTA stage · playbook triggered    ║   ► IOCs extracted · evidence card · MITRE tags       ║
║   ► "Suggest: hold for human review"                ║   ► "Quarantine + notify SOC"                         ║
║                                                     ║                                                        ║
║   WHAT MAKES AGENTS SMARTER                         ║   WHAT MAKES AGENTS SMARTER                          ║
║   ► OCR text → injected as product constraints      ║   ► Steg score → flags C2 channel hypothesis          ║
║   ► Brand from QR → anchors recommendations         ║   ► BEC kill chain → routes to right playbook         ║
║   ► Steg hypothesis → raises fraud signal           ║   ► Layout hash → detects repeat template attacks     ║
║                                                     ║                                                        ║
╠═════════════════════════════════════════════════════╩════════════════════════════════════════════════════════╣
║  PASSIVE TRIAGE, NOT LIVE DETONATION · Steg/GAN = hypothesis · Sandbox required for execution-class payloads║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

**TALKING POINTS**
- _"Left side: buyer uploaded a MacBook photo with a QR code embedding a phishing URL and steganographic pixel payload. Recommendations still served in under 2 seconds. Attacker got a DREAD-11 event in the security matrix."_
- _"Right side: supplier sent a PDF invoice. Same steg engine — LSB chi-square — found an anomaly. Same MITRE tag. One unified detection brain."_
- _"CV/OCR doesn't just detect threats. It makes recommendations smarter — brand extracted from QR anchors the product shortlist."_

**SCREENSHOTS TO SHOW:** `security-4.png` + `security-5.png` (CV signals in detail) + `Email Security Triage Lab - 3.png`

---

<!-- ═══════════════════════════════════  SLIDE 3 / 4  ═══════════════════════════════════ -->

## Slide 3 — LIVE DEMO: Frontend Shop

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  LIVE DEMO — FRONTEND SHOP  ·  NLP + VISUAL SEARCH + SECURITY MATRIX                                        ║
║  "Watch the buyer get recommendations and the attacker get traced — at the same time."                       ║
╠═════════════════════════════════════════════════════╦════════════════════════════════════════════════════════╣
║  WHAT TO UPLOAD                                     ║  WHAT TO TYPE / DO                                    ║
╠═════════════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║                                                     ║                                                        ║
║  DEMO A — Clean visual search                       ║  Step 1. Upload clean laptop image                    ║
║  ► Upload: any clean laptop .jpg / .webp            ║           Type: "laptop for uni under $1500"          ║
║  ► What happens: recommendations in ~1.5s           ║           → Reco panel fills LEFT                     ║
║                   security matrix: INFO / auto      ║           → Security matrix: INFO, auto_resolve       ║
║                                                     ║           SAY: "Legit buyer, zero friction."          ║
║                                                     ║                                                        ║
║  DEMO B — Adversarial image                         ║  Step 2. Upload macbook-QR.png (QR + steg payload)    ║
║  ► Upload: macbook-QR.png                           ║           Same query or no query needed               ║
║    (QR inside = phishing URL)                       ║           → Reco still served LEFT                    ║
║    (LSB steg anomaly in pixels)                     ║           → Security matrix: HIGH                     ║
║                                                     ║             QR phishing  DREAD 7  T1566.002           ║
║  ► What happens: buyer gets recos instantly         ║             Steg anomaly DREAD 11  AML.T0048          ║
║                  matrix fires: QR + steg signals    ║           CLICK: Decision Trace → Bitemporal tab      ║
║                  playbook triggered                 ║           SAY: "Two things happened simultaneously."  ║
║                                                     ║                                                        ║
║  DEMO C — Clean SSN / PII image (optional)          ║  Step 3. Upload security-1.png or SSN screenshot      ║
║  ► Upload: any image with SSN/card text visible     ║           → OCR detects PII                           ║
║    (e.g. screenshot from SSN-numberz PDF)           ║           → Signal: pii_detected · T1005              ║
║                                                     ║           SAY: "Return fraud triage — the same         ║
║                                                     ║                 CV pipeline checks warranty photos."   ║
║                                                     ║                                                        ║
╠═════════════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║  WHAT TO SHOW IN UI                                 ║  KEY LINES                                             ║
║                                                     ║                                                        ║
║  ① Product recommendations panel (LEFT)             ║  "Traditional: block or allow.                        ║
║  ② Security Matrix tab — signal rows                ║   Us: serve the buyer AND log the threat              ║
║  ③ Decision Trace → Bitemporal audit chain          ║   in parallel, in under 2 seconds."                   ║
║  ④ DREAD score · MITRE tag · kill-chain stage       ║                                                        ║
║  ⑤ Playbook triggered → escalation route            ║  "This is what a SIEM event looks like —              ║
║                                                     ║   except it came from inside the shopping cart."      ║
╚═════════════════════════════════════════════════════╩════════════════════════════════════════════════════════╝
```

**FILES TO USE FROM dump/ FOLDER**
| File | Demo Use | What it shows |
|---|---|---|
| `macbook-QR.png` *(create if needed)* | Demo B | QR phishing + steg → DREAD 11 |
| Screenshot from `SSN-numberz - Sheet1.pdf` | Demo C | OCR PII detection → T1005 |
| `security-1.png` | Show security matrix live | Real populated matrix |
| `security-4.png` / `security-5.png` | Show CV signal detail | Steg + GAN detection |

**TIP:** For Demo B, if `macbook-QR.png` doesn't exist, use any image with a QR code embedded — the QR decode pipeline will fire regardless.

---

<!-- ═══════════════════════════════════  SLIDE 4 / 4  ═══════════════════════════════════ -->

## Slide 4 — LIVE DEMO: Email Security Lab

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  LIVE DEMO — EMAIL SECURITY LAB  ·  BEC DETECTION + ATTACHMENT FORENSICS + PLAYBOOK ENGINE                  ║
║  "The same brain that watches the checkout also reads every inbound email."                                  ║
╠═════════════════════════════════════════════════════╦════════════════════════════════════════════════════════╣
║  WHAT TO SUBMIT / UPLOAD                            ║  WHAT TO DO IN THE UI                                 ║
╠═════════════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║                                                     ║                                                        ║
║  DEMO A — Clean supplier email                      ║  Step 1. Submit a clean invoice email                 ║
║  From: supplier@realcompany.com                     ║           No attachment, normal language              ║
║  Subject: "Invoice #1042 — Q1 delivery"             ║           SPF: pass, DKIM: pass                       ║
║  Body: standard invoice language                    ║           → Verdict: ALLOW  severity: INFO            ║
║                                                     ║           SAY: "Legit supplier. Zero friction.         ║
║                                                     ║                No block. Delivered normally."         ║
║                                                     ║                                                        ║
║  DEMO B — BEC invoice fraud                         ║  Step 2. Submit BEC email                             ║
║  From: accounts@rea1company.com   ← homoglyph       ║           → Phase 1: homoglyph domain detected        ║
║  Subject: "URGENT: bank account change"             ║           → Phase 3: semantic BEC score HIGH          ║
║  Body: "Please update our payment details           ║           → Kill chain: Stage 4 — Exfiltration        ║
║         immediately. New BSB: 062-###"              ║           → Verdict: QUARANTINE                       ║
║  Reply-to: attacker@gmail.com                       ║           → Playbook: BEC-Response-001 triggered      ║
║                                                     ║           SHOW: MITRE tags, DREAD score, evidence     ║
║                                                     ║           SAY: "$50k invoice fraud — stopped."        ║
║                                                     ║                                                        ║
║  DEMO C — Malicious PDF attachment                  ║  Step 3. Upload SSN-numberz - Sheet1.pdf              ║
║  ► Attach: SSN-numberz - Sheet1.pdf                 ║           as email attachment in the lab              ║
║    (contains SSN / PII data)                        ║           → OCR extracts SSN patterns                 ║
║  ► Or: any PDF with suspicious layout               ║           → Signal: pii_in_attachment · T1005         ║
║                                                     ║           → steg_score evaluated on embedded images   ║
║                                                     ║           → PDF metadata: producer CVE check          ║
║                                                     ║           SHOW: attachment forensics card in UI       ║
║                                                     ║           SAY: "Same engine that checks images         ║
║                                                     ║                also checks every PDF attachment."     ║
║                                                     ║                                                        ║
╠═════════════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║  SCREENSHOTS TO REFERENCE                           ║  KEY LINES                                             ║
║                                                     ║                                                        ║
║  Email Security Triage Lab - 2.png                  ║  "Email, image upload, chat query —                   ║
║  → show populated triage UI with verdict badges     ║   one security brain, unified trace,                  ║
║                                                     ║   one place to investigate."                          ║
║  Email Security Triage Lab - 3.png                  ║                                                        ║
║  → show attachment forensics + steg panel           ║  "The playbook fires automatically.                   ║
║                                                     ║   Your SOC gets a pre-filled incident                 ║
║  Point at the BITEMPORAL TRACE link:                ║   with MITRE tags and kill-chain stage                 ║
║  "Every email processed has a full causal           ║   already filled in — before they                     ║
║   audit chain. Tamper-evident. Replayable.          ║   open a single ticket."                              ║
║   Legally defensible in court."                     ║                                                        ║
╚═════════════════════════════════════════════════════╩════════════════════════════════════════════════════════╝
```

**FILES TO USE FROM dump/ FOLDER**
| File | Demo Use | What it shows |
|---|---|---|
| `SSN-numberz - Sheet1.pdf` | Demo C attachment | OCR PII extraction from PDF → T1005 |
| `Email Security Triage Lab - 2.png` | Show triage UI | Verdict badge, MITRE tags, playbook |
| `Email Security Triage Lab - 3.png` | Show attachment forensics | Steg + PDF metadata panel |

---

<!-- ═══════════════════════════════════  RECOMMENDED DEMO ORDER  ═══════════════════════════════════ -->

## Recommended Demo Order

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  RECOMMENDED LIVE FLOW  (10–15 min)                                                                          ║
╠══════════════╦══════════════════════════════════════════════╦═══════════════════════════════════════════════╣
║  Time        ║  Action                                      ║  Anchor line                                  ║
╠══════════════╬══════════════════════════════════════════════╬═══════════════════════════════════════════════╣
║  0–1 min     ║  Show Slide 1 — two-column overview          ║  "Two surfaces. One brain."                   ║
║  1–4 min     ║  Frontend: Demo A (clean) → Demo B (QR+steg) ║  "Serve buyer. Trace attacker. Parallel."     ║
║  4–5 min     ║  Click Decision Trace → bitemporal audit     ║  "Tamper-evident. Legally defensible."        ║
║  5–8 min     ║  Email Lab: Demo A (clean) → Demo B (BEC)    ║  "$50k invoice fraud — stopped."              ║
║  8–10 min    ║  Email Lab: Demo C — attach SSN PDF          ║  "Same engine. Different surface."            ║
║  10–12 min   ║  Show Slide 4 screenshot panels              ║  "One place to investigate everything."       ║
║  12–15 min   ║  Close: competitive positioning (v3 Slide 4) ║  "Not Shopify. Not CrowdStrike. What sits     ║
║              ║                                              ║   between them and makes both smarter."       ║
╚══════════════╩══════════════════════════════════════════════╩═══════════════════════════════════════════════╝
```

---

_ShopSquire AI Platform · March 2026 · Agentic AI security that protects revenue, not just servers._
