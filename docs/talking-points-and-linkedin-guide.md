# ShopSquire — Talking Points, Story Arc & LinkedIn Video Guide
> _For interviews, demos, and LinkedIn content. March 2026._

---

## THE ONE-SENTENCE PITCH

> **"I built an agentic AI ecommerce platform where the AI itself is treated as an untrusted actor — and every agent decision is detected, isolated, scored, and explained to a human in under 2 seconds."**

---

## THE CORE THESIS (say this first, every time)

> **"If an agent CAN do something — treat it as already compromised."**

This is **Zero Trust applied to autonomous AI agents**.

In classic Zero Trust: *never trust a user, always verify.*
In agentic AI: *never trust the agent's action, always verify the intent.*

The capability boundary of an agent IS its attack surface.

Maps directly to:
- **MAESTRO SC-04B** (CSA 2025) — every tool call validated before execution
- **OWASP Agentic AI Top 10 #1** — Unsafe Agent Actions beyond designed scope
- **MITRE ATLAS AML.T0051** — Prompt injection → unauthorized tool invocation

---

## THE THREE-PART STORY ARC

Tell it in this order. Every time.

```
1. DETECT   — the security matrix catches the deviation
2. INFORM   — the human gets context, not a raw log
3. ADAPT    — the agents get smarter from what was found
```

---

## TALKING POINTS — FRONTEND (NLP + CV/OCR)

### Opening hook
> "Every ecommerce platform lets buyers upload images.
>  A product for return. A screenshot of a warranty.
>  Nobody asks: what if the image is a weapon?"

### The attack surface nobody talks about
- A buyer uploads a laptop photo. It has a QR code embedding a phishing URL.
  The pixel LSBs carry a steganographic C2 payload.
  The product name is overlaid with OCR-extractable text.
- Traditional platform: image stored, thumbnail generated, zero inspection.
- ShopSquire: **6 parallel analysis tasks fire on that image the moment it arrives.**

### Why parallel architecture matters
> "Sequential pipelines have a fatal flaw: if stage 1 clears the image, stage 2 never runs.
>  We fire all six simultaneously.
>  A disagreement between agents is itself a signal."

- QR scanner clears → steg detector flags = **sophisticated adversarial image**
  (not naive malware — an attacker who knew to avoid simple signatures)
- **Agent disagreement → elevated DREAD score automatically**

### What CV/OCR does that nobody expects
> "OCR doesn't just find threats. It makes the recommendation engine smarter.
>  Brand from QR → anchors the product shortlist.
>  Specs from text overlay → become search constraints.
>  Steg hypothesis → becomes the 27th fraud signal.
>  Same pipeline, two masters, simultaneously."

### The buyer never feels it
> "The buyer got recommendations in 1.4 seconds.
>  The attacker got a DREAD-11 event, MITRE tag AML.T0048,
>  kill-chain stage 'Delivery', and an auto-selected playbook.
>  Both things happened. In parallel. In the same HTTP request."

---

## TALKING POINTS — EMAIL SECURITY LAB (BEC + Attachment Forensics)

### The scale hook
> "BEC — Business Email Compromise — is the most expensive cybercrime category
>  every single year. $4.5 billion in 2023. FBI IC3 report. Every year.
>  It almost always enters through a legitimate-looking supplier email."

### The 4-phase pipeline mirrors how a senior SOC analyst thinks
> "We built the pipeline the way a senior threat analyst works."

| Phase | What it does | Why it's in that order |
|---|---|---|
| Phase 1 | SPF / DKIM / DMARC / header forensics | Deterministic. No ambiguity. Provable. |
| Phase 2 | YARA (15 rules): LOLBin, ransom, QR redirect | Known-bad signatures — fast, cheap |
| Phase 3 | Semantic BEC — embedding similarity to intent seeds | Catches what signatures miss |
| Phase 4 | Verdict + playbook auto-selected | Structured evidence card, not just allow/block |

> "The machine does all four phases in under 500ms."

**Pause on Phase 3** — this is the differentiator:
- Embedding similarity against intent seeds: "payment redirect", "urgency pressure", "out-of-band bypass"
- Catches BEC that passes all header checks and has no YARA match
- This is what a human analyst does by feel — we made it measurable

### Attachment forensics — same engine, different surface
> "That PDF invoice. We run the same LSB chi-square that caught the image upload.
>  We check the PDF producer field against known CVEs.
>  We hash the invoice layout and check for template reuse —
>  the same spoofed template used across different campaigns, different text, same structure."

- Layout hash catches repeat-campaign attacks that YARA misses
- PDF producer CVE: CISA KEV CVE-2025-54236 — Magento SessionReaper, CVSS 9.1, 250+ stores overnight

