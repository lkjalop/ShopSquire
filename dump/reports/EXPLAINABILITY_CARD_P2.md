# Explainability Card (P2)

## What was added

- `explainability_card` is now included in email security evaluate responses.
- The card is also persisted in `evidence_snapshot.explainability_card`.
- Investigation payload now surfaces:
  - `explain.explainability_card`
  - `explain.why_flagged`
  - `explain.why_not_blocked`

## Card fields

- `decision` (`severity`, `route`, `verdict_action`, `escalation`)
- `why_flagged` (top reasons)
- `why_not_blocked` (deterministic rationale)
- `top_contributing_features` (artifact contribution or indicator fallback)
- `controls_evaluated` (DMARC/IOC/semantic/YARA/ransomware control summary)
- `analyst_summary`

## Files

- `src/app/security/email_security.py`
- `src/app/routers/admin_email_security.py`
- `src/app/schemas/email_security.py`
- `tests/security/test_email_explainability_card_p2.py`
- `tests/api/test_admin_email_security_investigation.py`
