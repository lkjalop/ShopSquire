# MVP security and buyer-workflow delta

Later update: [pilot resumption, 456 storefront passes, trace binding and buyer snapshot transport](PILOT_RESUMPTION_DELTA_2026-10-25.md). The results below retain their original source scope.

25 October 2026, Australia/Sydney. Tested source: `c11d51b048e5cc25b40231822d55e79c7202d796`. This supplements the [consolidated roadmap](CONSOLIDATED_SAVEPOINT_AND_PILOT_ROADMAP_2026-10-25.md), retaining its historical freezes and failures. The platform is not declared MVP-ready or release-green by this update.

## What changed and what passes

| Area | Verified delta | Boundary |
|---|---|---|
| Buyer upload admission | Native registered buyers can inspect uploads; tenant/identity/key rejection and buyer artifact namespacing remain enforced | Does not establish every artifact consumption/read boundary |
| Original adversarial images | Nine original image paths quarantine in the real buyer UI; two clean carriers pass; final recheck **11 passed, zero skipped/flaky** | Six unique adversarial byte hashes; filenames duplicated across variants are not independent attacks |
| Decision Trace | Quarantine and incomplete inspection expose Security without requiring privileged event reads; blocked authority wins; labels wrap; recovered patterns do not imply runtime execution | Privileged trace authorization warning still appears for buyers; provider correlation and runtime confirmation remain separate |
| Technique and payload labels | Steganography maps to possible T1027.003; a destination alone no longer becomes C2; URL-bearing injection keeps its injection label | Passive findings are not proof of execution; containment behavior remains unchanged |
| Catalogue browsing | Imported category metadata now covers all 11 source categories. Ordinary monitor, bag and hard-drive requests return useful priced source items | Seven source rows with missing/conflicting prices stay held; snapshots do not certify compatibility or current real stock |
| Buyer presentation | Browsing explains category/price scope and model degradation without denying returned choices; irrelevant requirement/architecture panels are hidden | Technical-fit questions still require evidence; no extra commerce authority is granted |
| Supplier workflow | Current browser positive retains fixture **40 requested / 15 held / 25 short**, shared draft/hash, independent approval, amendment invalidation, reload and cited simulated lead time | Distinct from the live-search journey; fake transport and supplier terms stay labeled simulation |
| Live search and memory | Two native browser cases pass consented SearXNG discovery, quantity correction, task requests and reload; serialized receipt copies deduplicate to three distinct HTTP-200 receipts | Receipt deduplication is not an independent provider-call counter; discovery does not admit lead-time facts |

The source import initially enrolled only laptops into the fixture tenant's approved taxonomy. Fixing the index returned eight monitors and four bags; those tests then exposed a source-title comparison that ignored the importer's whitespace normalization. The comparison now normalizes whitespace on both sides, retaining the source-membership expectation. Additional browser rejection assertions require the unrelated architecture, requirements and unresolved-research widgets to be absent during browsing. These oracle corrections and stronger controls are explicit; they are not counted as unchanged-test application repairs.

The five-case buyer profile moved from **one pass/four failures** to **four passes/one failure**, with no skips or flaky outcomes. The remaining failure is the requested laptop/monitor/bag bundle. Its useful-product and no-involuntary-cart expectations remain in place. The three browsing presentation assertions were separately observed red before the presentation change and green afterward.

## Current native qualification

