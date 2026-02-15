# Merchant Ops UI (Wireframes + Ports)

Date: 2026-02-15

This document captures the intended merchant/admin UI layout for:
1. Merchant BI dashboard (charts)
2. Human escalation console (incident room)
3. Email security triage lab (compose + attachments + escalation)

Color direction: match storefront theme (navy/blue + white + orange accents).

## Ports / URLs (Local Demo)

Buyer storefront (Vite):
- `http://127.0.0.1:5173/`

API (Docker):
- `http://127.0.0.1:8080/health`

Merchant Ops (served by API as static SPA):
- Entry: `http://127.0.0.1:8080/merchant/dashboard`
  - Deep-link: `http://127.0.0.1:8080/merchant/app/index.html?tab=merchant-bi`
- Escalations: `http://127.0.0.1:8080/merchant/incident-room`
  - Deep-link: `http://127.0.0.1:8080/merchant/app/index.html?tab=escalations`

Legacy demo pages (should not be used for the recording):
- Suggested FAQs stub: `http://127.0.0.1:8080/merchant/dashboard-faq`
- Lite incident room: `http://127.0.0.1:8080/merchant/incident-room-lite`

Admin React (dev server; optional):
- `http://127.0.0.1:3001/`

## 1) Merchant BI Dashboard (Charts)

Goal: page 1 should immediately show proof the platform works:
- Jan/Feb transaction history (daily + monthly)
- Security event history (daily + monthly)
- Breakdown by security type (NLP/CV/Email/Supply-chain/Network/Endpoint/etc.)
- Upsell performance (CTR / conversion) if available

Wireframe (desktop):

┌──────────────────────────────────────────────────────────────────────────────┐
│ ShopSquire | Merchant Ops                               API: ● Healthy       │
│ Tabs:  [BI] [Escalations] [Email] [Inventory] [Settings]                     │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ BI Dashboard                                                                  │
│ Range: ( Jan–Feb 2026 ▾ )  Granularity: ( Daily ▾ )  [Refresh]               │
│                                                                              │
│ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐     │
│ │ Revenue       │ │ Orders        │ │ Refund rate    │ │ Chargebacks   │     │
│ │ $1,234,567    │ │ 1,765         │ │ 2.3%           │ │ 0.6%          │     │
│ └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘     │
│                                                                              │
│ ┌───────────────────────────────┐  ┌──────────────────────────────────────┐ │
│ │ Transactions over time         │  │ Security events over time            │ │
│ │ (line chart)                   │  │ (line chart)                         │ │
│ └───────────────────────────────┘  └──────────────────────────────────────┘ │
│                                                                              │
│ ┌───────────────────────────────┐  ┌──────────────────────────────────────┐ │
│ │ Security by type               │  │ Top signals / reasons                │ │
│ │ (stacked bars)                 │  │ (table: signal, count, severity)     │ │
│ └───────────────────────────────┘  └──────────────────────────────────────┘ │
│                                                                              │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ Upsell performance (optional)                                             │ │
│ │ (CTR / conversion / top SKUs)                                             │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘

Notes:
- “API: Healthy/Down” in header should be a simple `/health` ping indicator.
- Default range should be Jan–Feb (for demo) with “Last 7 days” as a quick toggle.

## 2) Escalations Console (Human-to-Human Incident Room)

Goal: operator-friendly workflow:
- Left: queue with clear states (Active, Pending, Done)
- Middle: chat thread with buyer + assistant + staff
- Right: context bundle (summary + evidence + decision trace links + playbook)
- Message input at bottom of chat panel (familiar UX)

Wireframe (desktop):

