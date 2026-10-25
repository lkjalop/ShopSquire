# ShopSquire portfolio roadmap — 26 September 2026

## Scope decision

**Inventory follow-up:** [The electronics-shop roadmap](ELECTRONICS_SHOP_ROADMAP_2026-09-26.md) refines the ordering after inspecting the owner's August catalogue and reproducing import defects. Use that existing broad catalogue; the three invented SKUs suggested below were a minimal example, not a requirement to replace available products. Catalogue normalization and a consistent operational dataset now precede broad journey testing.

The owner clarified that ShopSquire is a learning and portfolio project, with synthetic data and no expected commercial customer. A real tenant, private supplier feed or real sales history is therefore **not a prerequisite for completing the portfolio**. Earlier roadmap requests for those inputs are superseded for this scope. They remain prerequisites for claims about actual business impact or real-world forecast accuracy.

Build a reproducible demonstration with honest provenance, meaningful negative cases, traceable decisions and fake effect providers. Customer onboarding, production commerce and commercial readiness are optional future projects. This scope change does not waive correctness, authorization or recovery tests.

## Complete ordered roadmap

“Partial” means useful implementation/evidence exists, not that the exit gate has passed. Historical test results are not a fresh end-to-end certification.

| Order | Work | Current evidence | Completion gate |
|---|---|---|---|
| 1 | Preserve and reproduce | Local checkpoint/restore and bounded runtime checks recorded; full clean dependency installation and off-device recovery remain separate. | Recoverable reviewed snapshot; clean installation, migrations, seed, startup and test commands; record exact runtime/dependency versions. |
| 2 | Persist explicit requirement selection | Contract selection service and migration added; seven service tests cover persistence, ownership, revision changes and revocation. | API and buyer UI select/reload/revoke a tenant/case/revision-bound contract; concurrent stale writers rejected; browser clickthrough passes. |
| 3 | Revalidate when evidence is used | Coverage/compiler gates exist; persistence service can reject stale bindings. | Actual research and qualification consumers enforce binding, applicability, freshness and revocation, including changes while research is running; no fallback around a failed gate. |
| 4 | Deliver one bounded product journey | Blender obligation diagnosis and parser repairs exist; held manufacturer observations do not establish real qualification. | One explicitly labelled synthetic positive journey plus missing/stale/wrong-version/refused cases agree across API, UI and trace. Keep real-publisher Blender qualification as a separately evidenced milestone; never relabel synthetic fixtures as verified manufacturer evidence. |
| 5 | Keep the core agnostic | Data-owned contracts and general gates exist; active V2 still has large functions and domain assumptions. | Extract terminal/research/contract responsibilities under behavior tests; keep publisher/domain adapters separate; use a second synthetic domain to detect hidden laptop or Blender assumptions. No arbitrary intent-to-hardware rules. |
| 6 | Demonstrate distinct-person approval | Spend-tier helper exists; complete authenticated-person enforcement is not established. | Server-controlled synthetic principals; two credentials for one person cannot self-approve; wrong tenant, inadequate role and changed/expired/revoked approval rejected again at dispatch. Fake providers only. |
| 7 | Finish effect integrity and recovery | Several replay/refund/message controls and tests exist; complete sink coverage remains open. | Inventory every externally visible mutation; test exact payload, expiry, revocation, retries and crashes before/after provider acceptance. Reconcile uncertain outcomes and reservations without duplicate effects or false completion. |
| 8 | Govern search and resist injection | Source controls and research tests exist; universal disclosure/effect protection is not established. | Consented useful, empty, denied and unavailable research; webpage/OCR/email/cached/direct attacks cannot expand permissions, leak canaries or trigger unauthorized fake effects. Verify network boundaries, not just model refusal text. |
| 9 | Prove browser journeys | Three prior complete image cycles passed using one repeated image; continuity passed. New contract flow has no browser evidence yet. | Playwright clicks selection, research, revision change, revoke, failure, cancellation and simulated approval flows through the real API. Preserve traces/screenshots; identify any mocked dependencies. |
| 10 | Extend reliability evidence | Mixed-model run: 45 calls in roughly six minutes; not sustained certification. | Predeclare thresholds; run at least 60 minutes with varied images, cold/warm starts, cancellation, failures and restarts, then an overnight run. Record elapsed time, every failure, queue/transport/end-to-end timing and bounded model residency. |
| 11 | Show one useful simulated market decision | No real tenant is available or required for the revised portfolio scope. | Fictional shop and exact synthetic SKU mapping; replayable stock/demand/supplier observations; compare a simple baseline with evidence-informed replenishment, wait or alternative sourcing. Explain correct abstention as well as changes. |
| 12 | Benchmark and automate release checks | Small model comparison establishes no quality winner. CI and image publishing workflows exist; remote success and deployment/rollback not established here. | Frozen held-out scenarios, declared metrics, unseen failure cases and reviewed labels. Local and remote CI evidence; reproducible release artifact. Demonstrate local/staging rollback if claiming CD. Real-world utility and forecasting remain unproven without real outcomes. |

