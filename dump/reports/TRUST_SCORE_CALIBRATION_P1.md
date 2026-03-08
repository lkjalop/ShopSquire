# Trust-Score Confidence Calibration (P1) - Implementation Note

## Runtime calibration

- Trust routing now applies calibration using `confidence_calibration` profiles:
  - Agent key: `email_trust_score`
  - Config path: `config/confidence_calibration.json`
- Output fields in `trust_case` now include:
  - `raw_score`
  - `calibrated_score`
  - `calibration_source`
  - `score` (final calibrated trust score used for policy decisions)

## Reliability report

- Added endpoint:
  - `GET /api/v1/admin/email_security/trust-score/calibration/report`
- Report includes:
  - `reliability_curve` bins
  - `ece` (expected calibration error) when labeled outcomes are present
  - sample/labeled counts and mean calibrated trust score

## Proof tests

- `tests/security/test_trust_score_calibration_p1.py`
