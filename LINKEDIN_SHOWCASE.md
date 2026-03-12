# ShopSquire — LinkedIn Showcase Guide
_What to post, what angle to use, what to record — March 2026_

---

## Overview: 7 Angles You Can Own

| # | Angle | Who Sees It | What It Signals |
|---|---|---|---|
| 1 | Agentic AI Architecture | AI Engineers, CTOs | System design depth |
| 2 | NLP / Natural Query Engine | ML Engineers, PMs | Applied NLP at product level |
| 3 | Computer Vision + OCR Security | AI Security, MLOps | Multi-modal threat detection |
| 4 | AI Security Threat Matrix | Security architects, CISO teams | MITRE/OWASP/PASTA fluency |
| 5 | Compliance Engineering | Fintech/govtech hiring managers | Regulatory awareness |
| 6 | Bitemporal Decision Trace | Data Engineers, compliance leads | Advanced data architecture |
| 7 | E-commerce Agentic Loop | Product Engineers, founders | Business-value thinking |

Post one angle per week. Seven weeks = a complete mini-series.

---

## Slide Wireframes (ASCII 16:9 — 80×44 chars)

Each block below is a screen/slide you can record, screenshot, or use as a video frame.
Use OBS or Windows Snipping Tool to capture your actual terminal / browser running these flows.

---

### SLIDE 1 — Platform Architecture Overview

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  SHOPSQUIRE — AI-Native Commerce Intelligence Platform            [Slide 1] ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║   USER INPUT                      AGENTIC LAYER                OUTPUT       ║
║   ──────────                      ─────────────                ──────       ║
║                                                                              ║
║   💬 Text query  ──────────────►  ┌──────────────────────┐                 ║
║                                   │   NLP / NQE Engine    │──► Product Grid ║
║   🖼️  Image upload ─────────────► │   Intent · Persona    │                 ║
║                                   │   Budget · Slot Fill  │──► DecisionTrace║
║   🔍 Order ID    ──────────────►  └──────────────────────┘                 ║
║                          │                   │                              ║
║                          ▼                   ▼                              ║
║                 ┌────────────────┐  ┌────────────────────┐                 ║
║                 │  CV PIPELINE   │  │  SECURITY OBSERVER  │                 ║
║                 │  YOLOv8        │  │  DREAD scoring      │                 ║
║                 │  OCR/Tesseract │  │  MITRE ATLAS        │                 ║
║                 │  EXIF forensics│  │  OWASP LLM Top10    │                 ║
║                 │  Polyglot det. │  │  PASTA staging      │                 ║
║                 │  Luhn validate │  │  STRIDE mapping     │                 ║
║                 └────────┬───────┘  └────────────────────┘                 ║
║                          │                                                  ║
║                          ▼                                                  ║
║                 ┌────────────────┐  ┌────────────────────┐                 ║
║                 │  ESCALATION    │  │  BITEMPORAL TRACE   │                 ║
║                 │  WS → SSE      │  │  valid_from/to      │                 ║
║                 │  → Poll        │  │  system_from/to     │                 ║
║                 │  Buyer + Staff │  │  Immutable audit    │                 ║
║                 └────────────────┘  └────────────────────┘                 ║
║                                                                              ║
║  Stack: FastAPI · React/Vite · SQLite · PyG · YOLOv8 · Tesseract · pyzbar  ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**What to record:** Browser split-screen — left: storefront chat, right: Decision Trace
modal open showing Timeline + Security Matrix tabs updating in real time.

---

