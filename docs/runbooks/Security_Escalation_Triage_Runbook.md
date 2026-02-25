# Security Escalation Triage Runbook

## Purpose
Operational decision policy for `human_review` vs `security_review` in ShopSquire email/CV/OCR flows, with ethical safeguards to reduce harm and false positives.

## Mandatory Security Review (No Manual Bypass)
Escalate to `security_review` immediately when any of the following appears:
1. `account_name_mismatch` or `legal_entity_mismatch`
2. `bank_fingerprint_baseline_mismatch` or `bank_fingerprint_extracted_mismatch`
3. `auth_enforcement` under DMARC reject/quarantine
4. `prompt_injection` with execution/tool intent
5. `lolbin_command`, `malware_delivery_combo`, or malicious detonation result
6. OOB required and not verified (`mandatory_oob_verification_pending`)

## Human Review (Analyst Queue)
Use `human_review` when risk is medium and no hard-stop condition above exists:
1. Benign-likely OCR catalog overlays with no payment or execution instructions
2. Conflicting IOC confidence without hard malicious evidence
3. Soft auth anomalies with trusted historical sender and no payment-change signals

## OOB Verification Procedure
1. Validate request metadata (`vendor_domain`, trigger signal, amount, invoice reference).
2. Contact pre-approved callback via independent channel.
3. Mark challenge `confirmed` or `denied`; never process payment updates while pending.
4. Record analyst ID, timestamp, and disposition in decision trace.

## Bitemporal Trace Checklist
For every escalated case, verify these events exist:
1. `security_scan`
2. `policy_gate`
3. `security_review_started` or `human_override_requested`
4. `oob_verification_requested` when OOB is required

Required agent source IDs:
1. `Email_Security_Agent`
2. `Email_Policy_Gate_Agent`
3. `Email_Trust_Graph_Agent`
4. `IOC_Enrichment_Agent`

## Ethical Triage Guardrails
1. Do not auto-deny based only on language, locale, or script.
2. Use explainable indicators for adverse actions (entity mismatch, auth failure, malware evidence).
3. Minimize stored personal data in analyst views; use hashed identifiers where possible.
4. Require human sign-off for irreversible actions (vendor bank changes, large-value payouts).
5. Track override outcomes and feed back only adjudicated labels into threshold tuning.
