# Blender qualification diagnosis and execution — 25 September 2026

The first demonstrated failure was **lost table structure during extraction**. It is repaired. A qualified product journey is still blocked by application scope, compiler policy and configuration evidence. This batch does not establish pilot readiness or authorize commerce.

## Preserved and reproduced

- Local recovery checkpoint: `C:/AI/ShopSquire-checkpoints/20260925-092243`. Verified Git bundle, 5,385-file worktree archive and SHA-256 manifest. The archive includes tracked and non-ignored files, including uncommitted work. Ignored environment files and installed dependencies are not included.
- A separate evidence archive preserves 128 selected artifacts, plus a SQLite backup of the proof database whose integrity check passed. The final batch archive supplements the initial worktree checkpoint.
- Restored into an isolated directory from the bundle and worktree archive, preserving the dirty snapshot rather than pretending it is a committed clean checkout. Fresh SQLite migrations through `20260879_refund_effect_permit`, seeding and 45 baseline tests passed there.
- FastAPI lifespan startup in that restored snapshot completed with temporary Redis. `/healthz` and fast `/readyz` returned 200. The attempted `/health/db` URL returned 404; it is not a registered route in that app. This was standard-profile application startup with model prewarming disabled, not a full browser/model demo or deep readiness certification. Existing installed Python dependencies were reused.
- This is an on-machine recovery copy. Off-machine backup, dependency installation from scratch and publication/review of all existing changes remain open.

## Actual gap record

The read-only [machine-readable report](../.artifacts/blender-gap-2026-09-25/report.json) contains source hash/time, platform/tier/cell text, extracted predicates, actual compiler rejection, configuration identity, product observation IDs, freshness, literal comparison and blockers. It covers Windows minimum and recommended cells plus uncompiled instruction-set, graphics-API and architecture clauses.