Portfolio completion requires the relevant exit gates above, not merely files or workflows existing. A future commercial release additionally needs actual identity administration, customer-specific policy, operational ownership and real-data validation.

## Recommended fictional shop and market demonstration

Use `portfolio-shop` and the existing August catalogue, with a small reviewed subset for the first journey and the broader catalogue for cross-category tests. Attach clearly labelled fictional stock, supplier and transaction records. Start with one decision: **should the shop replenish this exact SKU now, wait, or choose another approved supplier?** A SKU is simply a shop's identifier for one exact product configuration; a tenant is the isolated workspace for that shop.

Minimum input dataset: current and reserved stock, daily synthetic sales and returns, open orders, supplier lead time, unit cost/currency, region and observation/publication timestamps. Retain a fixed generation seed, scenario version and source IDs. Add a second tenant fixture to test isolation, not a second business showcase.

Use independent scenarios: normal supply; a supplier delay; stale data; contradictory quotes; wrong-region/currency observations; revoked mapping; and a malicious instruction embedded in supplier text. Compare against a documented simple stock-coverage/reorder baseline. Keep some scenarios out of tuning. Generated history supports controlled experiments, not a claim that a forecast predicts real customers.

Every screen/report should distinguish synthetic observations, captured public material and unavailable evidence. Public manufacturer material may support product facts if accepted through the governed path; it does not become evidence of demand, sales or supplier availability.

## Approval options explained

Approval asks two different questions: “Who are you?” and “Are you allowed to approve this exact action?” Different logins are not necessarily different people.

| Option | What it demonstrates | Recommendation |
|---|---|---|
| Simulated people and fake providers | Permission boundaries, audit trail, separation of duties and recovery without external effects. | Implement first. You may act out both fictional roles, clearly labelled as simulation. |
| Test accounts with a real login provider | Integration with authentication, sessions and centrally managed identities. | Optional extension after the demo works; two accounts alone still do not prove two actual people. |
| Real employees and commerce | Actual operational approval with genuine identity and organization-specific rules. | Outside the present portfolio scope. |

Suggested initial demo policy: reading and drafting need no second person; every simulated send, purchase, refund or stock mutation needs an authorized different person. Model identity with a stable server-controlled `person_id`; multiple credentials may map to the same person. Never accept the approver's identity or role merely because the browser supplied it.

If demonstrating spend escalation, use configurable, explicitly illustrative AUD bands: up to AUD 1,000 requires a different manager; above AUD 1,000 requires a different owner. These are demo choices, not legal requirements or industry standards. Unknown amount/currency is held for review; non-monetary actions still need approval. The existing default tier ladder is different and opt-in: this paragraph is a proposed demo policy, not a claim it is already configured or enforced.

Approval binds the recipient/provider, action, exact configuration, quantity, amount/currency, tenant, case revision and payload digest. Editing any material field requires a fresh approval. Dispatch rechecks person separation, permission, expiry and revocation. Provider acceptance and confirmed completion remain separate states. Use a fake outbox and fake payment provider; a “demo” label alone must not permit real network effects.

## Testing and experience claims

- **TDD:** Write the expected behavior test first, observe a meaningful failure, implement the smallest fix, then refactor with checks green. The current selection batch has recorded initial missing-module red evidence and seven green behavioral tests. Other historical tests may have been added after implementation; call the overall approach TDD-informed rather than claiming every feature was test-first.
- **Testing:** Unit tests check rules; integration tests check components and database behavior; Playwright exercises actual browser interactions. Fault and security tests check failures and abuse. A fixture-only pass is not live-service proof.
- **Harness engineering:** Build the machinery that makes tests repeatable: isolated data, fixed configurations, fake providers, runtime bounds, reset scripts, traces, metrics, deadlines and failure injection.
- **Loop engineering:** Design how the agent moves from a request to research, validation, action and observation, including when to retry, ask for input, replan, stop or refuse. Version changes and revocation must invalidate old authority.
- **CI/CD:** CI runs checks automatically when code changes. Delivery packages a releasable artifact. Deployment installs it into an environment, and rollback restores a known version. Workflow files and container publication do not by themselves establish operated production deployment.

Suggested portfolio wording, provided you can explain the design and reproduce the evidence:

> Built and iteratively tested an AI-assisted commerce research prototype using regression and integration tests, selected test-first development cycles, and Playwright browser journeys. Developed reproducible test harnesses and agent lifecycle controls for evidence validity, changing requirements, bounded execution and effect safety. Configured CI checks and container publishing workflows, using synthetic business data and simulated external providers.

Describe your own role accurately: requirements, architecture decisions, directing and reviewing AI-assisted implementation, running experiments, interpreting failures and verifying behavior. Do not imply that all code was manually authored, that all approval gates are finished, or that this prototype has served production customers.

## Verification for this update

Fresh local run: 37 tests passed across case binding, requirement contracts and contract compilation, with no failures or skips; the test bootstrap migrated SQLite through `20260880_case_contract_selection`. Evidence: `.artifacts/roadmap-tdd-2026-09-26/scope-review.xml`. This verifies service/compiler behavior; no browser run, real identity integration, sustained run or commercial readiness is established by this result.
