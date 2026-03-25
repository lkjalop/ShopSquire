# ShopSquire Video 2 - Security Deep Dive (ASCII 16:9)

Purpose: LinkedIn video focused on prompt injection, CV/OCR attacks, and steganography.
Target length: 4 to 6 minutes.
Flow direction: left -> right on every slide.

---

## Slide 1 - Security Story Arc

```text
+--------------------------------------------------------------------------------------------------+
| ATTACK SURFACE               -> DETECTION LAYERS                  -> POLICY RESPONSE             |
| prompt + image + metadata       NLP + CV/OCR + steg triage          allow / monitor / flag / deny |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- This is a practical security demo for agentic ecommerce pipelines.
- The objective is safe recommendations without silent model compromise.

Visual:
- Insert `sec-matrix.png`

---

## Slide 2 - Standard Prompt Injection (Text Lane)

```text
+--------------------------------------------------------------------------------------------------+
| USER/IMAGE TEXT             -> PARSE/CLASSIFY                  -> POLICY GATE                    |
| hidden instructions            role/authority/tool abuse cues     block unsafe instruction flow    |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- First lane is direct and indirect prompt injection.
- We detect instruction override patterns before downstream agent execution.

Visual:
- Insert `why-no-prod-intent.png`

---

## Slide 3 - CV/OCR Attack Lane

```text
+--------------------------------------------------------------------------------------------------+
| IMAGE                       -> OCR EXTRACT                    -> SECURITY TAGGING                 |
| benign-looking product image   hidden payment text/URLs          social engineering, PCI, QR risk |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- OCR exposes text that users and models might ignore visually.
- OCR findings are translated into policy tags for deterministic handling.

Visual:
- Insert `no-price-textoverlay.png`

---

## Slide 4 - Steganography Lane

```text
+--------------------------------------------------------------------------------------------------+
| PIXEL PAYLOAD CHECK          -> STEG DETECTION SCORE           -> TRIAGE + ESCALATION            |
| hidden content patterns         confidence + evidence tags         quarantine/high-risk workflow    |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Stego payloads are treated as high-risk because they bypass plain OCR checks.
- Detection is probabilistic, so we pair score with policy and human review thresholds.

Visual:
- Insert one of:
- `steg-prompt_injection_hidden-Dell_15_DC15255.png`
- `steg-c2_beacon_simulation-apple-mac.png`

---

## Slide 5 - Correlating MITRE + Threat Modeling + DREAD

```text
+--------------------------------------------------------------------------------------------------+
| EVIDENCE TAGS                -> MITRE/TACTIC MAP              -> DREAD PRIORITY                  |
| qr_external_url, pci_exposed    initial access / exfil patterns   impact x likelihood triage       |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- MITRE gives shared language for defender communication.
- Threat-model stage (PASTA) + DREAD gives prioritization, not just detection counts.

Visual:
- Insert `sec-matrix.png`

---

## Slide 6 - Why Security Teams Care

```text
+--------------------------------------------------------------------------------------------------+
| WITHOUT THIS                    | WITH THIS                      | OPERATIONAL DIFFERENCE         |
| fragmented alerts               | unified evidence timeline      | faster triage and escalation   |
| little model-context provenance | decision trace with payloads   | explainable incident handling  |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Security teams need evidence continuity from signal to policy action.
- Product teams need the same data for root-cause and safe rollout.

---

## Slide 7 - Live Demo Sequence (Simple and Strong)

```text
+--------------------------------------------------------------------------------------------------+
| 1) benign image passes    -> 2) OCR-injected image flagged  -> 3) steg image escalated          |
| show clean baseline          show tags + rationale             show score + action path           |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Always show clean control first, then attack case.
- This proves you can separate normal commerce from adversarial inputs.

Visual:
- `no-steg.png` or `no-steg-msi.png` (control)
- plus one steg image (attack)

---

## Slide 8 - Evidence You Know What You Are Doing

```text
+--------------------------------------------------------------------------------------------------+
| CLAIM                         | SHOW THIS                                                       |
| detection quality             | `steg-detection-results.json` + matrix screenshot              |
| architecture rigor            | lane-by-lane controls and policy decisions                     |
| security engineering maturity | mapping to MITRE/PASTA/DREAD + explicit false-positive handling |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Credibility comes from transparent method, not hype.
- Include one miss/limitation and how you mitigate it.

---

## Slide 9 - Close and CTA

```text
+--------------------------------------------------------------------------------------------------+
| ASK TO AUDIENCE                 | WHY IT WORKS                                                   |
| "Which attack lane is highest    | invites expert discussion on architecture, not vanity metrics  |
| risk in your stack today?"      |                                                                |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Invite technical critique; that signals confidence.
- Offer to share a short threat-model template and detection matrix.

---

## Suggested Image Pack (2 to 4 images for this video)
- `sec-matrix.png` (anchor slide)
- `no-price-textoverlay.png` (OCR risk)
- one control image: `no-steg.png` or `no-steg-msi.png`
- one attack image: `steg-data_exfiltration_instruction-lenovo-pro7.png` or `steg-c2_beacon_simulation-apple-mac.png`

## MITRE/Threat Model Talking Line (short)
- "MITRE gives us the attacker behavior vocabulary, PASTA gives stage context, and DREAD gives response priority."
