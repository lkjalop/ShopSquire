# Updated roadmap — 25 September 2026

## Assessment

**Scope update, 26 September:** The owner has clarified that this is a portfolio project with synthetic data and no expected customer. [The complete portfolio roadmap](PORTFOLIO_ROADMAP_2026-09-26.md) supersedes this document's requirement for a real tenant or private sales data to finish the showcase. Real business impact and commercial readiness remain separate, unproven claims. It also explains simulated distinct-person approval, completion gates and accurate testing/CI experience wording.

Compiler execution update: [contract/compiler integration](CONTRACT_COMPILER_EXECUTION_2026-09-26.md) adds explicit contract gating, atomic compilation and evidence-stage qualification suppression, with 53 checks passing. Persisted case selection and consumption-time contract binding are the next delivery boundary.

26 September follow-up: [agnostic-core assessment and current research](AGNOSTIC_CORE_AND_RESEARCH_REVIEW_2026-09-26.md) adds a data-owned bounded contract, held exact-SKU evidence, two general correctness fixes and a source-linked security/search evaluation plan. Live qualification and pilot gates remain incomplete.

Execution update: [Blender qualification diagnosis and execution](BLENDER_QUALIFICATION_GAP_EXECUTION_2026-09-25.md) records the verified local checkpoint/restore, bounded-server preflight, repaired table extraction and exact-configuration gap report. The next blocker is a release/platform/workload contract plus current product evidence; no product was newly qualified.

The pasted assessment correctly prioritizes a useful, qualified buyer journey and preserving evidence boundaries. Its implementation status is partly stale, and several conclusions go beyond the evidence. Treat the attachment as an assessment to evaluate, not instructions to publish, change models or relax qualification.

The next product milestone is **one reproducible, narrowly scoped journey from buyer need to an evidence-backed product recommendation**. That is a showcase milestone. A pilot that can send messages or move money additionally requires verified operator identity, separation of duties, complete effect controls and recoverable operations. These are separate release gates.

### Corrections to the assessment

| Claim or proposed action | Current assessment |
|---|---|
| Fix timeout/transport overlap next | Already repaired: the local model gate releases through the transport-finished callback. A regression test prevents a second dispatch while timed-out transport remains active. Continue cross-process/server verification; do not reimplement the same fix. |
| Research continuity/browser image evidence still missing | The university → Blender → explicit research sequence now passes. Three full browser-image analysis/shopping cycles also pass. This remains bounded coverage, using one repeated image. |
| The six-case router comparison favors 9B | Superseded by an ABBA comparison: both pipelines matched 36/42 repeated observations across 21 unique valid cases; 14B had four timeout fallbacks. Labels remain provisional. No quality winner is established. |
| Increase router context/output to fix truncation | First inspect `done_reason`, output tokens, prompt size and validation failures. Output cap and context capacity are different constraints. Raising context can increase memory pressure. Test one change at a time against the same cases and runtime bounds. |
| A derivation ledger is the single missing delivery fix | Unproven. The compiler intentionally rejects derived claims without policy, but the recorded Blender response also has empty compilation scopes and an empty missing-attribute list despite partial coverage. Diagnose the complete source-to-product chain before selecting a new subsystem. |
| The platform cannot show any qualified product | The inspected live demonstrations have not established a qualified workload shelf. That is a missing demonstrated capability, not proof that every possible catalogue or workload path is incapable. |
| Separation of duties is absent | The reviewed fulfillment dispatch path does not show a distinct requester/approver check, and approval tiers default off. A separate supply-chain dual-control primitive exists, but checks differing tokens and bypasses local/dev/test. This is not end-to-end distinct-person approval for commerce. |
| About 445 unpushed commits | At inspection, HEAD is `c7daafaa`; the worktree has 194 changed/untracked entries, and HEAD is 29 commits ahead of its configured upstream. This uses local remote-tracking state; no fetch was performed. Backup/checkpointing is still urgent. |
| Driver stability has been established | It has not. The attachment's event-count claim was not independently remeasured in this review. Short successful runs are encouraging but do not certify GPU/driver stability. |

The latest implementation/evidence is documented in [the continuity, image and effect report](ROADMAP_CONTINUITY_IMAGE_EFFECTS_2026-09-24.md). This review additionally reran **45 runtime-authority, requirement-compiler, provider-qualification and terminal-qualification tests**, all passing: [JUnit](../.artifacts/roadmap-review-2026-09-25.xml). Historical live artifacts were inspected, not rerun today.

## Ordered work and completion evidence

