# Five-defect repair receipt — 2026-09-07

## Status

This is a partial repair checkpoint, not a production release certificate.
The reproduced scope, routing, trace and stock-projection defects have regression
coverage and passed targeted live browser checks. Two architecture guards pass;
the source-size guard still fails. No ceiling was raised.

## Changes and evidence

| Defect | Repair | Remaining limit |
| --- | --- | --- |
| Missing/unbound catalog scope | Normal persisted chat turns derive server catalog scope; the read model binds its case ID and revision without mutating the input. | Non-case early exits still need a complete scope-contract audit. Deriving scope is not a new proof that every legacy catalog path enforces the same candidate IDs. |
| Purchase/workload/unrelated routing | A device modifier or the noun “training” no longer establishes a workload. Validated model roles take precedence over generic fallback. A sold modifier cannot hide an explicitly named off-catalog purchase category. Informational questions use a typed informational scope. Empty retrieval alone no longer triggers publisher research. | This is generic taxonomy/semantic validation, not a guarantee for all negations or arbitrary conversation. No application aliases were added. |
| Contradictory trace summary | The trust strip consumes the canonical research outcome for execution, authority, completeness and uncertainty. Rejected compiled claims make requirements partial even when the source document was complete. | Freshness remains unknown when unobserved; partial accepted predicates do not prove every CPU/GPU compatibility dimension. |
| Unknown bulk stock gap | Financial economics joins the read-only inventory snapshot. Local ATP, transfers and unconfirmed supplier shortfall remain separate, with degraded/unknown freshness preserved. | Stock is not reserved or promised. A measured bulk turn took 25.638 s, down from the reported roughly 63 s; this is not a latency SLA. A FreeCAD research diagnostic still took roughly 46 s. |
| Architecture guards | Synchronous interpretation/database work runs in the route worker, not the ASGI loop. Four broad catches were narrowed or replaced with shape validation. | Six source files still exceed their ratcheted size limits. |

## Verification

- Full recommendation-core/bulk/API-focused run: 258 passed.
- Focused scope, semantics, evidence and integration run: 237 passed (overlaps the preceding run; do not add the counts).
- Frontend: 355 tests passed; production build passed.
- Real-browser run: three tests passed, one worker, zero retries, real Ollama/search profile. These cover five fresh buyer sessions: shapez 2, chair, unrelated question, bulk laptops and FreeCAD.
- Browser assertions check displayed claim values and authority, non-empty products with accepted requirements, revision-bound scope, completed trace status, purchase/category boundaries and location-aware stock accounting.
- A separate diagnostic opened all 15 trace tabs. Loading every tab is not proof that every possible summary is correct.
- Seven case-API failures were reproduced on the previous checkpoint (`44daf404`) as well as current code. Their local fixture had no tenant sold taxonomy. Explicitly seeding the laptop storefront made all 29 existing tests pass. A separate ungrounded-tenant regression preserves the fail-closed boundary.
- Final expanded case-API plus async/broad-exception architecture run: 43 passed.
- No supplier send, cart execution, source-review approval, remote push or disk cleanup was authorized by these changes.

Local evidence is outside source control:
`C:\Users\leoma\AppData\Local\Temp\shopsquire-assessment-20260907`.
Relevant logs: `five-full-core-final.log`, `five-consolidated-v3.log`,
`five-final-frontend.log`, `five-final-build.log`, `five-final-browser.log`,
`case-api-baseline-comparison.log`, `case-api-grounded.log`, `case-api-final.log`.
The browser trace artifacts are in `five-final-browser/`.

## Outstanding architecture work

Measured ceilings remain unchanged:

| File | Lines | Ceiling |
| --- | ---: | ---: |
| routers/admin.py | 4152 | 4137 |
| routers/chat.py | 5807 | 5049 |
| routers/fulfillment_cases.py | 2574 | 2447 |
| routers/shopping_cases.py | 2397 | 2073 |
| recommendation_core/core.py | 2860 | 2816 |
| recommendation_core/turn_router.py | 3259 | 2821 |

