# Pilot resumption and remaining work

25 October 2026, Australia/Sydney. Tested code: `82e5cabcb83d43cd00911e6155a17daabcfb0c97`. See the [sanitized receipt ledger](audits/pilot-resumption-evidence-2026-10-25.json), [earlier buyer/security delta](MVP_SECURITY_AND_BUYER_DELTA_2026-10-25.md) and [full roadmap](CONSOLIDATED_SAVEPOINT_AND_PILOT_ROADMAP_2026-10-25.md). This is a source checkpoint, not MVP or release approval.

## Interruption investigation

Local Codex diagnostics record HTTP 400 from an official OpenAI host at 13:47:18 Sydney time, followed by the generic `Bad Request` detail in the turn log. The saved application/browser logs searched did not contain a matching 400. This supports a Codex request-path interruption; the available error does not establish the rejection reason. No account/configuration changes were made. Credentials, headers, raw request bodies and conversation logs are not published. Official [Codex error documentation](https://learn.chatgpt.com/docs/app-server#errors) describes failed turns and upstream error metadata; it does not diagnose this particular rejection.

The working tree was clean at `09e09a19` on resumption. The prior optimization and browser tests had completed successfully; they were not still running.

## Verified changes

| Change | Evidence | Limit |
|---|---|---|
| Category-neutral product lanes extracted from App | 14 focused controls; App reduced by 65 lines to 4,227; ordinary category browser positives in the preceding cohort | Missing OS stays unclassified; no inferred compatibility or fit; bundling still fails |
| LSB chi-square histogram | 19 numerical reference cases; preceding combined security profile 62 passes; deterministic 2,000²-channel median reduced from 0.79637 s to 0.02245 s with identical score | About 35 times faster for this calculation only; no API latency, accuracy or endurance claim |
| Trace/case/revision binding | A rendered regression reproduced another trace's query appearing under the requested ID; exact-ID and invalid-revision controls now pass | Presentation binding complements backend ownership; this is not all artifact-read/privacy coverage |
| Image evidence continuity | Matching artifact remains visible; mismatched artifact is excluded; previous trace/events/explanations reset on transition | Late upload callbacks and broader cross-case lifecycle still require review |
| Buyer snapshot transport | Regression: 29 pass / 1 fail before repair, unchanged expectation then 30 pass; authenticated operator rejection control remains terminal | Component fetch is mocked in these focused tests; no buyer access to privileged events is granted |
| Native original-image browser | **11 pass, 0 fail/skip/flaky**, 61.359 s browser duration; nine adversarial paths quarantine, two clean controls pass | Six unique adversarial image hashes; duplicates are disclosed in earlier ledgers; models disabled and external HTTP denied |
| Buyer security presentation | Nine adversarial browser cases assert SNAPSHOT and zero operator-only trace GETs; beacon screenshot visually inspected | Passive recovered patterns remain unconfirmed runtime hypotheses |
| Storefront regression | **456 pass, 0 fail/skip**, 59.187 s; TypeScript, production browser build and source/function size ratchets pass | Focused tests overlap this suite; passing ratchets do not remove existing oversized-file debt |

## Work needed for the selected MVP

1. **Complete canonical multi-line bundle choices.** The existing bundle browser expectation remains red. The parser misses singular quantified requests, and the legacy optional planner reads an unscoped catalogue. Fixing a parser or enabling that planner alone would not establish tenant isolation, per-line quantities, a whole-bundle budget, currency/tax basis, or accessory compatibility. Preserve the unchanged no-cart-mutation expectation and add rejection/tenant/over-budget controls.
2. **Join the ordinary live workflow.** Explicitly accept a catalogue SKU and current stock, calculate the exact shortage, admit relevant cited intelligence, and pass those facts to the shared versioned supplier draft. The earlier live SearXNG journey retains 40 units but still has unknown shortage and no admitted lead-time citations. The separate simulated 40/15/25 reviewed-draft positive cannot substitute for that joined journey.
3. **Complete merchant portability.** Remove remaining laptop taxonomy/presentation defaults through merchant configuration, retain source/category boundaries, test AU/US/EU currency and price-basis cases, and cover non-electronics bundles. The selected data is fictional catalogue/stock, not real merchant inventory.
4. **Close continuity, privacy and runtime gaps.** Review late upload callbacks, buyer history tenant routing, all artifact reads, erasure/recovery, temporal admission and market relevance. Measure long requests and database/session/scheduler ownership; this histogram optimization does not close historical hangs or connection exhaustion.
5. **Qualify one frozen candidate.** Resolve required hosted lint/image/install gates; run required broad suites, supported clean installs, security profiles, runtime/database restore and rollback, and endurance. Earlier 8,846-pass Python and 878-pass/16-skip security receipts retain their original source scope and are not rerun by this update.

“Green” means the unchanged behavioral expectation, its positive and rejection controls pass on identified source. Mocked checks, blocked outcomes and skips keep their narrower meaning. Release green additionally requires all required gates on one frozen candidate. There is no defensible overall completion percentage and no claim to manual review of every repository line. W00–W15 remain represented in the full roadmap.