Diagnostic scope: **Blender, Windows, published recommended application requirements**, retaining minimum compatibility obligations. The moving [official requirements page](https://www.blender.org/download/requirements/) does not bind a release. This is not a large-scene, Cycles GPU-rendering or render-time promise. Release/workload applicability must be resolved before qualification.

| Obligation | Source/extraction result | Exact configuration evidence | Blocker |
|---|---|---|---|
| RAM | Recommended column contains 32 GB; row label is RAM. Old parser required contiguous `32 GB RAM` and missed it. | Both selected configurations record 64 GB. | Extraction repaired; product observations are stale and not currently verified. |
| GPU memory | Recommended column contains 8 GB VRAM. Previously the only recovered claim. | Both record 24 GB. | Stale evidence; capacity alone does not prove graphics API or workload compatibility. |
| CPU cores | Recommended column contains 8 cores; minimum cell also carries an instruction-set condition. | Neither configuration has a CPU-core observation. | Missing configuration fact; compound compatibility clause remains uncompiled. |
| OS | Platform and tier cells are now preserved separately. | MSI records Windows 11 Pro; ASUS has conflicting OS observations. | Staleness/conflict plus missing version/edition compatibility policy. Exact-string failure is not evidence that Windows 11 Pro is incompatible. |
| Minimum API / instruction set / architecture | Original clauses are retained in the report. | No newly accepted facts were inserted. | Numeric extraction does not discharge these clauses. |
| Compiler scope | Enrolled-source provenance acceptance does not invoke the pinned authoritative compiler. Diagnostic compilation without a scope rejects the proposals. | Both configurations remain unqualified. | `compilation_scope_unresolved` / `manifest_scope_missing`. |
| Manifest obligations | Current electronics manifest requires RAM, named CPU/GPU, OS, storage capacity and storage type. | Does not match the obligations published in this Blender table. | A bounded application contract is needed; adding invented storage requirements or guessed CPU/GPU equivalence would not resolve it. |

Selected exact configurations, drawn from the existing proof database:

- **SCORP-126982** — MSI Titan 18 HX A2WJ-1038AU; configuration hash `a72848ace0228aca215c4fdc955c29d0a42eb7cc4db43f5e9fc379a14be7b231`.
- **SCORP-125638** — ASUS GX651AX-SR004W; configuration hash `e27d340419a1774b2ce6dd6414d888d18077183dd908abec1102e571fdb6583d`.

These are diagnostic candidates, not recommendations. Current price, stock and manufacturer facts were not refreshed. The recorded specification dates are in August, beyond the configured freshness window.

## Implemented and verified

1. Added a source-specific HTML table parser preserving platform, tier, exact cell text and source revision. It recovers 19 literal predicates across the supported platform tables, including the previously lost RAM values. Unknown platform/schema and unscoped prose abstain. Claim IDs distinguish equal values in different platforms/tiers; the Blender parser cache version changed independently of other sources.
2. The shared research outcome now exposes `manifest_scope_missing` for accepted enrolled-source claims without compiler coverage. Extracted the existing manifest-coverage calculation into a helper under behavior checks and the function-size ratchet.
3. Added a repeatable read-only gap-report script. It does not mutate the catalogue, enroll evidence, refresh timestamps or grant authority.
4. Demo launch now uses dedicated Ollama port **11435**, validates one model/one request/context at most 4096, and requires a matching live launcher receipt. The receipt binds process ID/start time, profile hash and endpoint. Client environment variables alone no longer satisfy preflight. This is local operational provenance, not tamper-proof attestation against an administrator.

Verification:

- [90 parser/compiler/provider/catalog/outcome checks](../.artifacts/blender-gap-2026-09-25/tests.xml) passed. After extracting the coverage helper, [29 focused projection/security/parser checks](../.artifacts/blender-gap-2026-09-25/projection-tests.xml) passed. These sets overlap and must not be summed as unique cases.
- The restored snapshot passed 45 baseline checks; logs and JUnit are inside the checkpoint restore directory.
- A fresh [governed official-origin fetch](../.artifacts/blender-gap-2026-09-25/governed-fetch.json) completed without discovery or unresolved source errors and recovered 19 claims. The [shared outcome](../.artifacts/blender-gap-2026-09-25/shared-outcome.json) remains partial, reports the missing scope and grants no commerce authority. This is service/projection evidence, not a newly recorded browser journey.
- Bounded-server positive preflight and endpoint-mismatch rejection passed. Server startup logs showed context 4096, maximum loaded models 1 and parallelism 1. The absent-receipt path also rejected startup. The owned server and temporary Redis were stopped after verification.
- Function-size ratchet, undefined-name checks and diff whitespace checks passed.

Reproduce the diagnosis (PowerShell, from repository root):

```powershell
$env:APP_ENV='local'
$observed=(Get-Item .artifacts/blender-gap-2026-09-25/requirements.html).LastWriteTimeUtc.ToString('o')
python scripts/report_blender_qualification_gaps.py --source-html .artifacts/blender-gap-2026-09-25/requirements.html --observed-at $observed --database .artifacts/roadmap-proof.sqlite3 --tenant default --sku SCORP-126982 --sku SCORP-125638 --output .artifacts/blender-gap-2026-09-25/report.json
```

For a demo, keep `./scripts/start_local_ollama.ps1` running in one terminal before running `./start_demo.ps1` in another. An unrelated server on 11434 is not adopted or stopped.

## Revised next work

1. Bind one Blender release, Windows platform and workload tier to a reviewed obligation contract. Carry enrolled claims through the authoritative compiler and enforce platform/tier applicability at consumption. Preserve missing clauses as gaps; do not shrink completeness to the fields the parser happens to emit.
2. Refresh attributable facts for one selected configuration: CPU cores/instruction support, GPU API support, exact OS edition/version, RAM and VRAM. Resolve conflicting ASUS observations through supersession with evidence, or use the MSI candidate. Then verify qualified/insufficient/stale/revoked/model-failure outcomes through API, UI and trace.
3. Enforce authenticated distinct-person approval at the workflow and effect dispatch boundaries before real commerce. This batch did not implement that gate or finish revocation/renewal and uncertain-provider recovery.
4. Run the predefined varied 60-minute reliability suite, then overnight. This batch adds no sustained-soak certification and changes no model-quality conclusion.
5. Obtain the real tenant/SKU or lane, attributable observations and independent relevance/outcome labels before claiming useful market decisions or representative benchmark improvement.

A general derivation ledger remains deferred. The diagnosis demonstrates extraction, scope/contract and product-evidence failures first.
