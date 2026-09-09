# Scope, evidence and trace repair — 2026-09-09

Status: local engineering checkpoint, **not a production release certificate**.

## Confirmed changes

- Evidence compilation pins a tenant/product-type/relationship/manifest scope. Numeric-only evidence cannot establish complete hardware compatibility.
- Literal publisher CPU/GPU/OS text keeps its source spans. Unreviewed VRAM translations remain derived and cannot gain publisher authority.
- Exact enumerated compatibility alternatives require matching cited spans. No relative CPU/GPU performance equivalence is inferred.
- Completeness is evaluated separately by workload name/version and manifest scope, not by combining unrelated claims into a complete checklist. Stable provider identity migration remains desirable.
- Chat preflight stages typed case amendments; the terminal reducer performs the durable commit. The independently callable procurement amendment path retains its own persistence behavior.
- Explicit purchase-category changes use the existing taxonomy boundary and cannot be masked by a budget amendment. Immediately negated category nouns do not become positive purchase requests.
- Current trace selection uses the current terminal trace ID, not a retained ambiguity/case trace. Research summaries recognize terminal-only outcomes.
- Audit displays persisted shopping-turn read models separately from procurement decision runs. Revision changes refresh history; timeouts no longer leave the hook loading indefinitely.
- Decision history queries enforce tenant and valid/knowledge-time filters. Empty results stay empty; database errors return 503 rather than trying unfiltered or alternate databases. Equivalent timezone cutoffs normalize to UTC; invalid cutoffs return 422.
- Source ownership is labelled as source ownership, not blanket evidence verification. Empty matching SKU arrays no longer display “Verified.”
- Completion-cache checks now reuse the tenant/case/explicit-turn reader; foreign cached completion events cannot suppress current research. Both tenant and case regressions failed before the repair.

## Owned boundaries

- `src/app/services/recommendation_core/requirement_scope.py`: manifest resolution and relationship scoping.
- `src/app/services/recommendation_core/requirement_compiler.py`: claim validation and typed predicates.
- `src/app/services/research_outcome.py`: completeness and terminal authority.
- `src/app/services/procurement_case_preflight.py`: staged versus persisted amendments.
- `src/app/services/turn_transition.py`: operation-bearing read model.
- `src/app/services/shopping_case_trace_reader.py`: recorded case evidence and turn history.
- `src/app/routers/decisions.py`: bounded historical query.
- `frontend/src/components/decision-trace/TurnHistoryPanel.tsx`: historical revision selection.
- `frontend/e2e/live-turn-trace-continuity.spec.ts`: live, non-mocked three-turn/all-panel gate.

Extracted without changing size ceilings:

- Shopping-case HTTP schemas → `src/app/schemas/shopping_case.py`.
- Excluded-SKU/budget projection → `src/app/services/catalog_shortfall_projection.py`.
- Operator outbound queue endpoints → `src/app/routers/fulfillment_outbound.py`.
- Chat transport/persistence/projection → existing owned service modules.
- Chat cart response and image security → `chat_cart_projection.py` and `chat_image_security.py`.

This closes the file-size guard, **not** the larger monolithic orchestration-function design debt.

Source anchors at this checkpoint: scope resolution `requirement_scope.py:26`; compiler entry `requirement_compiler.py:41`, exact alternatives `:139`; per-workload completeness `research_outcome.py:283`; staged amendments `procurement_case_preflight.py:19`; scoped completion check `shopping_case_trace_reader.py:122`; UTC historical cutoffs `decisions.py:485`; V2 ranking bridge `recommendation_facade.py:839` and invocation `:1414`.

## Verification receipts

Artifacts are outside source control at `C:/AI/ShopSquire-checkpoints/pilot-review-20260909`.

- Pre-extraction broad service/architecture run: 4,417 collected; 4,410 passed, six skipped, one size-guard failure.
- Frontend unit suite: 360 passed. Subsequent focused UI regressions passed.
- Production frontend build passed.
- Compiler → real fit engine → terminal gate positive fixture passed with complete accepted exact requirements and matching stock. This is controlled backend evidence, not live publisher performance-equivalence certification.
- Three-turn live browser: PRAGMATA → computer chair → ten laptops. All 15 trace panels inspected on every turn, unique terminal trace/operation references, recorded history visible, zero dispatch requests. Passed with zero retries before and after extraction (1.7 and 1.6 minutes respectively).
- Outbound extraction: fulfillment service suite and endpoint-ownership tests passed.
- Shopping-case extraction: 32 API/projection tests passed after replacing a partial hand-written schema fixture with the real conversation migration.
- Chat extraction characterization: 38 passed, including unchanged architecture ceilings and cart confirmation boundaries.
- Historical filtering: retroactive correction, tenant isolation, timezone equivalence, invalid dates, empty result and database failure covered.
- Full post-extraction services/architecture suite: 4,416 passed, six skipped, zero failures (4,422 collected). Detached clean-checkout gate: 179 passed.
- Final frontend unit suite: 361 passed; production build passed.
- Live chair, unrelated-query and bulk-stock checks: three passed, zero retries. These check stock accounting, not the complete draft-only shortage certificate.
- Stronger four-turn browser gate: passed, zero retries (2.1 minutes). The quantity amendment stays in the same case and advances exactly one revision; selecting the prior historical revision shows its prior operation, then selecting current shows the new operation.
- The first stronger browser attempt failed under concurrent suite load: history retrieval exceeded the UI deadline. A direct read found the persisted turn. Added a failing UI regression, corrected unavailable-versus-empty narration and exposed an explicit retry. The original failed receipt is retained, not erased by the subsequent passing run.
- Integration rerun exposed an obsolete assertion: a no-requirements fixture expected resolved fit. It now requires context-only identity, blocked fit and no products while retaining the additive-workload assertions.
- Final integration run: 94 passed, eight skipped, zero failures. After the completion-cache correction: 101 acceptance/history/architecture tests passed, zero failures.

## Not certified / still open

1. Arbitrary CPU/GPU performance translation and reviewed derivation policies; exact alternatives are not a performance ranking system.
2. A live complete-evidence → qualified SKU browser journey. PRAGMATA remains honestly partial; the controlled backend positive test is not a substitute.
3. Separate live budget/stock shortfalls and explicit draft-only sourcing with durable zero-dispatch proof.
4. Correction to the earlier assessment: ranking is wired through `recommendation_facade._run_v2_intelligence_stage` (not directly in core). Treatment/control integration tests now pass both in the suite and in isolation with temporary flags. This is not a live effectiveness certificate.
5. Human source/claim reviews, including Rockwell. No approvals were performed.
6. PostgreSQL and hosted clean-machine release certification; local SQLite and a clean checkout on this laptop are not those gates.
7. Persisted production WORM/anchor certification. Recorded turn history and two-coordinate decision queries are useful temporal coverage, not certification of the entire audit pipeline.
8. Publication/review of cross-category database manifests, packaging semantics and full stable provider/concept IDs. Scoped hardware checks do not certify pharmacy, groceries or coffee procurement.

## Checkpoint policy

Source checkpoint `34f69a94` includes the previously untracked compiler module and tests. No databases, screenshots, logs, credentials, supplier sends or source approvals are included. Historical assessment documents remain dated evidence, not endorsements that all their proposed repairs are complete. No remote push was performed.
