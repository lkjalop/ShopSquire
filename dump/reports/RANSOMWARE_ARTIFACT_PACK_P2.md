# Ransomware Artifact Pack (P2) - Gateway Scope

## Positioning

ShopSquire is the pre-execution gate; EDR is the post-execution backstop.

## Implemented deterministic signals

- `ransomware_attachment_entropy_hint`
  - High-entropy attachment bytes/text hinting encrypted or staged payload artifacts.
- `ransomware_shadow_copy_deletion_command`
  - Detects shadow-copy deletion command strings in body/attachment text.
- `ransomware_canary_targeting_pattern`
  - Detects canary/honeypot filename targeting patterns.
- `ransomware_office_to_script_chain_indicator`
  - Detects Office-to-script execution chain indicators in text/macros.

## API/evidence additions

- Response field:
  - `coverage_limits`
- Evidence snapshot fields:
  - `evidence_snapshot.ransomware_artifact`
  - `evidence_snapshot.coverage_limits`

## Tests

- `tests/security/test_ransomware_artifact_pack_p2.py`
