# Engineering walkthrough

A ten-minute guide for engineers and hiring managers, reviewed **23 October 2026**. The [current status and roadmap](../REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md) separates committed evidence, local work and proposed changes.

ShopSquire is substantially AI-assisted, using Claude Code and Codex. The author's work includes specifying architecture, directing implementation, reviewing changes and requiring evidence. This guide does not claim that every line was independently reviewed or every repair followed test-first development.

## The engineering problem

What may a commerce assistant claim or do when a buyer's request, inventory, supplier messages and external sources disagree?

```text
observations -> evidence -> hypotheses -> proposals -> authorization -> execution
```

A model's proposal is an input to deterministic checks. Tenant, case, revision, evidence validity, commercial constraints and explicit authorization determine what can progress. This is a working prototype with useful bounded workflows and substantial unfinished integration.

## Read these six files

| File | What to inspect |
|---|---|
| [recommendation_core/core.py](../../src/app/services/recommendation_core/core.py) | `_recommend_turn`: routing, retrieval, stage composition and response construction. |
| [stage_runner.py](../../src/app/services/recommendation_core/stage_runner.py) | Exception recording and cancellation. The publication base does not snapshot/roll back mutations; that implementation is local work. |
| [typed_stage_coordinator.py](../../src/app/services/recommendation_core/typed_stage_coordinator.py) | Pre-execution phase-order validation. Dependency-ID validation and blocked-dependency propagation are local changes. |
| [post_retrieval_stage_plan.py](../../src/app/services/recommendation_core/post_retrieval_stage_plan.py) | Declared fit/commercial/response dependencies and artifact references. |
| [turnOracle.ts](../../frontend/e2e/helpers/turnOracle.ts) | Scenario-defined checks across response, case, trace and authority surfaces. |
| [research_trigger_decision.py](../../src/app/services/recommendation_core/research_trigger_decision.py) | Research eligibility versus permission to run an external action. |

The [ASCII architecture](../architecture/CURRENT_ARCHITECTURE_2026-10-23.md) adds identity, memory, stores, workers and side-effect boundaries.

## What a turn does

1. Admit the request under an identity and tenant/case boundary.
2. Interpret intent; a configured model can propose a typed route and requirements.
3. Validate the proposal against deterministic contracts and retrieve candidates.
4. Execute fit and commercial stages with dependencies and recorded outcomes.
5. Adjudicate accepted evidence and construct an answer or refusal.
6. Record trace/case state; proposed commercial effects have separate approval/execution boundaries.

Receipt names and fields are inspectable contracts, not proof that every route emits every receipt. A stage reporting `ok` establishes that it ran without its guarded exception; it does not establish a useful answer or qualified product.

## What is demonstrated

| Result | Evidence and scope |
|---|---|
| Corrections survive reload | Seven buyer-only memory scenarios, including a longer correction conversation. A test-setup overlay removes operator headers. |
| A shortfall becomes a retained draft | Native buyer: 40 requested / 15 available / 25 short. Supplier contact is still required; dispatch is false. |
| Authority and failure boundaries are testable | Typed-stage unit tests, security controls and actor-aware browser checks. Attachment and legacy actor flows still fail. |
| Current market stock respects event validity | Native PostgreSQL and SQLite controls. This does not complete source admission or ordinary-chat citations. |
| Broad integration remains red | Python: 8,237 P / 3 F / 280 item skips plus 4 collection skips. Browser: 41 P / 68 F / 32 skips. Different source revisions. |

The [evidence index](../REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md#evidence-and-reproduction) links complete committed ledgers, hashes, scope and failure evidence. Private `.artifacts/` folders are not required to assess those retained results.

## Review hypotheses and open work

Claude proposes separating ordinary preference browsing from evidence-qualified workload recommendations. A reported university-laptop conversation returned no products despite successful routing. That is a review observation, not a newly reproduced result in this publication. A universal impossibility or completed two-mode implementation is not established.

| Review candidate | Required next evidence |
|---|---|
| Dependency failure suppresses useful responses in the local coordinator | Identify dependent outputs that must stop and independent advice that may safely remain. Do not bypass failed fit dependencies. |
| Snapshot `deepcopy` escapes the local guard | Reproduce with a supported response value; design a bounded snapshot contract before integrating the local change. |
| Approved evaluation baseline lacks a production writer | Establish approved-baseline lifecycle with valid positive and refusal controls. Missing approval should fail closed. |
| Unpriced sibling blocks category approval | Establish cost-policy intent and a useful unknown-total explanation; preserve cost authority. |
| Optional procurement fetch erases the panel | Reproduce secondary failure with valid primary state; show partial/error state without masking authorization denial. |

Some reviewed code is local work rather than the published source. The [review disposition](../REPOSITORY_STATUS_AND_ROADMAP_2026-10-23.md#claude-review-disposition) makes that distinction. Live research, external mail/ERP, distributed privacy/recovery, deployed independent-person approval and endurance remain open. No real-world business uplift is established.

## Reproduce and interpret green

Follow the [README setup](../../README.md#reproduce-a-focused-check), then use that environment's Python:

```powershell
python -m pytest tests/services/test_typed_recommendation_stage_coordinator.py tests/services/test_local_model_roles.py tests/services/test_research_policy.py -q
python scripts/check_source_file_sizes.py
python scripts/check_function_sizes.py
```

The dated publication assessment records the focused result and architecture-ratchet output. A function-growth failure remains a failure; ceilings were not increased for publication.

Green means the intended assertion executes for the intended actor, source, installation and prerequisites. A valid refusal cannot replace a positive workflow. A mock validates its seam; a skipped prerequisite validates no execution; coverage measures exercised lines rather than task quality. Release green requires all required profiles on one frozen source plus recovery, rollback and endurance evidence.

For TDD, retain an intended-behavior assertion failing on the parent, then show it and relevant negative controls passing after repair under the same limits. Existing regressions and review observations should be labelled accordingly. This publication improves presentation and CI setup; it does not claim to repair the remaining product gaps.
