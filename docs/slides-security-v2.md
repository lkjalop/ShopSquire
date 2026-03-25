# ShopSquire — Security That Sells  |  Live Demo Deck
> _16:9 — 3 slides + optional 4th · Audience: CISO, CMO, Creative Director, AI/Security Architects_
> _Thesis: Security is not a cost centre — it is the reason your platform keeps making money under fire._

---

<!-- ═══════════════════════════════════  SLIDE 1 / 3  ═══════════════════════════════════ -->

## Slide 1 — The A-10 Principle: The Platform Keeps Selling Under Attack

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  THE A-10 PRINCIPLE — KEEP FLYING, KEEP SELLING, EVEN UNDER FIRE                                  ║
║  "Security that protects revenue, not just servers"                                                ║
╠════════════════════════════════════════════╦═════════════════════════════════════════════════════════╣
║                                            ║                                                       ║
║  THE BUSINESS PROBLEM                      ║  THE A-10 ANSWER                                      ║
║  ─────────────────────                     ║  ───────────────                                      ║
║                                            ║                                                       ║
║  A customer uploads a photo of a           ║  The platform does BOTH things at once:               ║
║  MacBook they want to match.               ║                                                       ║
║                                            ║  ┌─────────────────────────────────────────────────┐  ║
║  That image contains:                      ║  │  LANE 1 — BUSINESS CONTINUITY (the customer)    │  ║
║   · A QR code (phishing URL inside)        ║  │  ► CV/OCR reads "MacBook Air 15-inch"           │  ║
║   · Text overlay ("WARRANTY VOID")         ║  │  ► NLP agent enriches: use-case = university    │  ║
║   · Hidden steganographic payload          ║  │  ► Top 3 MacBook recommendations returned       │  ║
║     (certutil + powershell LOLBin)         ║  │  ► LLM summary: "Best for lecture notes & ..."  │  ║
║                                            ║  │  ► Customer sees results in < 2 seconds          │  ║
║  Traditional platform:                     ║  └─────────────────────────────────────────────────┘  ║
║   · Blocks the upload → customer leaves    ║                                                       ║
║   · OR lets it through → breach            ║  ┌─────────────────────────────────────────────────┐  ║
║                                            ║  │  LANE 2 — SECURITY INTELLIGENCE (the operator)  │  ║
║  Either way, you lose revenue              ║  │  ► Steg detector: LSB chi-square p=0.0           │  ║
║  or you lose trust.                        ║  │  ► QR decoded: phishing URL flagged              │  ║
║                                            ║  │  ► DREAD score: 11/15 · Kill chain: Delivery    │  ║
║  ┌───────────────────────────────┐         ║  │  ► MITRE: AML.T0048 + T1218                     │  ║
║  │ CMO's question:               │         ║  │  ► Security Matrix populated in real time        │  ║
║  │ "Why did conversions drop 8%  │         ║  │  ► Human escalation triggered — not a block      │  ║
║  │  after we turned on security?"│         ║  │  ► Bitemporal trace: full causal audit chain     │  ║
║  │                               │         ║  └─────────────────────────────────────────────────┘  ║
║  │ CISO's question:              │         ║                                                       ║
║  │ "Can you prove the agent      │         ║  THE CUSTOMER NEVER KNOWS.                            ║
║  │  made the right call?"        │         ║  THE OPERATOR KNOWS EVERYTHING.                       ║
║  │                               │         ║  THE PLATFORM NEVER STOPS.                            ║
║  │ ShopSquire answers both.      │         ║                                                       ║
║  └───────────────────────────────┘         ║  Revenue protected. Trust maintained. Threat logged.  ║
║                                            ║                                                       ║
╚════════════════════════════════════════════╩═════════════════════════════════════════════════════════╝
```

**LIVE DEMO** — Upload `macbook-QR.png` and `ms-texti.png`.
Show: recommendations still return · Security Matrix populates live · Decision Trace shows full audit.

---

<!-- ═══════════════════════════════════  SLIDE 2 / 3  ═══════════════════════════════════ -->

## Slide 2 — Live: Image Threats Meet Product Intelligence

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  LIVE DEMO — TWO IMAGES, TWO THREATS, ZERO DOWNTIME                                               ║
║  "The customer gets recommendations. The attacker gets traced."                                    ║
╠═════════════════════════════════════════════╦════════════════════════════════════════════════════════╣
║  IMAGE 1: macbook-QR.png                    ║  IMAGE 2: ms-texti.png                               ║
║  ┌─────────────────────────────────────┐    ║  ┌─────────────────────────────────────┐             ║
║  │ [MacBook photo + embedded QR code]  │    ║  │ [MSI laptop + text overlay]          │             ║
║  └─────────────────────────────────────┘    ║  └─────────────────────────────────────┘             ║
╠═════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║  WHAT THE CUSTOMER SEES:                    ║  WHAT THE CUSTOMER SEES:                              ║
║  ► "Here are 3 MacBooks for university"     ║  ► "Here are 3 MSI laptops for gaming"               ║
║  ► LLM: "The M4 Air is ideal for notes,    ║  ► LLM: "MSI Katana with RTX 4070 fits your          ║
║    light coding, and 18hr battery life"     ║    AAA gaming needs at this price point"              ║
║  ► Price filters, spec comparisons shown    ║  ► Price filters, spec comparisons shown              ║
╠═════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║  WHAT THE SECURITY MATRIX SHOWS:            ║  WHAT THE SECURITY MATRIX SHOWS:                      ║
║                                             ║                                                       ║
║  ┌────────────────┬────────┬────────────┐   ║  ┌────────────────┬────────┬────────────┐            ║
║  │ Signal         │ DREAD  │ Framework  │   ║  │ Signal         │ DREAD  │ Framework  │            ║
║  ├────────────────┼────────┼────────────┤   ║  ├────────────────┼────────┼────────────┤            ║
║  │ QR phishing    │  7/15  │ T1566.002  │   ║  │ OCR text read  │  2/15  │ info       │            ║
║  │ Steg payload   │ 11/15  │ AML.T0048  │   ║  │ No steg found  │  0/15  │ clean      │            ║
║  │ LOLBin cmds    │ 11/15  │ T1218      │   ║  │ No QR code     │  —     │ —          │            ║
║  └────────────────┴────────┴────────────┘   ║  └────────────────┴────────┴────────────┘            ║
║                                             ║                                                       ║
║  Severity: HIGH                             ║  Severity: INFO                                       ║
║  Route: human_escalation                    ║  Route: auto_resolve                                  ║
║  Kill Chain: Delivery → Exploitation        ║  Kill Chain: n/a                                      ║
║  Action: Log + escalate + continue serving  ║  Action: Serve normally                               ║
║                                             ║                                                       ║
║  ► CUSTOMER STILL GOT THEIR MACBOOKS        ║  ► CUSTOMER GOT THEIR MSI LAPTOPS                    ║
║  ► ATTACKER GOT LOGGED AND ESCALATED        ║  ► BENIGN IMAGE — ZERO FRICTION                      ║
╚═════════════════════════════════════════════╩════════════════════════════════════════════════════════╝
```

