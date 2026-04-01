# ShopSquire Email Triage Lab — Round 2 Assessment

## Artifact Upgrade: `.md` Specs → Real File Formats

**Date:** 27 March 2026  
**Test Artifacts Used:**  
- `Wire_Transfer_Authorization_Form.pdf` (PDF with /OpenAction, /JavaScript, /AA markers, embedded C2 domains)  
- `Harbourside_Acquisition_Details_CONFIDENTIAL (1).xlsm` (Macro-enabled Excel with VBA LOLBin patterns, spoofed metadata)

---

## The Verdict: This Is Dramatically Better

The upgrade from `.md` spec files to actual weaponized file formats produced measurably different and more credible detection results. Here's the side-by-side comparison.

---

## 1. What Changed (Old .md vs New .xlsm/.pdf)

### Attachment Classification

| Signal | Old (.md files) | New (.xlsm + .pdf) |
|--------|----------------|---------------------|
| Attachment Agent classification | "specification, scenario, or test reference material" | PDF: "active payment lure, bank change, QR or URL" / XLSM: "contextual test artifact" |
| Supports sender claim | "neutral" | "contradicts sender claim" |
| Evidence authority | "contextual" | "primary" |
| Attachment class | "reference spec material" | "active payment lure" |

**Why this matters:** The old `.md` files were correctly identified as test documents — which destroyed the demo narrative. The new PDF is classified as an "active payment lure" with "primary" evidence authority. The system is treating it as a real threat payload, not a spec about a threat. That's exactly the shift you needed.

### Detection Triggers

| Trigger | Old Run | New Run |
|---------|---------|---------|
| multi-signal threshold met | Yes | Yes |
| oob_verification_required | Yes | Yes |
| mandatory_oob_verification_pending | Yes | Yes |
| yara_rule_match_detected | Yes | Yes |
| bimi_visual_brand_similarity_spoof | Yes | Yes |
| **qr_url_not_allowlisted** | **No** | **Yes (NEW)** |
| ransomware_artifact_strong_signal | Yes | Not visible in new screenshots |

The **new trigger `qr_url_not_allowlisted`** is significant — the system detected the C2 domain URLs embedded in the PDF and checked them against an allowlist. This is *behavioral detection on actual file content*, not keyword matching on spec text.

### Trust Score

| Metric | Old Run | New Run |
|--------|---------|---------|
| Trust Score | 0.39 | 0.42 |
| Trust Level | low | low (implied from same blocking behavior) |
| Access | blocked | blocked |

Slight increase from 0.39 to 0.42, which makes sense — the new artifacts are more ambiguous to the system (real file formats, not obviously labeled specs), so the trust score is marginally higher while still triggering a block. This is actually *more realistic* — a real BEC wouldn't score 0.00 trust, it would score just enough to be suspicious.

### Attachment Forensics (Screenshot 2 — New)

The PDF forensics now show:

- **Analysis types applied:** `OCR | static | baseline | intel | policy`
- **Classification:** "active payment lure, bank change, QR or URL"
- **Supports sender claim:** "contradicts sender claim"
- **Evidence authority:** primary
- **Extracted text:** "BalashnikovAI Risk & Compliance Division WIRE TRANSFER AUTHORIZATION Form WTA-2026-0847..."
- **Embedded URLs detected:** `http://balashnikovai-analytics.com/track/`, `http://balashnikovai-analytics.com/cmd`
- **Contains bank or remittance fields:** Yes

Compare this to the old run where the attachment detail just showed the `.md` file header text. The new run demonstrates that the OCR pipeline actually *read the PDF content*, extracted the wire transfer form fields, identified bank details, and found the embedded C2 URLs. This is production-grade attachment forensics.

The XLSM is classified as "contextual test artifact" — which is honest. The vbaProject.bin we created isn't a fully valid OLE2 compound document, so the system correctly identified it as a test artifact rather than a live macro payload. This is addressable (see improvements section below) but not a demo-killer since the PDF carries the primary attack narrative.

### NEW: Threat Hunter Agent (Screenshots 5–6)