| Profile | Native result | Scope |
|---|---|---|
| Broad `tests/security` plus buyer-upload ownership and steg severity | **878 passed, 16 skipped, zero failures/errors**, 461.063 seconds | Includes stubs/mocks in unit and protocol tests; skipped checks are not qualified |
| Category, terminal projection, transition, qualification and case regression | **105 passed, zero skipped** | Overlaps smaller repair scopes; do not add counts together |
| Storefront Vitest after the latest UI changes | **424 passed, zero skipped**, 55.703 seconds | Unit/component qualification; distinct from browser/provider execution |
| Storefront TypeScript and owned production preview | Passed | The current preview was built for the native browser runs |
| Original images and clean controls, current recheck | **11 passed, zero skipped/flaky**, 63.760 seconds in Playwright | Native buyers, actual original bytes, no API mocks, unavailable models, sandboxed commerce, external HTTP denied by configured proxy |
| Catalogue and reviewed supplier workflow | **4 passed, 1 failed**, 10.440 seconds in Playwright | Native buyer and independent operator review; bundle remains red |
| Live read-only search/memory | **2 passed, zero skipped/flaky**, 13.399 seconds in Playwright | Real SearXNG discovery; unavailable models; no real commercial transports |
| Source/function size ratchets | Passed without changing ceilings | Warnings remain: App 4,292 lines, DecisionTrace 4,324, chat 4,825; size is still debt |

The broad security supervisor observed a peak process RSS of 631,762,944 bytes, 1,998 handles and 113 threads, with no resource violation. These bounded runs do not clear the historical 151.56-second request, connection-exhaustion finding or endurance requirement. The earlier full Python result of 8,846 passes/311 skips belongs to its earlier freeze; it was not rerun wholesale for this update.

The [original-image assessment](audits/ADVERSARIAL_UPLOAD_DELTA_2026-10-25.md), [current image ledger](audits/adversarial-upload-evidence-2026-10-25-destination-after.json) and [buyer case ledger](audits/buyer-mvp-delta-evidence-2026-10-25.json) retain hashes, source identity and per-case results without decoded personal information, raw authentication traces or credentials. Raw native receipts/screenshots are private `.artifacts` evidence. The image trust panel and catalogue presentation were visually inspected; automated visibility checks supplement those observations.

## What the live journey still cannot complete

The live buyer retains the amended 40-unit request, AUD 1,500 per unit and Sydney destination. Its provisional email has `shortfall: null` and explicitly lacks `supplier_contact` and `current_accepted_selection`. It cannot invent either the available stock or the shortage. Its lead-time intelligence is blocked with `no_current_scoped_evidence`, no answered lead-time facet and zero admitted citations. Those are honest outcomes under the memory test's acceptance contract, not successful completion of the desired commercial task.

The separate fixture positive proves shared reviewed-draft continuity and relevant simulated supplier terms. It must not be spliced into the live conversation and presented as one completed real merchant workflow.

## Next implementation order

1. Preserve the current clean source checkpoint and native evidence. Continue using explicit commits and private runtime backups; do not publish original payloads, credentials or all private Git refs.
2. Finish useful bundle choices through the existing canonical catalogue/planning boundary. Preserve per-line quantity, currency and price basis, total-budget arithmetic, optional versus accepted items and absence of automatic cart changes. Do not bypass workload or tenant checks to make the remaining browser case pass.
3. Complete ordinary buyer selection/current fixture-stock acceptance in the same research conversation, then derive the exact shortage and reviewed supplier draft from that accepted revision. A missing contact or current selection must be actionable and must stay unknown until provided.
4. Admit relevant current market evidence for the requested facet, source, region and validity interval, with a useful cited positive and unrelated/stale rejection. Search hits and demand observations cannot establish supplier lead time. Keep simulated quotes visibly simulated.
5. Close the buyer/operator explanation boundary and cross-worker privacy gaps; diagnose bounded runtime cancellation, connection exhaustion and shutdown ownership. Catalogue progress does not clear these security/runtime packages.
6. Resolve required hosted gates and supported installation/image findings, then freeze the pilot candidate for required broad testing, recovery/rollback and endurance. The previous hosted Ruff gate recorded 333 findings in the PR scope; the accumulated checkpoint gate remains separate. No ignore threshold or lint waiver was introduced here.

The selected MVP remains requirements → useful candidates → explicitly accepted current stock → exact shortfall → relevant cited intelligence → reviewed supplier draft → amendment/reload. A guided fictional rehearsal is available; a finished ordinary live-search-to-shortfall journey and release readiness remain open. No overall completion percentage is asserted. All W00–W15 packages remain represented in the consolidated roadmap.