┌──────────────────────────────────────────────────────────────────────────────┐
│ ShopSquire | Merchant Ops                               API: ● Healthy       │
│ Tabs:  [BI] [Escalations] [Email] [Inventory] [Settings]                     │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Escalations                                                                   │
│ Filters: Status ( Active ▾ ) Severity ( All ▾ ) Channel ( All ▾ ) [Refresh]  │
└──────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────┬───────────────────────────────┬─────────────┐
│ LEFT: Queue                   │ MIDDLE: Chat                  │ RIGHT: Context│
│                               │                               │              │
│ [Active] [Pending] [Done]     │ Incident: #abc123  Sev: High  │ Summary      │
│ Search: [______________]      │ Buyer: demo-user-1             │ - what happened
│                               │                               │ - why flagged
│ ○ Inc #...  CV Refund         │ ┌───────────────────────────┐ │ - recommended
│   Sev: High  Status: Active   │ │ assistant: ...             │ │              │
│ ○ Inc #...  Email BEC         │ │ buyer: ...                 │ │ Evidence     │
│   Sev: Warn  Status: Pending  │ │ staff: ...                 │ │ - uploaded imgs
│ ○ Inc #...  NLP PCI attempt   │ │ ...                         │ │ - extracted OCR/QR
│   Sev: High  Status: Done     │ └───────────────────────────┘ │ - key tags
│                               │ [input box............................][Send]│
│                               │                               │ Links        │
│                               │                               │ - Decision Trace
│                               │                               │ - Security Matrix
│                               │                               │ - Playbook run
│                               │                               │ Actions      │
│                               │                               │ [Mark Triaged]
│                               │                               │ [Mark Resolved]
└───────────────────────────────┴───────────────────────────────┴─────────────┘

Queue statuses:
- Active: needs human attention now
- Pending: waiting on buyer re-upload / waiting on supplier verification / waiting on other system
- Done: resolved/closed (still searchable)

Context panel content (minimum viable):
- Incident metadata: id, created_at, severity, status, channel (cv/email/nlp)
- “Evidence rail”: thumbnails (CV images), attachment list (Email)
- “Security note to buyer” preview (non-scary language)
- Decision trace link (opens trace by id)
- MITRE/OWASP/DREAD/PASTA details are visible here (staff only), not shown to buyer

## 3) Email Security Triage Lab (Simulated Inbox + Compose)

Goal: allow safe demo testing without real email infrastructure:
- Compose email (to/subject/body)
- Attach files (PDF/PNG/JPG/EML/TXT)
- Platform extracts: URLs, QR codes, homoglyph/unicode tricks, bank details change request patterns
- Output:
  - if suspicious: auto-escalate to human queue + show “needs verification” note
  - if benign: allow + log evidence

Wireframe:

┌──────────────────────────────────────────────────────────────────────────────┐
│ Tabs: [BI] [Escalations] [Email] ...                                         │
└──────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────┬──────────────────────────────────────────────┐
│ LEFT: Inbox (simulated)       │ RIGHT: Viewer / Composer                      │
│                               │                                              │
│ [New Email]                   │ To:      [____________________]               │
│ Search: [______________]      │ Subject: [____________________]               │
│                               │ Body:                                         │
│ ○ Supplier invoice (Warn)     │ [ multiline textbox........................ ] │
│ ○ Bank details update (High)  │                                              │
│ ○ Shipping delay notice (Info)│ Attachments: [Add files]  (list w/ hashes)    │
│                               │ [Analyze] [Submit & Escalate]                 │
│                               │                                              │
│                               │ Analysis Summary (staff view):                │
│                               │ - Verdict: suspicious / benign                │
│                               │ - Reasons: ...                                │
│                               │ - Extracted: URLs / QR payload / entities     │
│                               │ - Suggested action: verify out-of-band        │
└───────────────────────────────┴──────────────────────────────────────────────┘

Important: “malicious-like attachments” in this lab should be NON-executable demos:
- PDF with a fake “bank account change” request
- Image with QR code pointing to a benign placeholder URL
- Text containing lookalike domains/homoglyphs
- EML samples (no execution) that the pipeline parses as plain text + headers

Escalation behavior:
- If a bank/payment change request is detected: auto-create incident, mark as Pending, require human verification.
- Buyer-facing response should be non-technical: “We can’t confirm payment changes via email attachments. A team member will verify with the supplier using a trusted contact method.”