### What the human actually receives
> "The operator doesn't get a log.
>  They get: severity badge, verdict, the exact sentence that triggered the BEC flag,
>  the MITRE kill-chain stage, and a playbook already selected.
>  Their job is to agree or override — not to investigate from scratch."

---

## THE CORE THESIS IN PRACTICE

### DETECT — behavioral deviation, not just input validation
> "We don't just watch what comes IN.
>  We watch what agents DO.
>  The Security_Observer_Agent watches the other agents."

- If the Recommendation Agent calls a tool outside its scope: flagged, DREAD-scored, security matrix event
- MAESTRO SC-04B: tool call validated against allowlist **before** execution — not after
- Tool_Intent_Gate + Policy_Gate = two enforcement layers on every LLM output

### ISOLATE — scope is blast radius control
> "Each agent has a defined permission surface.
>  CV_Label_Agent can read images and write to the security matrix.
>  It cannot write to the product catalog. It cannot call external APIs.
>  Capability = attack surface. Constrain capability, constrain blast radius."

- Least-privilege per agent — enforced at runtime, not just by convention
- Even if an LLM is prompted to go outside scope, the gate blocks execution

### INFORM — context, not noise
> "When compromise is detected, the human doesn't get 'agent behaved unexpectedly'.
>  They get: which agent, what it tried to do, what it was permitted to do,
>  what data it touched, DREAD score, MITRE ATLAS tag, recommended playbook.
>  The investigation is already done."

- Decision Trace: what the agent saw → decided → did → what was blocked
- Bitemporal audit: replay the exact agent context at the moment of anomaly
  Not a summary. The actual state.

### ASSESS — damage, risk, likelihood
> "Damage assessment is three questions:
>  What did the agent access? What did it write or transmit?
>  What would have happened if the gate hadn't caught it?
>  DREAD answers those quantitatively."

| DREAD dimension | What it measures |
|---|---|
| Damage | How bad is the worst case if exploited |
| Reproducibility | How easily can an attacker repeat this |
| Exploitability | How much skill/effort is required |
| Affected users | How many users/records at risk |
| Discoverability | How easy is it to find this vulnerability |

- Kill-chain stage = **where in the attack are we**
- PASTA stage = **what is the attacker trying to achieve**
- Bitemporal trace = **what did the agent know at the time** (passive observation vs active modification)

---

## THE POSITIONING LINE (for interviews)

> "Most platforms ask: did this input look safe?
>  I ask: what did every agent believe, what did it try to do,
>  and what was the blast radius if we were wrong?
>  The answer to all three is logged, MITRE-tagged, and replayable forever.
>  That's AI security orchestration — not just threat detection."

**For a hiring panel:**
> "I didn't just build security features.
>  I built a security posture for a system where the AI itself is an untrusted actor."

That's the mindset gap between someone who implements security and someone who designs secure agentic systems.

---

## HOW TO ARTICULATE IT — DELIVERY NOTES

### Pace and pausing
- **Slow down on the thesis line.** "If an agent CAN do something — *[pause]* — treat it as already compromised." Let the pause do the work.
- **Name the framework, then explain it** — don't explain it then name it. "MAESTRO SC-04B — every tool call validated before execution" lands better than explaining the concept and then saying "that's called MAESTRO".
- **Use contrasts.** "Traditional: block or allow. Us: serve the buyer AND trace the attacker. In parallel."

### What to emphasise for different audiences

| Audience | Lead with | Key line |
|---|---|---|
| CTO / Architect | Parallel agent architecture, blast radius | "Capability = attack surface. Constrain capability, constrain blast radius." |
| CISO / Security | MAESTRO + MITRE ATLAS + bitemporal audit | "Tamper-evident. Legally defensible. Replayable in court." |
| SOC Analyst | Security matrix, triage card, playbook | "The investigation is already done. Your job is to agree or override." |
| Hiring Panel | The thesis + your design decisions | "I treated the AI as an untrusted actor. Here's how I enforced that." |
| CMO / Business | Revenue protected, no friction, escalate not block | "Security doesn't cost you sales. We escalate instead of block." |

### Phrases that land
- "Same engine. Different surface." ← for any time you show frontend vs email
- "Two things happened simultaneously." ← when showing split reco + security matrix
- "The investigation is already done." ← for the triage card / explainability
- "Not a chatbot. 26 agents. 160 services. In parallel." ← for architecture depth
- "We sit between Shopify and CrowdStrike. We make both smarter." ← for positioning

### Phrases to avoid
- "It detects threats" — too vague
- "AI-powered security" — meaningless
- "The system automatically…" — use agent names instead: "The Steg_Detector fires..."
- Over-explaining steg math in a demo — say "statistical fingerprint" and move on

---

## LINKEDIN VIDEO GUIDE

### What to record (in order)

---