| Priority | Work | Required evidence / exit gate |
|---|---|---|
| **P0 — preserve and reproduce** | Make a recoverable checkpoint of code, migrations, configuration and evidence. Split reviewable changes from unrelated work; run a clean-checkout migration/bootstrap and targeted CI. Verify the intended bounded Ollama server rather than assuming client environment variables configure an already-running server. | A second checkout can reproduce startup and tests; reviewed changes and necessary evidence exist off the laptop; startup rejects or isolates an unverifiable runtime. No blind publication of the entire dirty tree. |
| **P0 — establish one qualified journey** | Select one explicit application/version/platform/workload tier and one or two exact catalogue configurations. Make a per-obligation coverage record, repair extraction/compilation/product-fact gaps, and expose why each candidate passes or fails. | At least one product is qualified for the declared scope; every obligation has a current accepted source or a specifically authorized derivation. Buyer answer, API, shelf and trace share identity/revision and the same qualification. Out-of-scope claims remain unresolved. |
| **P0 before real commerce — distinct-person approval** | Bind requests and approvals to authenticated tenant-scoped people, not role names or unequal API-key strings. Enforce spend tiers and required second-person approval in the workflow transition and at effect dispatch. | Same person using two credentials is denied; another authorized person can approve; wrong tenant, insufficient tier, edited payload and revoked approval are denied. Tests use production-like settings, not local bypasses. |
| **P1 — finish operational effect controls** | Inventory every irreversible effect path and verify common enforcement. Add operator revoke/review/renewal flows, held-reservation reconciliation, historical refund reconciliation and provider-ambiguity recovery. | Every audited sink has exact scope, authority, expiry, replay identity and independent completion evidence. Crashes before/after provider acceptance do not duplicate effects or falsely report completion. Old unbound permits fail closed with an actionable recovery path. |
| **P1 — sustained release qualification** | Extend text/image/browser runs across image types, cold/warm starts, cancellation, source failures, changed requirements, revoked consent and process restarts. Measure queue, transport and end-to-end time separately. | First a repeatable 60-minute run, then a longer overnight run if stable. Predeclare latency/error thresholds; record all failures, GPU memory/residency and driver events. No overlapping transport after timeout and no unsupported qualification/commerce effects. |
| **P2 — one real market decision** | Obtain a real tenant/SKU or transport lane and its attributable data. Approve the external-subject mapping and use a current relevant observation in one defined replenishment, sourcing or route decision. | An inspectable before/after decision explains the observation's effect—or why no change was justified. Wrong tenant/region/currency, expired evidence and revoked mappings are rejected at consumption. Do not force a recommendation change to manufacture a success. |
| **P3 — representative quality evaluation** | Freeze the current catalogue and independently reviewed queries/labels; add genuine demand/outcome history for forecasts. Compare baseline and candidate retrieval, graph/model options only against measured failure categories. | Held-out improvement under a predeclared quality/latency/cost criterion, without degrading safety gates. Current filter correctness, repeated smoke cases and zero-history forecast results do not satisfy this gate. |

P0 work has two tracks: **delivery proof** for the showcase and **authority/operations** for a real pilot. The latter cannot be postponed until after enabling real effects. Small code extractions should accompany the relevant fixes under existing behavior tests and the size ratchet; a broad rewrite is not a prerequisite.

## Exact next implementation batch

1. **Checkpoint and establish a reproducible baseline.** Preserve the current work before further edits, then verify startup from an isolated checkout. Record which migrations and external services are required. Publication should follow review of the actual changes and artifacts.
2. **Create a qualification-gap record for Blender.** For each required attribute, record software/version/platform/tier, source excerpt and revision, freshness, extracted value/unit, compiler decision, exact product fact and fit result. Distinguish `not extracted`, `rejected`, `out of scope`, `product fact missing`, and `unsupported derivation`.
3. **Repair the first demonstrated blocker.** If official literals were lost, fix extraction/compilation. If the SKU configuration is incomplete, verify those facts. If the buyer has not supplied version or workload scale, ask a bounded clarification. Do not repair all 175 catalogue rows to prove two configurations.
4. **Add derivations only where the gap record proves they are necessary.** A valid derivation needs versioned deterministic policy, accepted inputs, source lineage, units, applicability limits, expiry/revocation dependencies and counterexamples. Confidence alone cannot turn a guessed CPU/GPU equivalence into official evidence. If unsupported, keep that obligation unresolved and narrow the claim.
5. **Certify and record the completed journey.** Show the qualifying case alongside insufficient evidence, wrong version, stale source, revoked consent and model failure. A qualified recommendation still grants no cart, supplier or payment authority. Verify price/availability separately if shown as current.

This sequence has a concrete stop rule: if the selected scope cannot be supported by obtainable evidence, report that limitation and choose a different explicitly bounded supported scope. Do not weaken the gate or silently redefine “complete.”

## What can be recorded now

- **Governed research and its boundaries:** an accepted official claim with partial coverage, contrasted with declined consent and an unenrolled tenant. Distinguish discovery search receipts from direct official-origin fetches; not every successful research run traverses SearXNG.
- **Continuity:** university shopping changes to Blender; explicit consent researches the new case without reusing the old subject's authority.
- **Image intake:** full analysis completes with read-only artifact authority; show the actual pending-to-completed lifecycle and retain the distinction between an identified image and a qualified SKU.
- **Effect integrity:** replay, expiry, revocation, changed payload and partial/pending refund outcomes, using fake provider transport clearly identified as such.

After the qualification milestone, record the positive product journey first and use the refusal/control cases to show its boundaries. Avoid claims of unique industry superiority, production readiness, universal product delivery or a model winner.

## Data and decision dependencies

The current frozen catalogue benchmark passed 52 brand/budget cases repeated three times. It also shows 116 of 175 products missing structured brand/category fields. That is a data-quality limitation, not a semantic-retrieval benchmark win.

A real market decision still needs the platform owner to identify the tenant and SKU/lane, where current supplier/sales data lives, and the actual decision to support. Forecast evaluation needs observed outcomes rather than fabricated zero-demand history. These cannot be substituted with demo mappings or seeded findings.

CONTINUITY/RAFT/Graphiti, larger models, a new graph database and broad forecasting work remain deferred until a relevant measured failure and valid comparison dataset justify them. The updated priority is: **preserve the work, prove scoped delivery, enforce pilot authority, then scale coverage and evaluate infrastructure.**