**LIVE DEMO** — Split screen: left = storefront (customer view), right = admin Decision Trace (operator view).
Point: whether the image is weaponised or innocent, the customer gets the same fast experience.

---

<!-- ═══════════════════════════════════  SLIDE 3 / 3  ═══════════════════════════════════ -->

## Slide 3 — Email Triage Lab + The Human Escalation Loop

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  EMAIL SECURITY TRIAGE LAB + HUMAN ESCALATION — THE LAST MILE                                     ║
║  "The platform detects. The human decides. The trace proves."                                      ║
╠══════════════════════════════════════════════╦═══════════════════════════════════════════════════════╣
║  EMAIL TRIAGE (show Email-triage.png)        ║  THE HUMAN LOOP — WHY IT MATTERS                    ║
╠══════════════════════════════════════════════╬═══════════════════════════════════════════════════════╣
║                                              ║                                                     ║
║  Inbound email → 4-phase pipeline:           ║  THE PLATFORM DOES NOT BLOCK USERS.                 ║
║                                              ║  IT ESCALATES TO HUMANS.                            ║
║  Phase 1: Deterministic rules                ║                                                     ║
║   · SPF/DKIM/DMARC · Reply-to mismatch      ║  ┌───────────────────────────────────────────────┐  ║
║   · Bank-change language · Homoglyph domains ║  │  Threat detected                              │  ║
║                                              ║  │      │                                         │  ║
║  Phase 2: YARA scan (15 rules)               ║  │      ▼                                         │  ║
║   · LOLBins · Ransomware · QR payment redir  ║  │  Platform continues serving customer           │  ║
║                                              ║  │  (recommendations, chat, checkout — all work)  │  ║
║  Phase 3: Semantic BEC                       ║  │      │                                         │  ║
║   · Thread hijack · Kill chain inference     ║  │      ▼                                         │  ║
║                                              ║  │  Security Matrix populates in Decision Trace   │  ║
║  Phase 4: Verdict + Playbook                 ║  │  DREAD · STRIDE · PASTA · MITRE · CVSS        │  ║
║   · allow / hold / quarantine / escalate     ║  │      │                                         │  ║
║                                              ║  │      ▼                                         │  ║
║  ┌────────────────────────────────────────┐  ║  │  Human operator gets escalation alert          │  ║
║  │  STEG IN EMAIL ATTACHMENTS             │  ║  │  Sees: full trace, evidence, kill chain stage  │  ║
║  │  Same LSB/chi-square/SPA pipeline      │  ║  │      │                                         │  ║
║  │  applies to image attachments in email  │  ║  │      ▼                                         │  ║
║  │                                        │  ║  │  Human can: talk to user, escalate to SOC,    │  ║
║  │  Attachment steg → indicator folded     │  ║  │  close as false positive, or block account    │  ║
║  │  into verdict → playbook auto-selects  │  ║  │                                               │  ║
║  └────────────────────────────────────────┘  ║  │  Every action → bitemporal audit trail         │  ║
║                                              ║  └───────────────────────────────────────────────┘  ║
║  Show: Email-triage.png screenshot live      ║                                                     ║
║  Show: severity, route, MITRE tags,          ║  THIS IS THE A-10 PRINCIPLE:                        ║
║  playbook selection, steg on attachments     ║  The engine keeps running.                          ║
║                                              ║  The crew handles the damage.                       ║
║                                              ║  The mission continues.                             ║
╚══════════════════════════════════════════════╩═══════════════════════════════════════════════════════╝
```

**LIVE DEMO** — Show `Email-triage.png` screenshot. Walk through severity, route, MITRE tags.
Point: email triage uses the same security matrix as CV — unified architecture.

---

<!-- ═══════════════════════════════════  SLIDE 4 / 3 (OPTIONAL)  ═══════════════════════════════════ -->

## Slide 4 (Optional) — Intentional vs Accidental: The Business Conversation

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  INTENTIONAL vs ACCIDENTAL — THE CONVERSATION THAT CONVERTS                                        ║
║  "Not every threat is an attacker. Some are just bad photos. Know the difference."                 ║
╠═════════════════════════════════════════════╦════════════════════════════════════════════════════════╣
║  SCENARIO A: ACCIDENTAL                     ║  SCENARIO B: INTENTIONAL                             ║
╠═════════════════════════════════════════════╬════════════════════════════════════════════════════════╣
║                                             ║                                                      ║
║  Customer: uploads a MacBook photo from     ║  Attacker: uploads a MacBook photo with              ║
║  a forum post that happens to have a        ║  embedded LOLBin payload (certutil +                 ║
║  QR code in the background.                 ║  powershell -enc) in pixel LSBs.                     ║
║                                             ║                                                      ║
║  Platform response:                         ║  Platform response:                                  ║
║  ─────────────────                          ║  ─────────────────                                   ║
║  ► Recommendations: ✓ delivered             ║  ► Recommendations: ✓ delivered                      ║
║  ► QR flagged: low risk (info only)         ║  ► Steg flagged: HIGH (DREAD 11/15)                  ║
║  ► Steg: clean (score < 0.42)              ║  ► Kill chain: Delivery → Exploitation               ║
║  ► Severity: INFO                           ║  ► Severity: HIGH                                    ║
║  ► Route: auto_resolve                      ║  ► Route: human_escalation                           ║
║                                             ║                                                      ║
║  Human action: none needed.                 ║  Human action: operator contacts customer.            ║
║  Customer journey: uninterrupted.           ║  "Hey — we noticed something unusual in your         ║
║                                             ║   upload. Can you try again with a fresh photo?"      ║
║  ┌───────────────────────────────────────┐  ║                                                      ║
║  │  BUSINESS OUTCOME                     │  ║  ┌───────────────────────────────────────────────┐   ║
║  │                                       │  ║  │  BUSINESS OUTCOME                             │   ║
║  │  Zero friction. Sale completes.       │  ║  │                                               │   ║
║  │  Customer never knew security ran.    │  ║  │  If innocent: customer re-uploads, sale        │   ║
║  │                                       │  ║  │  completes. Relationship preserved.            │   ║
║  │  Conversion: protected.               │  ║  │                                               │   ║
║  └───────────────────────────────────────┘  ║  │  If attacker: payload logged, account flagged, │   ║
║                                             ║  │  SOC has full MITRE/DREAD/bitemporal evidence. │   ║
║                                             ║  │                                               │   ║
║                                             ║  │  Either way: platform never went down.         │   ║
║                                             ║  │  Either way: the trace proves the decision.    │   ║
║                                             ║  └───────────────────────────────────────────────┘   ║
║                                             ║                                                      ║
║  FOR THE CMO:                               ║  FOR THE CISO:                                       ║
║  "Security didn't cost us a single sale."   ║  "Every decision is traceable, auditable, provable." ║
║                                             ║                                                      ║
╚═════════════════════════════════════════════╩════════════════════════════════════════════════════════╝
```

Point: The 4th slide resolves the "was it intentional?" question — the platform doesn't need to know upfront.
It serves the customer, logs the threat, and lets humans make the final call.

---
_ShopSquire AI Platform · Security that protects revenue, not just servers · The A-10 Principle._
