# Agentic Security Mapping Matrix (Demo-Ready)

This is a compact evidence-oriented mapping from ShopSquire "attack lanes" to controls and artifacts you can show live.

## Lane A: Email BEC / Phishing / Supplier Payment Change

- Primary controls
  - Intake-only normalization: NFKC normalization for identity fields (From/Reply-To/Subject) and canonicalized whitespace.
  - Deterministic rules: reply-to mismatch, DMARC/SPF/DKIM anomalies, payment-change language.
  - Playbook-driven response: tags/risk-band -> playbook selection -> typed actions (hold, ticket, notify) -> audit trail.
- Evidence artifacts
  - API response includes: `tags`, `reasons`, `risk_band`, `playbook.id`, `decision_id`.
  - Trace stream includes: `security_scan`, `policy_gate`, `playbook_run_started`, `playbook_step`, `playbook_run_completed`.

- MITRE ATT&CK (typical mapping)
  - Initial Access: Phishing (T1566)
  - Collection/Exfil: Exfiltration Over Web Service (T1567) (for link-driven theft patterns)
  - Impact: Account Manipulation (T1098) (for payment redirection workflows)

- OWASP (LLM / agent-adjacent)
  - Data validation and trust boundaries: treat email and attachments as untrusted input.
  - Human-in-the-loop enforcement for financial changes.

## Lane B: CV / OCR / Document Robustness

- Primary controls
  - Tier0 gates: image quality gating before heavy pipelines.
  - Robustness checks
    - Dual OCR disagreement (optional): run two OCR providers and flag low similarity.
    - QR/barcode payload extraction (best-effort): detect URL payloads and tag them for review.
  - Policy gate: if robustness signals fire, escalate required actions (human review / manual approval).

- Evidence artifacts
  - CV tier2 response includes: `robustness.dual_ocr`, `robustness.qr`, `evidence_tags`.
  - Trace event on upload includes: `cv_upload` + the tier2 payload and evidence bundle id.

- MITRE ATT&CK (typical mapping)
  - Initial Access: Phishing via attachment/QR (T1566)
  - Defense Evasion: Obfuscated/Compressed Files and Information (T1027) (PDF/container patterns)

## Lane C: Agent Outbound Comms (Email C2 / Beaconing)

- Primary controls
  - Outbound monitoring: log outbound email entropy + timing metadata per agent identity.
  - Periodicity detection: inter-arrival variance (beacon-like timing).
  - Encoded subject detection: Shannon entropy thresholding.

- Evidence artifacts
  - Admin endpoint returns: anomaly reasons, score, and agent id.
  - Trace event (when decision_id provided): `outbound_email_observed`.

- MITRE ATT&CK (typical mapping)
  - Command and Control: Application Layer Protocol (T1071)
  - Exfiltration: Exfiltration Over Alternative Protocol (T1048) (conceptual mapping)

