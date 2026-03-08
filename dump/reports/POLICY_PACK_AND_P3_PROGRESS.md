# Policy Pack Versioning + P3 Progress

## P2: Policy pack versioning + signed release notes

- Added signed policy-pack release workflow with manifest hashing over key controls.
- Endpoints:
  - `POST /api/v1/admin/email_security/policy-pack/release`
  - `GET /api/v1/admin/email_security/policy-pack/releases`
  - `GET /api/v1/admin/email_security/policy-pack/releases/{version}`
- Signature:
  - HMAC-SHA256 over `{manifest, release_notes}` payload.
  - Env keys: `EMAIL_SECURITY_POLICY_SIGNING_KEY`, `EMAIL_SECURITY_POLICY_SIGNING_KEY_ID`.

## P3: BIMI visual similarity

- Added `visual_similarity` output in BIMI verification with:
  - `brand_spoof_score`
  - `spoof_suspected`
  - `logo_host_mismatch`
- Email security now adds:
  - indicator `bimi_visual_brand_mismatch`
  - reason `bimi_visual_brand_similarity_spoof`
  - evidence fields:
    - `evidence_snapshot.bimi_verification`
    - `evidence_snapshot.bimi_visual_similarity`

## P3: Adversarial pipeline + external benchmark pack

- Added synthetic adversarial generation pipeline:
  - template mutation
  - homoglyph domain mutation
  - OCR noise mutation
  - URL indirection mutation
- Endpoints:
  - `POST /api/v1/admin/email_security/adversarial/generate`
  - `POST /api/v1/admin/email_security/benchmarks/external/run`
- Benchmark run writes report JSON (default path):
  - `dump/reports/external_benchmark_pack_v1.json`