Next: extract cohesive orchestration/projection responsibilities into their
existing owned service boundaries, preserving signatures and authority semantics.
Run the full core, case API, architecture and browser gates after each extraction.
Do not minify code, delete useful tests/comments, or raise limits to hide growth.
Then audit early terminal scope exits and measure slow research roles separately.
Hosted clean-machine/PostgreSQL certification and independent source reviews are
still outstanding. This local run does not substitute for them.

## Follow-up: scope enforcement and live-discovered trace corruption

The preceding receipt describes checkpoint `d754f220`. It was verified from a
separate clean worktree: 70 focused tests passed using the existing Python
environment (not a clean-machine certificate).

Subsequent TDD repairs:

- Missing candidate IDs in `project_accepted_catalog` now yield no candidates,
  never the entire tenant catalog. Isolated projection tests explicitly supply
  their seed universe; no production unbounded-preview bypass was added.
- Explicitly partial requirements cannot produce full catalog qualification.
  Accepted claims remain accepted; the canonical outcome records
  `requirements_incomplete` and narration explains the remaining gap.
- Terminal scope metadata distinguishes bound, unavailable and not-applicable.
  Progress and retained-operation failures record pending/unavailable scope.
  This does **not** certify every early router return or legacy candidate path.
- Degraded chat responses preserve the facade's timing receipt instead of
  silently dropping it. Research-stage accounting remains incomplete.
- A real browser trace exposed UUID corruption: privacy scrubbing converted
  `sc-48504246-2713-44b7-9a2c-5de1cabe3977` into a phone-redacted string, making a
  recorded research plan unreachable. Only syntactically valid UUIDs in named
  trace-reference fields now bypass PII scrubbing. Phone-valued ID fields and
  ordinary text remain scrubbed. No corrupted historical record was rewritten.
- Failed research no longer preserves a prior budget-success sentence.
- A provider call marked successful followed by an unusable router result is
  labelled `router_output_invalid`, not a transport outage. This improves the
  failure evidence; it does not fix every invalid model response.

Owned-boundary extraction moved timing to `observability/stage_timer`, router
contracts to `turn_outcome`, case-patch validation to `case_patch_grounding`, and
admin DB diagnostics to `timescale_admin`. The unused private legacy prompt
builder had no source/test callers and was removed (recoverable in Git).
Import compatibility was retained. **admin, core and turn_router now pass their
existing size ceilings.** Chat, shopping_cases and fulfillment_cases remain over
their ceilings; no ceiling was changed.

Follow-up evidence (same external artifact directory):

- `scope-final-focused.log`: 101 passed.
- `scope-final-validation.log`: 235 passed; overlaps prior runs, not additive.
- `live-failure-regressions-green.log`: 37 privacy/narration/transport tests passed.
- `scope-live-browser.log`: first zero-retry run, one passed/two failed.
- `scope-live-after-reference-fix.log`: after the UUID repair, two passed/one
  failed. The game partial-evidence and FreeCAD checks passed; the chair response
  still degraded instead of producing the expected off-catalog answer.
- The combined scope/stock browser test was split into independent cases so a
  chair failure cannot skip unrelated-question and bulk verification.
- `scope-independent-browser.log`: unrelated-question and bulk tests both passed
  with zero retries. These are separate executions, not a green full-matrix run.

Remaining work is not just file size: complete the early-exit/candidate-enforcement
audit, diagnose the live router validation failure, expand negation/mixed-role and
subject-switch tests, measure end-to-end research latency, then run the entire
independent zero-retry matrix. A positive complete-requirements/matching-stock
live certificate remains necessary; passing the new partial-evidence refusal
test is not a substitute. Human source review and hosted/PostgreSQL release gates
remain separate and were not approved by this work.