#### VIDEO 1 — The Thesis (60–90 seconds, talking head)
**What to say:**
> "Here's a principle I built a platform around:
>  If an AI agent CAN do something — treat it as already compromised.
>  That's Zero Trust applied to autonomous AI.
>  The capability boundary of each agent is its attack surface.
>  In ShopSquire, every agent has a defined permission surface.
>  Every tool call is validated before execution.
>  Every decision is logged with a DREAD score and a MITRE tag.
>  The agent can't just do things. It has to earn the right to act.
>  That's agentic AI security orchestration."

**How to record:** Talking head, no screen. Short. Confident. One camera angle.
**Hook for caption:** "Zero Trust for AI agents — if it CAN do it, assume it's compromised."

---

#### VIDEO 2 — Frontend Demo: The Split Screen (2–3 minutes, screen recording)
**What to record:**
1. Open the ShopSquire frontend
2. Upload a clean image → show recommendations appear → point at security matrix: "INFO, auto-resolved"
   Say: "Legit buyer. Zero friction."
3. Upload `macbook-QR.png` (QR + steg payload) → recommendations still appear
   Switch to Security Matrix tab
   Say: "Two things happened simultaneously. The buyer got results. The attacker got this."
   Point at: QR phishing row (DREAD 7), Steg anomaly row (DREAD 11, AML.T0048)
4. Click Decision Trace → Bitemporal tab
   Say: "Every agent step. Valid-time, transaction-time. Tamper-evident. Replayable."

**Screenshots to use in the post:** `security-1.png`, `security-4.png`, `security-5.png`

**Caption hook:** "I uploaded a laptop photo with a steganographic payload to my own platform. Here's what happened."

---

#### VIDEO 3 — Email Security Lab (2–3 minutes, screen recording)
**What to record:**
1. Show `Email Security Triage Lab - 2.png` or live UI
   Walk: severity badge → verdict → MITRE tags → playbook name
   Say: "The operator doesn't get a log. They get a triage card."
2. Submit a BEC email (homoglyph domain, bank-change body, mismatched reply-to)
   Show Phase 1–4 firing in UI
   Say: "Four phases. Under 500ms. Stage 4 — Exfiltration on the kill chain."
3. Attach `SSN-numberz - Sheet1.pdf` as the email attachment
   Show attachment forensics card: OCR extracted SSN patterns, steg score evaluated
   Say: "Same LSB chi-square engine that caught the MacBook image — checking a PDF invoice."
4. Show `Email Security Triage Lab - 3.png` — point at steg + PDF metadata panel

**Caption hook:** "I sent a fake supplier invoice to my own email security lab. DREAD 9. Kill chain Stage 5. Playbook triggered automatically."

---

#### VIDEO 4 — The Architecture Argument (90 seconds, screen recording + voice)
**What to record:** Show the slide deck (Slide 1 from ShopSquire-Redteam.pdf)
**What to say:**
> "Two attack surfaces — a buyer uploading an image, a supplier sending an invoice.
>  The same 26 agents watch both. Same security matrix. Same MITRE tags. Same audit trail.
>  This is not a WAF bolted on the outside.
>  Security runs INSIDE the recommendation pipeline.
>  Shift-left security for agentic AI.
>  The unoccupied quadrant: high ecommerce domain depth, high security depth.
>  No competitor is here."

**Caption hook:** "ShopSquire is not a Shopify. Not a CrowdStrike. It's what sits between them."

---

### LinkedIn Post Structure (for each video)

```
[Hook — 1 sentence, provocative or counterintuitive]

[What you built — 2-3 sentences, specific]

[What it does that's different — 2-3 bullet points]

[The principle / lesson — 1-2 sentences]

[Call to action — "DM me if you're building agentic AI security" or similar]

#AgenticAI #AISecurity #MAESTRO #MITREAtlas #MachineLearning
#Cybersecurity #LLMSecurity #RedTeam #ShopSquire
```

---

### Recommended posting order

| Week | Video | Why |
|---|---|---|
| Week 1 | Video 1 — The Thesis | Establish the principle first. Get engagement on the idea before the product. |
| Week 2 | Video 2 — Frontend Demo | Show the visual split: reco + security matrix simultaneously. Most shareable. |
| Week 3 | Video 3 — Email Lab | BEC / invoice fraud resonates with business audience. |
| Week 4 | Video 4 — Architecture | Saves the positioning argument for last — by then the audience has seen proof. |

---

### What NOT to do on LinkedIn
- Don't start with "I'm excited to share..." — algorithm buries it
- Don't make it a feature list — make it a story with a conflict (the image is a weapon) and a resolution (buyer gets recos, attacker gets traced)
- Don't explain every framework acronym — drop the name and move on; curious people will search it
- Don't post without a screenshot or video — text-only gets half the reach

---

_ShopSquire AI Platform · March 2026_