### SLIDE 2 — Agentic Architecture Deep-Dive

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTIC AI ARCHITECTURE — ShopSquire Agent Chain                 [Slide 2] ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │                     EPISODIC MEMORY (3-tier)                        │    ║
║  │  Working Memory   ◄──►  Session Memory   ◄──►  Long-term Memory     │    ║
║  │  (active turn)         (conversation)         (user profile +       │    ║
║  │                                                RAPTOR summaries)    │    ║
║  └────────────────────────────┬────────────────────────────────────────┘    ║
║                               │ context injection                           ║
║                               ▼                                             ║
║    Query ──► [INTENT AGENT] ──► [NQE AGENT] ──► [RANKING AGENT]            ║
║              │                  │                │                          ║
║              │ intent + slots   │ smart Qs       │ listwise rerank          ║
║              │ budget parsing   │ 6 templates    │ GNN fraud signal         ║
║              │ persona detect   │ per category   │ diversity enforce        ║
║              │                  │                │ contrastive WHY          ║
║              ▼                  ▼                ▼                          ║
║         ┌──────────────────────────────────────────────────────────┐        ║
║         │              DECISION TRACE WRITER                       │        ║
║         │  event_type · intent · nqe_plan · ranking_result ·       │        ║
║         │  security_signals · valid_from · system_from             │        ║
║         └──────────────────────────────────────────────────────────┘        ║
║                                                                              ║
║    Image ──► [CV AGENT] ──► [SECURITY AGENT] ──► [ESCALATION AGENT]        ║
║              │                │                   │                         ║
║              │ YOLOv8 detect  │ DREAD score        │ WS/SSE/poll            ║
║              │ OCR extract    │ PASTA stage        │ staff routing          ║
║              │ EXIF forensics │ MITRE map          │ warranty check         ║
║              │ QR decode      │ kill-chain tag     │ seed chat context      ║
║                                                                              ║
║  Agent policies: config/agent_policies.yml   Memory: src/app/services/     ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**What to record:** Show the `episodic_memory.py` file open + the `nqe.py` file, then
switch to browser and show how asking "I need a laptop for gaming" triggers 2-3
clarifying questions driven by the NQE template.

---

### SLIDE 3 — Natural Query Engine (NLP)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  NLP — Natural Query Engine (NQE) Pipeline                        [Slide 3] ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  USER: "I need a laptop for university gaming, budget around $800"           ║
║                                                                              ║
║  STEP 1 — INTENT EXTRACTION (PEG-style parser + semantic slot fill)         ║
║  ┌──────────────────────────────────────────────────────────────────┐        ║
║  │  category: laptop         use_case: gaming + university          │        ║
║  │  budget_max: 800          brand: [none]                          │        ║
║  │  persona: student         intent_confidence: 0.87                │        ║
║  │  is_open_ended: TRUE  ──► trigger NQE question plan              │        ║
║  └──────────────────────────────────────────────────────────────────┘        ║
║                                                                              ║
║  STEP 2 — QUESTION PLAN (config/nqe_templates_*.json, 6 categories)         ║
║  ┌──────────────────────────────────────────────────────────────────┐        ║
║  │  Q1: "Do you need Windows, or are you open to other platforms?"  │        ║
║  │  Q2: "Which games? (Minecraft casual vs AAA like Cyberpunk)"     │        ║
║  │  [budget/brand/specs/intent_conf gate → max 2 questions shown]  │        ║
║  └──────────────────────────────────────────────────────────────────┘        ║
║                                                                              ║
║  STEP 3 — SLOT MERGE + USE-CASE KNOWLEDGE BASE                              ║
║  ┌──────────────────────────────────────────────────────────────────┐        ║
║  │  game: cyberpunk ──► tier: aaa_heavy ──► specs: RTX 3060+, 16GB  │        ║
║  │  use_case: gaming_aaa_heavy ──► ram_gb_min: 16, gpu: discrete    │        ║
║  │  budget_status: "tight for AAA tier" ──► budget_advice: ⚠️        │        ║
║  └──────────────────────────────────────────────────────────────────┘        ║
║                                                                              ║
║  STEP 4 — PRODUCT RANKING (GNN + listwise + contrastive WHY)                ║
║  ┌──────────────────────────────────────────────────────────────────┐        ║
║  │  #1  Lenovo Legion 5  score: 87  reasons: [RTX 3060, 16GB, $799] │        ║
║  │  #2  ASUS TUF A15     score: 79  reasons: [RX 6600M, 8GB, $699]  │        ║
║  │  WHY: "Ranked for AAA gaming + student portability, matched $800"│        ║
║  └──────────────────────────────────────────────────────────────────┘        ║
║                                                                              ║
║  NLP stack: PEG parser · slot merge · NQE · use_case_knowledge_base.json    ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**What to record:** Screen-capture the live chat asking "I need a laptop for gaming around
$800". Show the NQE questions appearing, then show the products that result with the
budget-fitness ⚠️ note and the "Why Recommended" breakdown. Narrate each step.