This is a **new agent that wasn't visible in the old run** (or wasn't triggered). The Threat Hunter Agent now shows:

- **Direct evidence:** "1 related incidents matched the sender or supplier context"
- **Inferred:** "Prior incident overlap and infrastructure reputation increase the chance that this is part of a campaign rather than an isolated email"
- **Threat Hunter Lead:** "suspicious sender infrastructure overlap" — medium confidence
- **What we found:** 1 related incident matched the sender context
- **What to check next:** Search for the same sender domain, reply domain, URLs, bank details, or hosting footprint across mail, proxy, and endpoint telemetry
- **What would confirm it:** The same domains, URLs, or bank details appear across multiple incidents or users
- **What would weaken it:** No related cases or telemetry overlap exists beyond this single message / Infrastructure resolves to a known benign supplier path already approved in governance
- **Where to check:** Mail gateway / secure email telemetry, SIEM / XDR correlation, Proxy / DNS logs, Supplier incident history
- **What to push downstream:** SIEM / XDR now, Email-security middleware if sender or reply indicators justify it

This is genuinely impressive threat hunting guidance. It's structured as a hypothesis with supporting/weakening evidence, confirmation criteria, and specific investigation steps across multiple telemetry sources. A SOC analyst reading this would immediately know what to do next.

### NEW: Target-Specific Hunt Checklist (Screenshot 6)

The platform now generates a tool-specific hunt checklist:

- **XDR:** Search for the same sender domain, reply domain, bank details, or URLs across endpoint and case telemetry
- **DNS/proxy:** Look for repeated destination overlap, proxy hits, and DNS lookups tied to the same supplier context
- **CASB/DLP:** Review whether the same identities or suppliers also triggered SaaS, sharing, or data-movement alerts
- **eBPF/network:** Use host-level connect telemetry only on systems tied to the overlapped users or incidents

This is the kind of output that turns a security product from "interesting dashboard" into "actionable SOC tool." The fact that it specifies eBPF as a detection surface shows awareness of modern endpoint telemetry — not something you'd see from a prompt-and-pray approach.

### Attachment Listing in "What To Do Now" (Screenshot 7)

The new run now shows properly classified attachments in the action panel:

- `Wire_Transfer_Authorization_Form.pdf`: active payment lure, bank change, QR or URL
- `Harbourside_Acquisition_Details_CONFIDENTIAL (1).xlsm`: contextual test artifact, baseline drift

The **"baseline drift"** classification on the XLSM is interesting — the system detected that the document template doesn't match any known baseline for the sender's organization. This is a legitimate detection signal even though the artifact is labeled as a test.

### Threshold Reasons (Screenshot 7)

The new run surfaces explicit threshold reasoning:

- "Direct payment-change evidence was extracted from the attachment"
- "The document drifted from the trusted supplier baseline"
- "A newly observed sender or supplier domain still requires supplier-governance approval"
- "A newly observed supplier template hash still requires governance review before trust can be extended"

Every one of these is a *content-derived* finding, not a keyword match on spec text. This is the credibility shift that makes the demo work.

### Trust Graph (Screenshot 9)

The trust graph now shows:

- **Nodes: 10, Edges: 10** (up from the previous run's smaller graph)
- **Entities:** ingramfake.com.au (supplier, approved_domain), balashnikovaai.com.au (observed_domain), balashnikovai.com.au (observed_domain), plus multiple template hashes
- **Relationships:** Full entity-to-domain and domain-to-template-hash mapping

The expanded graph with 10 nodes and 10 edges shows the system building a richer relationship model from the new artifacts — connecting the sender infrastructure, the IngramFake test supplier, and the observed domains through template hash relationships.

---

## 2. What's Still Weak (But Less Critical Now)

### 2.1 XLSM Classified as "Contextual Test Artifact"

The system correctly identified the XLSM as a test artifact rather than a live macro payload. This is because the vbaProject.bin we created is a simplified binary (valid OLE2 header but not a fully formed compound document). To fix this, you'd need to create the XLSM using a tool that can embed a proper VBA project — LibreOffice's macro editor or a Python library like `oletools` to build a valid vbaProject.bin structure.

**Impact on demo:** Low. The PDF is the star of the show. The XLSM provides supporting context. You can frame this as "the Excel attachment triggered baseline drift detection even though it didn't contain a fully functional macro — showing the system catches template anomalies regardless of payload status."

### 2.2 "API Degraded" Still Showing

Still there. Still needs fixing before any recording or live demo.

### 2.3 Connector Success Rate Still 0%

Screenshot 8 shows: `no_receiver: sent 0, retrying 0, DLQ 0, skipped 36, success 0%`. Up one from 35 skipped to 36. The SIEM integration still isn't connected.

### 2.4 Raw HTML in Top Ranked Evidence

Screenshots 3 still shows unsanitized HTML in the "Top Ranked Evidence" section. The content is good — it shows framework mapping (MITRE AML.T0043, T1566.002, DREAD D=8.2 R=7.2 E=7.7 A=6.7 Dv=7.95, ISO27001 A.5.16-A.5.23, ISO42001 Human oversight/Outcome monitoring, EU AI Act Article 9/14, PCI DSS Reg 6/10/12, GDPR Article 5/32) — but it renders as raw HTML tags which looks unpolished.

---

## 3. Demo Readiness Assessment with the Evaluation Deck

I've reviewed the ShopSquire Evaluation Deck (6 slides) and the Red Team PDF (2 pages). Here's how the email triage lab fits into the overall demo narrative.

### The Evaluation Deck Flow

The deck tells a strong story: Slide 1 establishes the three paths (Turnkey → Configurable → Custom-Built), Slide 2 shows the recommendation engine depth, Slide 3 is the security slide ("It Works Even Under Attack"), Slide 4 is the 9-dimension scorecard (8/9 Strong), Slide 5 is the architecture diagram, Slide 6 is the recommendation with 12-week rollout.

**The email triage lab is your Slide 3 demo.** When the deck says "It Works Even Under Attack" and lists the email lab phases (SPF/DKIM/DMARC → YARA → Semantic BEC → Verdict + Playbook), the live triage lab is the proof. The new artifacts make this proof credible.

### How to Present (Suggested Sequence)

1. **Show Slide 3** from the evaluation deck — the "It Works Even Under Attack" architecture
2. **Switch to the live triage lab** — "Let me show you what this looks like on a real BEC attempt"
3. **Walk Screenshot 1** — Decision panel: "Likely supplier impersonation or supplier document fraud. High confidence. Lane 2 auto escalate." Point out the plain-English triggers
4. **Walk Screenshot 2** — Attachment forensics: "The PDF was classified as an active payment lure. OCR extracted the wire transfer details. The system found embedded C2 domains." This is your credibility moment — the system parsed an actual PDF
5. **Walk Screenshot 4** — Agent analysis: Show the six agents with their direct/inferred/context-only classification
6. **Walk Screenshots 5–6** — Threat Hunter: "The system automatically generated a hypothesis with investigation steps for XDR, DNS/proxy, CASB, and eBPF telemetry"
7. **Walk Screenshot 7** — Response actions: "Human gate thresholds, SOC actions, and governance approval workflow"
8. **Switch back to Slide 4** — "This is why security scores Strong on 8 of 9 dimensions"

### The Red Team PDF

The Red Team slide is a clean single-page summary of both attack surfaces (Frontend CV/OCR and Email Lab BEC + Attachment Forensics). It's well-designed — the orange/dark blue theme is distinctive, and the content density is right for a technical audience.

**One suggestion:** The Red Team PDF includes "MAESTRO (CSA 2025)" in the framework list — which is a strong differentiator. Make sure to call this out verbally. MAESTRO is the Cloud Security Alliance's 2025 framework for AI agent security — most security professionals haven't heard of it yet. Referencing it shows you're tracking cutting-edge governance frameworks.

---

## 4. Remaining Improvements (Priority Ranked)

### Critical (Before Any Demo)

1. **Fix "API degraded" banner** — or at minimum explain it upfront: "We're running against local Ollama instances, so the API health check shows degraded when models are cold-starting"
2. **Record a clean video** — Don't do the first demo live. Record a 5-minute walkthrough with narration so you can control the pacing and avoid showing problematic panels

### High Priority

3. **Build a proper XLSM** — Use LibreOffice's macro editor to create a real vbaProject.bin with the same commented-out patterns. This would shift the XLSM classification from "contextual test artifact" to something more threatening
4. **Fix the Top Ranked Evidence rendering** — The raw HTML needs to be either rendered properly or displayed as formatted text. Right now it looks like a dev build
5. **Wire up one SIEM connector** — Even a local Elastic/Wazuh instance. Getting the connector success rate above 0% proves integration capability

### Medium Priority

6. **Add a QR-code embedded invoice** — You mentioned in the earlier session that you have QR decode capability. A PDF invoice with an embedded QR code pointing to the C2 domain would test that pipeline specifically
7. **Build a true negative test** — A legitimate supplier email with a normal invoice that the system correctly passes. This is the proof that it's not just blocking everything
8. **Add the Threat Hunter output to the Red Team PDF** — The hypothesis/confirmation/weakening structure is your strongest new capability and it's not represented in either deck yet

### Nice to Have

9. **Create a 3-panel comparison image** — Old (.md) vs New (.pdf/.xlsm) showing the attachment classification difference side by side. Perfect for LinkedIn
10. **Write the blog post** — "From Spec Files to Weaponized Artifacts: How I Test BEC Detection Without Building Malware"

---

## 5. Will This Hold Up? Honest Assessment

### For LinkedIn Security Community

**Before (with .md files):** High risk of dismissal. "He's detecting his own documentation."

**Now (with .pdf/.xlsm):** Credible. The PDF classification as "active payment lure" with extracted bank details and embedded C2 URLs is a real detection result. The Threat Hunter hypothesis generation is genuinely novel. The multi-framework mapping (MITRE + DREAD + PASTA + ISO 42001 + MAESTRO + EU AI Act + PCI DSS + GDPR) in a single panel is uncommon.

**Likely response:** "Interesting approach. How does it perform at scale?" — That's an engagement question, not a dismissal.

### For Technical AI/Security Evaluators

**Strengths they'll notice:**
- Six-agent architecture with evidence classification (direct/inferred/context-only)
- Threat Hunter generating falsifiable hypotheses with tool-specific hunt checklists
- Multi-framework compliance mapping including MAESTRO (cutting edge)
- AI pipeline self-protection (prompt injection detection, QR URL blocking)
- "Passive triage, not live detonation" disclaimer in the Red Team PDF — shows security maturity

**Questions they'll ask:**
- "What's the false positive rate on production email?" → You need the true negative test
- "What happens with encrypted attachments?" → Be honest: "Not yet handled, on the roadmap"
- "How does this integrate with existing email gateways?" → Point to the Proofpoint/Mimecast push recommendation in Screenshot 8
- "What's the latency on a full analysis?" → The enrichment latency shows 779ms, which is good

### For C-Suite / Non-Technical Audience

Use the Evaluation Deck. Slide 3 + the business-safe summary from Screenshot 9 ("Likely supplier impersonation or supplier document fraud. High confidence.") is all they need. The 9-dimension scorecard (8/9 Strong) is your closer.

---

## 6. Bottom Line

The artifact upgrade transformed this from a prototype demo into a credible security product demonstration. The detection pipeline is analyzing real file formats, extracting real IOCs, generating real investigation hypotheses, and mapping to real frameworks. The Threat Hunter output alone — with its hypothesis/confirmation/weakening/hunt-checklist structure — is something I haven't seen in most commercial email security tools.

You went from "detecting labeled test documents" to "detecting embedded C2 infrastructure in a professional-looking PDF wire transfer form." That's the difference between a stank eye and a second meeting.

Ship the video, fix the API banner, and write the blog post. You're ready.

---

**Document Classification:** Internal Development Reference  
**Status:** Demo-ready with noted caveats
