# Original-image adversarial upload delta — 25 October 2026

This is a bounded security qualification, not a declaration of MVP or release readiness. The original corpus stays private under `dump/test-sec`; decoded payloads, QR personal information, authentication traces and fixture credentials are not published.

## Repairs and unchanged expectations

Backend commit `65834bb7` admits native authenticated buyers to upload inspection while retaining tenant membership, identity and operator-key rejection controls. Buyer artifact identifiers are namespaced by tenant and subject, preventing upload-history replacement by reusing another buyer's identifier. This is not proof of every artifact read/consumption boundary.

Frontend commit `d61affce` makes quarantined/pending/degraded artifacts visible in Security even when privileged trace reads are unavailable. It distinguishes recovered payload patterns from observed runtime activity, does not call severity confidence, and does not imply suggested hunting/response agents ran. A blocked upload overrides optimistic presentation flags. Read-only recommendation permission requires an explicit clean verdict and explicit permission; it confers no commercial authority. Trust labels wrap rather than disappear behind ellipses. Extracting the fallback projection reduced DecisionTrace from 4,372 to 4,324 physical lines; broader ownership refactoring remains open.

## Evidence

| Scope | Result | Meaning |
|---|---|---|
| Native buyer admission, before | 2 failures, 5 passes | Positive buyer uploads encountered 401; rejection controls retained their meaning |
| Admission plus existing extraction/severity/responsiveness, after | 22 passes, no skips | Same buyer admission expectations and existing detector controls pass |
| Ownership/security regression | 31 passes, no skips | Selected boundary, full-resolution and artifact-authority controls; not a complete security suite |
| Trace domain, before/after | 3 failures / 9 passes | Artifact state now exposes Security without requiring privileged events |
| Rendered narrative tests, before | 3 failures | Hidden-payload denial, runtime overclaim and severity-as-confidence reproduced |
| Rendered authority test, before | 1 failure, 3 passes | Optimistic fallback could imply recommendation permission for a quarantine |
| Current storefront unit suite | 424 passes, no skips | Native Vitest exit 0; TypeScript also passes |
| Current production-preview browser | 11 passes, 0 failures, 0 skips, 0 flaky | Nine original adversarial paths quarantine; two clean-photo controls do not falsely flag steganography |
| Passive technique mapping, before/after | 1 failure, 1 pass / 23 passes | Steganography is now mapped to possible T1027.003, with filename-only and existing payload/severity rejection controls |

The final browser run took 61.854 seconds in Playwright, 73.281 seconds including owned runtime supervision. Peak observed process RSS was 760,205,312 bytes, 1,160 handles and 78 threads, with no supervisor violation. It used native registered buyers, HTTP/API assertions and a built frontend, without application/API mocks. Models were unavailable, commercial effects sandboxed, and an HTTP proxy denied external destinations. That configuration is not an operating-system network isolation proof.

The nine adversarial image paths contain six unique byte hashes: five LSB payload families plus the QR image. Duplicate filenames count as upload-path regressions, not independent attacks. LSB extraction recovered C2, exfiltration, command-sequence, payment-fraud and prompt-injection patterns. The QR was quarantined by its separate QR/security path; a negative steg verdict is not a QR detection failure. Two unique clean carriers passed their native upload controls. The legacy manifest's original Lenovo hash differs from the available clean carrier; current byte hashes, not historical labels, identify the controls.

All 12 original corpus files and three recorded control rows were hash-checked after execution and remained unchanged. `steg_embed.py` was read as untrusted fixture material and was not executed. No decoded command or destination was followed. An initial harness waited for upload before clicking Send and failed; that harness correction is not an application repair. A subsequent nine-case run reached quarantine but failed because Security was hidden; that is a real application failure retained in the private evidence.

Private native receipts are under `.artifacts/mvp-adversarial-20261025` and `.artifacts/roadmap-execution-2026-10-20/mvp-*`. They are local evidence, not public downloadable artifacts. The final screenshot was visually inspected: trust labels are readable and runtime uncertainty is explicit. The buyer's privileged-trace authorization warning remains visible and unresolved. End-to-end clean-image product usefulness, image transformations, additional steganographic encodings, provider telemetry, cross-worker privacy, container scanning and endurance are not qualified here.

## Green and next work

Green means the unchanged behavioral expectation passes with a useful positive and rejection controls. Authentication failures, blocked-only results, mocks, skips and fixture-only stock keep their narrower meaning. These results do not supersede the broader failures or hosted Ruff findings in the [consolidated roadmap](../CONSOLIDATED_SAVEPOINT_AND_PILOT_ROADMAP_2026-10-25.md).

Next qualify ordinary browsing/bundle choices and the shared shortfall draft on the current source, then live consented discovery, facet-relevant cited intelligence and amendment/reload. Keep exploratory catalogue choices separate from evidence-qualified fit and explicit stock acceptance. Release still requires supported clean installations, required hosted/security gates, source-bound recovery and endurance.

The current-source five-case buyer retest passed the shared reviewed-draft journey, including fixture 40 requested / 15 held / 25 short, amendment invalidation, reload and cited simulated supplier terms. All four unchanged category/bundle cases still failed with empty candidates. This is a retained red contract, not a reason to redefine green. The browser receipt is separate from the 11-case original-image run.

The mapping correction follows the primary [MITRE Steganography entry](https://attack.mitre.org/techniques/T1027/003/); [Binary Padding](https://attack.mitre.org/techniques/T1027/001/) describes a different mechanism. Neither a passive pattern nor a technique tag proves runtime execution.