---

### SLIDE 4 — Computer Vision + OCR Security Pipeline

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  COMPUTER VISION + OCR — Threat Detection Pipeline               [Slide 4]  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║   IMAGE UPLOAD                                                               ║
║       │                                                                      ║
║       ├──► PHASE 1: STRUCTURAL VALIDATION                                   ║
║       │    file_validator.py ──► magic bytes · EOF analysis                 ║
║       │    ┌─────────────────────────────────────┐                          ║
║       │    │ polyglot_signature_detected?  ──► ⚠️ │  Hidden payload in file  ║
║       │    │ trailing_payload_after_eof?   ──► ⚠️ │  ZIP-in-JPEG etc.        ║
║       │    └─────────────────────────────────────┘                          ║
║       │                                                                      ║
║       ├──► PHASE 2: METADATA FORENSICS                                      ║
║       │    exif_analyzer.py ──► EXIF fields scanned                         ║
║       │    ┌─────────────────────────────────────┐                          ║
║       │    │ UserComment / ImageDescription       │  Injected instructions   ║
║       │    │ GPS inconsistency / date mismatch    │  Tampered metadata       ║
║       │    │ exif_text_injection ──► ⚠️            │  MITRE AML.T0051         ║
║       │    └─────────────────────────────────────┘                          ║
║       │                                                                      ║
║       ├──► PHASE 3: VISUAL ANALYSIS                                         ║
║       │    cv_pipeline.py + YOLOv8 ──► object detection                     ║
║       │    ocr_pipeline.py + Tesseract ──► text extraction                  ║
║       │    ┌─────────────────────────────────────────────────────┐          ║
║       │    │ payment_social_engineering? (PayID/BSB/IBAN)  ──► ⚠️│          ║
║       │    │ pci_card_exposed + Luhn valid?                ──► ⚠️│          ║
║       │    │ crypto_payment_uri? (bitcoin:ethereum:)       ──► ⚠️│          ║
║       │    │ ransomware_indicator? (encrypted/files_locked)──► ⚠️│          ║
║       │    │ homoglyph_injection? (NFKC unicode normalise) ──► ⚠️│          ║
║       │    │ encoded_payload? (base64/hex decode+reclassify──► ⚠️│          ║
║       │    └─────────────────────────────────────────────────────┘          ║
║       │                                                                      ║
║       └──► PHASE 4: QR CODE DEEP ANALYSIS                                   ║
║            barcode_decode.py (pyzbar + OpenCV multi-scale)                  ║
║            ┌─────────────────────────────────────────────────────┐          ║
║            │ qr_payload_wifi  ──► credential harvesting ──► ⚠️   │          ║
║            │ qr_payload_vcard ──► contact injection     ──► ⚠️   │          ║
║            │ qr_multi_mismatch──► label≠destination     ──► ⚠️   │          ║
║            │ redirect chain probe (gated: QR_REDIRECT_PROBE_ENABLED)        ║
║            └─────────────────────────────────────────────────────┘          ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**What to record:** Upload `dump/test-cv/macbook-QR.png` through the storefront CV complaint
flow. Show the security signals firing in the Decision Trace → Security Matrix tab.
Point out the MITRE technique, PASTA stage, and OWASP LLM category that appear.

---

### SLIDE 5 — AI Security Threat Matrix (50+ Permutations)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  AI SECURITY — Image Threat Detection Matrix (v2.0)               [Slide 5] ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  CATEGORY          PERMUTATIONS   KEY SIGNALS              MITRE TECHNIQUE  ║
║  ──────────────── ────────────── ─────────────────────── ─────────────────  ║
║  Financial Fraud    F1–F6         payment_social_eng.      AML.T0051        ║
║                                   pci_card_exposed         T1005            ║
║                                   crypto_payment_uri       AML.T0051        ║
║                                                                              ║
║  Ransomware         R1–R5         ransomware_indicator     T1486            ║
║                                   encoded_payload_det.     T1027            ║
║                                                                              ║
║  Data Exfiltration  D1–D6         qr_external_url          AML.T0048        ║
║                                   exif_text_injection      AML.T0051        ║
║                                   polyglot_suspected       AML.T0048        ║
║                                                                              ║
║  NLP Injection      N1–N5         ocr_prompt_injection     AML.T0051        ║
║                                   homoglyph_injection      AML.T0051        ║
║                                                                              ║
║  CV Attacks         CV1–CV5       adversarial detected     AML.T0043        ║
║                                   steg_suspicious          T1027            ║
║                                                                              ║
║  E-commerce         EC1–EC5       fake_review_pattern                       ║
║  Agentic Injection  A1–A5         tool_call_injection      AML.T0054        ║
║  Cross-modal        X1–X5         session_ocr_split_inj.                    ║
║                                                                              ║
║  ┌──────────────────────────────────────────────────────────────────┐        ║
║  │  THREAT SCORE PIPELINE  (per uploaded image)                     │        ║
║  │                                                                   │        ║
║  │  Signals → DREAD scorer → weighted_avg (0-10)                    │        ║
║  │         → PASTA stage (1-7, count-based thresholds)              │        ║
║  │         → STRIDE categories (Spoofing/Tampering/…)               │        ║
║  │         → OWASP LLM Top 10 (LLM01/LLM02/LLM05/LLM06)           │        ║
║  │         → Kill-chain phase (Recon/Delivery/Exfil/ActionsOnObj)   │        ║
║  └──────────────────────────────────────────────────────────────────┘        ║
║                                                                              ║
║  AML.T0051 triggered across 38 of 50+ permutations (MITRE ATLAS 2024)       ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**What to record:** Open `src/app/security/dread_scorer.py` and scroll through the signal
maps — point out that every signal has a MITRE, OWASP, and kill-chain entry. Then
open `framework_correlation.py` and show the `_pasta()` function. Narrate what PASTA
stage means in plain English ("Stage 6 means ransomware payload detected — the platform
automatically routes to human review and flags for incident response").

---

### SLIDE 6 — Compliance Engineering

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  COMPLIANCE ENGINEERING — AI Regulatory Framework Stack          [Slide 6]  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  EVERY TRIAGE DECISION EMITS STRUCTURED COMPLIANCE EVIDENCE                 ║
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │  SIGNAL DETECTED          │  FRAMEWORK MAPPING                      │    ║
║  │  ─────────────────────────┼─────────────────────────────────────── │    ║
║  │  payment_social_eng.      │  OWASP LLM01 (Prompt Injection)        │    ║
║  │  pci_card_exposed         │  OWASP LLM06 (Sensitive Info Disc.)    │    ║
║  │  crypto_payment_uri       │  OWASP LLM02 (Insecure Output)         │    ║
║  │  qr_payload_wifi          │  OWASP LLM05 (Supply Chain)            │    ║
║  │  exif_text_injection      │  MITRE ATLAS AML.T0051                 │    ║
║  │  ransomware_indicator     │  MITRE ATT&CK T1486 (Data Encrypted)   │    ║
║  │  polyglot_suspected       │  MITRE ATLAS AML.T0048                 │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                                                              ║
║  REGULATORY FRAMEWORKS ADDRESSED                                             ║
║  ┌────────────────────┬──────────────────────────────────────────────┐      ║
║  │  NIST AI RMF       │  GOVERN · MAP · MEASURE · MANAGE            │      ║
║  │  ISO 42001:2023    │  AI management system standard               │      ║
║  │  EU AI Act 2024    │  High-risk system transparency obligations   │      ║
║  │  AU Privacy Act    │  Sensitive data handling in image pipelines  │      ║
║  │  GDPR              │  PII in EXIF / OCR data processing           │      ║
║  └────────────────────┴──────────────────────────────────────────────┘      ║
║                                                                              ║
║  SHIFT-LEFT SECURITY                                                         ║
║  Threats modelled BEFORE build:                                              ║
║  STRIDE threat model ──► design review ──► signal definitions               ║
║  ──► DREAD weight calibration ──► PASTA staging thresholds                  ║
║  ──► automated test coverage (tests/security/, tests/cv/)                   ║
║                                                                              ║
║  Observable: Splunk HEC · structured telemetry · security event emission    ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**What to record:** Show `SHOPSQUIRE_COMPLIANCE_AND_SHIFT_LEFT_SECURITY.md` open (table of
contents), then switch to `dread_scorer.py` signal maps. Narrate: "Every signal that
fires during image triage is automatically tagged with its OWASP LLM category, MITRE
ATLAS technique, and kill-chain phase — this is the audit evidence a compliance team
needs without any manual tagging."

---

### SLIDE 7 — Bitemporal Decision Trace

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  BITEMPORAL DECISION TRACE — Immutable AI Audit Trail            [Slide 7]  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  PROBLEM: "What did the AI recommend to user X at 14:03 on March 10?"       ║
║  SOLUTION: Bitemporal storage — two independent time axes                   ║
║                                                                              ║
║  ┌──────────────────────────────────────────────────────────────────┐        ║
║  │  valid_time   = when this decision was TRUE in the real world    │        ║
║  │  system_time  = when this record was written to the database     │        ║
║  │                                                                   │        ║
║  │  valid_from  ─────────────────────────────────────► valid_to     │        ║
║  │      │  query issued               product removed from catalog  │        ║
║  │      │                                                            │        ║
║  │  system_from ─────────────────────────────────────► system_to    │        ║
║  │      │  record committed                 record corrected        │        ║
║  └──────────────────────────────────────────────────────────────────┘        ║
║                                                                              ║
║  WHAT THIS ENABLES                                                           ║
║  ┌────────────────────────────────────────────────────────────────┐          ║
║  │  Regulator audit   → exact state at any past timestamp         │          ║
║  │  Warranty dispute  → original triage result unchanged          │          ║
║  │  ML training       → what did we recommend vs what was bought  │          ║
║  │  Fraud rewind      → replay the full decision chain            │          ║
║  └────────────────────────────────────────────────────────────────┘          ║
║                                                                              ║
║  DECISION TRACE EVENT TYPES (Timeline tab in UI)                             ║
║  ┌────────────────────────────────────────────────────────────────┐          ║
║  │  session_start · intent_extracted · nqe_question_proposed      │          ║
║  │  recommendation_result · cv_triage_started · cv_signal_fired   │          ║
║  │  security_score_computed · escalation_triggered · resolved     │          ║
║  └────────────────────────────────────────────────────────────────┘          ║
║                                                                              ║
║  Schema: db/migrations/0001_add_decision_trace_events.sql                    ║
║  Model:  src/app/models/decision_trace_events.py                             ║
║  Router: src/app/routers/decision_trace_events.py                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**What to record:** Open the Decision Trace modal to the Timeline tab. Show an event row,
expand it, show the raw JSON payload with `valid_from` / `system_from` fields. Then open
`test_decision_bitemporal_query.py` and show the test that proves time-travel queries work.

---

### SLIDE 8 — E-commerce Agentic Loop (The Full Journey)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTIC E-COMMERCE LOOP — Guided Sell → Resolve                 [Slide 8]  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║   DAY 1 — SHOPPING                                                           ║
║   ─────────────────                                                          ║
║   User: "gaming laptop $800"                                                 ║
║       │                                                                      ║
║       ▼                                                                      ║
║   NQE clarifies → slots filled → use-case KB lookup                         ║
║   "AAA gaming needs RTX — $800 is tight. Show budget fit + perf fit?"       ║
║       │                                                                      ║
║       ▼                                                                      ║
║   ┌──────────────────────────┐  ┌──────────────────────────────────┐        ║
║   │ 💰 Budget fit            │  │ 🚀 Performance fit               │        ║
║   │ Lenovo Legion  $799      │  │ ASUS ROG Strix    $1,099         │        ║
║   │ [Add to Cart]            │  │ [Add to Cart]                    │        ║
║   └──────────────────────────┘  └──────────────────────────────────┘        ║
║       │                                                                      ║
║       ▼                                                                      ║
║   Cart → upsell → "Add protection plan $X" → Checkout                       ║
║                                                                              ║
║   DAY 90 — SUPPORT                                                           ║
║   ─────────────────                                                          ║
║   User: "screen cracked" + uploads cracked-mac.jpg                          ║
║       │                                                                      ║
║       ▼                                                                      ║
║   CV triage: damage_score 0.85 · screen_crack detected                      ║
║   Order lookup: purchase_date 2025-12-15 · warranty_months 12               ║
║   Warranty: ✅ eligible (9 months remaining)                                  ║
║       │                                                                      ║
║       ▼                                                                      ║
║   Security scan: no threats detected → human_review=True (accidental dmg)   ║
║       │                                                                      ║
║       ▼                                                                      ║
║   [Chat with Admin] → Escalation Room (WS/SSE live)                         ║
║   Staff: "Was this accidental or manufacturing defect?"                      ║
║   Resolved: replacement authorised                                           ║
║       │                                                                      ║
║       ▼                                                                      ║
║   FULL TRACE: Day 1 recommendation + Day 90 triage + resolution             ║
║               → one immutable bitemporal record                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**What to record:** Walk through the full demo script from NEXT_SPRINT_ROADMAP.md Sprint 1.
This is your hero demo — start recording at "My MacBook screen is cracked" and run to
the Escalation Room opening. No narration needed if the UI is clear; add it as a voiceover.

---

## LinkedIn Post Copy — 7 Angles

Paste these as-is or adapt them. Keep posts under 1,300 characters (LinkedIn sweet spot).
Hook line goes in the first 2 lines (before "See more" fold).

---

### POST 1 — Agentic Architecture

```
I built an AI agent pipeline for ecommerce from scratch (well, mostly from scratch 😅).

Here's what the architecture looks like:

→ Chat query hits an Intent Agent (PEG-style parser, semantic slot fill)
→ NQE Agent fires 1-2 clarifying questions based on missing slots
→ Ranking Agent uses a GNN to rerank products + explain WHY
→ 3-tier Episodic Memory (working / session / long-term) persists context
→ Every decision gets written to a bitemporal trace (immutable audit trail)

For image uploads, a parallel CV pipeline runs:
→ File validator (polyglot / magic byte analysis)
→ EXIF forensics
→ OCR + 50+ threat pattern matching
→ Security scoring (DREAD) → PASTA staging → MITRE ATLAS tagging

The hardest part wasn't the ML. It was wiring the bitemporal trace so
every recommendation is reconstructible at any past timestamp for compliance audits.

Built this as a learning project. The codebase is real.
What questions do you have about agentic architecture?

#AgenticAI #AIEngineering #SystemDesign #MachineLearning
```

---

### POST 2 — NLP / NQE

```
Most AI product recommenders skip the most important step: asking the right follow-up question.

I built a Natural Query Engine (NQE) that knows when to ask and what to ask.

The logic:
→ Parse the query for budget, brand, specs, use-case (PEG parser + semantic slots)
→ Check: is_open_ended? (budget missing, or intent confidence < threshold)
→ If yes — build a question plan from category templates (laptop, TV, phone, tablet...)
→ Filter to max 2 questions, prioritised by which slot has highest value missing
→ Merge answer back into session context, re-score products

Example:
User: "gaming laptop around $800"
NQE: "Which games? (casual like Minecraft or AAA like Cyberpunk?)"
User: "Cyberpunk"
System: ⚠️ AAA gaming needs RTX — $800 is tight. Here are budget-fit vs perf-fit options.

The ⚠️ note is the real product insight. Showing "here's what you can afford"
AND "here's what you actually need" is more honest than just returning filtered results.

That's the difference between a recommender and an advisor.

#NLP #MachineLearning #ProductEngineering #AIEngineer
```

---

### POST 3 — Computer Vision + OCR Security

```
Your ecommerce platform probably doesn't scan uploaded images for payment fraud. Mine does.

When a user uploads a support photo, ShopSquire runs:

1. Magic byte + EOF analysis — detect polyglot files (ZIP hidden inside JPEG)
2. EXIF forensics — scan UserComment/ImageDescription for injected instructions
3. OCR text extraction — then immediately check for:
   → PayID / BSB / IBAN / SWIFT text (payment social engineering)
   → Card numbers — regex + Luhn algorithm validation
   → Crypto URIs (bitcoin:, ethereum:, monero:)
   → Ransomware keywords (encrypted, files_locked, pay_within, btc_wallet)
   → Base64/hex encoded payloads — decoded and re-classified
   → Homoglyph injection (NFKC unicode normalisation)
4. QR decode — classify payload type (vCard, Wi-Fi credentials, URL)
   → optionally probe redirect chain (sandboxed, 3 hops max)

Every signal maps to MITRE ATLAS, OWASP LLM Top 10, PASTA stage, and kill-chain phase.

The bug that started this: OCR text was never passed to the NLP threat rules engine.
PayID text in an image was invisible to the security pipeline.

Finding that required tracing the data flow from image upload through to signal aggregation.

#CyberSecurity #ComputerVision #OCR #AIMLSecurity #MITRE
```

---

### POST 4 — AI Security / Threat Matrix

```
I built a 50+ permutation threat matrix for image-based AI attacks. Here's what I found.

Most ecommerce AI pipelines have zero defences against:

→ Payment social engineering in uploaded images (PayID, Venmo text visible in photo)
→ PCI card numbers in screenshots (even partial — check with Luhn)
→ QR codes that deliver Wi-Fi credential harvesting payloads
→ EXIF fields used to inject prompt instructions into the AI
→ Polyglot files — a valid JPEG that's also a valid ZIP with a malicious payload inside
→ Unicode homoglyphs — text that looks normal but isn't after NFKC normalisation

The attack categories I modelled:
Financial fraud · Ransomware · Data exfiltration · NLP injection
CV attacks · E-commerce fraud · Agentic tool injection · Cross-modal attacks

Every detected signal is scored with DREAD, staged through PASTA,
tagged with MITRE ATLAS technique and OWASP LLM Top 10 category.

The most common MITRE technique across 38 of 50+ permutations: AML.T0051.

This is the layer almost no one builds. And it's the layer that matters most
when your AI system processes user-uploaded content at scale.

#AISecurity #ThreatModelling #MITREATLAST #OWASP #CyberSecurity
```

---

### POST 5 — Compliance Engineering

```
Compliance isn't a checkbox you add after the build. It's a data schema decision you make at the start.

Building ShopSquire taught me this the hard way.

Every AI decision on the platform now emits structured compliance evidence:

→ OWASP LLM Top 10 category (which of 10 AI risk classes does this signal fall under?)
→ MITRE ATLAS technique (which adversarial ML attack pattern?)
→ PASTA stage (1-7: how far through the attack lifecycle is this threat?)
→ STRIDE category (Spoofing / Tampering / Repudiation / Info Disclosure / DoS / EoP)
→ Kill-chain phase (Reconnaissance → Delivery → Exploitation → Actions on Objectives)

Regulatory frameworks addressed:
NIST AI RMF · ISO 42001:2023 · EU AI Act · AU Privacy Act · GDPR

The question I kept asking myself:
"If a regulator asked for evidence that we detected and responded to this threat —
would the data already be there, or would we need to go build it?"

If you have to go build it after the fact, you've already failed the audit.

Shift-left means the threat model runs before the code, not after the incident.

#Compliance #AIGovernance #NeuralAI #NISTAI #GDPR #EUAIAct
```

---

### POST 6 — Bitemporal Decision Trace

```
Most AI systems can't answer this question: "What exactly did you recommend 90 days ago?"

ShopSquire can. Here's how.

Standard databases use one time axis (when the record was written).
Bitemporal databases use two:
→ valid_time: when this decision was true in the real world
→ system_time: when the record was committed to the database

Why it matters for AI:
→ Product removed from catalogue? The original recommendation still shows what was valid then.
→ Warranty dispute 6 months later? The triage result is unchanged and reconstructible.
→ Regulatory audit? Exact AI state at any past timestamp — immutable, queryable.
→ ML team needs training data? "What did we recommend vs what was bought" without leakage.

Every event on the platform — intent extraction, NQE questions, product ranking,
CV triage signals, security scores, escalation — is written to this bitemporal trace.

The Decision Trace modal in the UI lets you time-travel to any point in a session.

Only a handful of financial institutions do this for their AI systems.
I think every AI product that touches user decisions should.

#DataEngineering #BiTemporalData #AIAudit #Compliance #DataArchitecture
```

---

### POST 7 — The Full Loop (Hero Post — most shareable)

```
The full AI commerce loop, from "I need a laptop" to "my screen cracked" — in one trace.

DAY 1:
User: "gaming laptop, budget $800"
→ NQE asks: "Which games?" → "Cyberpunk"
→ ⚠️ AAA gaming needs RTX — $800 is tight
→ Shows: budget fit option ($799) + performance fit option ($1,099)
→ User buys Lenovo Legion. Cart adds extended warranty suggestion.

DAY 90:
User: "my screen cracked" + uploads photo
→ CV pipeline: damage_score 0.85, screen_crack detected
→ Security scan: no fraud signals (clean image)
→ Order lookup: purchased Dec 2025, 12-month warranty
→ Warranty: ✅ 9 months remaining
→ Routing: human_review=True (accidental damage needs policy decision)

→ Escalation Room opens (WebSocket → SSE → poll fallback)
→ Staff: "Was this accidental or manufacturing defect?"
→ Resolved: replacement authorised

THE TRACE:
Both sessions — Day 1 recommendation AND Day 90 triage + resolution —
sit in the same immutable bitemporal audit record.

A regulator, a fraud team, or a warranty insurer can replay the entire decision chain.

That's the product I built. What would you add to it?

#AIEngineer #ProductEngineering #AgenticAI #Ecommerce #MachineLearning
```

---

## Video Recording Guide

### Tools (free, Windows)
- **OBS Studio** — full screen/window capture, add voiceover, export MP4
- **Windows Snipping Tool** (Win + Shift + S) — for static screenshots of code
- **ShareX** — for animated GIFs of the UI flowing (good for carousel slides)

### What to Record Per Angle

| Angle | What to show | Duration |
|---|---|---|
| Architecture | Split: VS Code file tree + browser Decision Trace | 60-90s |
| NLP/NQE | Type query → NQE question → products → WHY text | 45-60s |
| CV/OCR | Upload macbook-QR.png → show signals firing in Security Matrix | 60s |
| Security Matrix | Scroll dread_scorer.py signal maps + framework_correlation.py _pasta() | 90s |
| Compliance | Show _signal_to_atlas dict + OWASP maps + compliance doc | 60s |
| Bitemporal | Open Decision Trace Timeline tab → show raw event JSON | 45s |
| Full loop | Full demo from NEXT_SPRINT_ROADMAP — the hero narrative | 2-3 min |

### Format for LinkedIn
- Short clips (under 3 min) perform best
- Add captions (LinkedIn auto-generates but check them)
- Post as native video, not YouTube link (native gets 3-5× more reach)
- Carousel posts (5-8 images) also perform well — use the ASCII slides above as slide graphics

---

## What NOT to Claim

- Do not say "I wrote all the code myself" — say "I architected and directed this system"
- Do not claim you'd pass a LeetCode Hard screen without preparation
- Do not call it "production" unless you've validated with real users

What you CAN say with full confidence:
- "I designed the architecture"
- "I identified and fixed two specific production bugs in the security pipeline"
- "I built the threat matrix and mapped every signal to MITRE/OWASP/PASTA"
- "I wrote the product roadmap and prioritised by business impact"

Those are all true and all verifiable from the codebase.

---
_LinkedIn Showcase Guide — ShopSquire — March 2026_
