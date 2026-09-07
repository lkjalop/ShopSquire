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
