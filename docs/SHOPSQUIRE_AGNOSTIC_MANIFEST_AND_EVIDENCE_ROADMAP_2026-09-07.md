# Agnostic manifest, evidence and buyer-delivery roadmap

Independent assessment, 7 September 2026. This is a repair plan and diagnostic receipt, not release certification. Line anchors refer to the inspected working copy; they will move after extraction.

## 1. Executive assessment

The proposed direction is correct, but category scoping alone is insufficient. Reorder around a single scoped compilation contract, dimensional validation and preserved evidence lineage before expanding categories or refactoring the large router.

The platform has useful reusable parts: typed research contracts, attribute definitions, tenant/store profiles, catalog scope, evidence observations, accepted-catalog projection and terminal outcomes. It does not need another title list or a second orchestration framework.

However, its current compiler is not product-type scoped, the exact configuration model is hardware-oriented, and the outcome reducer still reconstructs truth from heterogeneous dictionaries. Installing a pharmacy attribute pack does not establish a safe pharmacy procurement capability. Coffee and grocery attribute/profile packs were not found among the installed three verticals.

The model should propose subject, relationship, candidate identity and cited facts. Reviewed manifests and policy should determine units, permissible comparisons and authority. Inventory determines availability, not meaning, safety or source verification. An unknown or out-of-catalog product must not silently become an office laptop.

## 2. What was tested in this assessment

### Focused regression suites

Ran the existing attribute-registry, requirement-compiler and research-outcome suites: **34 tests passed**, exit 0. They do not cover the boundary failures below.

Ran the source-size architecture guard: **failed**, with unchanged ceilings:

| File | Actual lines | Ceiling |
|---|---:|---:|
| `src/app/routers/chat.py` | 5787 | 5049 |
| `src/app/routers/fulfillment_cases.py` | 2574 | 2447 |
| `src/app/routers/shopping_cases.py` | 2397 | 2073 |

Other oversize warnings are not the same as new ceiling violations. Do not claim the architecture gate is green.

### Direct compiler probes (executed, not hypothetical)

Each probe supplied an accepted, provenance-bearing test claim; no live evidence was approved.

| Input | Actual result | Defect |
|---|---|---|
| `storage_gb >= 40` | Rejected: `attribute_not_registry_authorized` | Variant role excludes a legitimate fit use |
| `strength_mg >= 10`, no product/tenant scope | Compiles | Installed verticals are treated as global authority |
| `ram_gb contains 16` | Compiles | Operator whitelist is not type-specific |
| `ram_gb >= 16`, separate `unit=mg` | Compiles as `16 GB` | Separate source unit is ignored |
| Multiple attributes from one source record | Same upstream `source_claim_ids` | Source record identity is not predicate identity |
| `approved_tenant_document` input | `verification_status=verified` | Acceptance and verification need independent semantics |

The frontend structured-claim projector already hashes distinct predicate IDs. That is progress, but it does not repair the upstream provenance references or the unconditional `verified_official` label.

### Browser diagnostic

Real local browser, live server, fresh buyer sessions, one Chromium instance with GPU disabled. Diagnostic script and raw outputs are outside the source tree:

`C:/AI/ShopSquire-checkpoints/test-isolation-20260907/trace-assessment.cjs`

`trace-assessment.json`, `trace-assessment.png` and preserved earlier attempts live alongside it. Two diagnostic selector errors were corrected (ambiguous label, then a mobile-only hidden select). A later run uses visible desktop section buttons. This is not a zero-retry release certificate. The initial 15-panel capture was mostly empty; a delayed capture is assessed separately below.

The earlier positive PRAGMATA delivery gate remains red: provider evidence existed, but partial compilation blocked qualification. This assessment does not change that gate or approve sources to produce shelves.

### Delayed browser result: all panels open, semantic certification fails

The completed diagnostic waited 30 seconds after opening Trace and bounded waits for audit/replay loading. All 15 panels opened; no API HTTP >=400 response was observed by its listener. Trace `7d196166-5aa8-4183-a8f2-9b087b41d935`, displayed case revision 2, budget AUD 2,500. The screenshot was visually inspected. This is one local PRAGMATA journey, not a cross-category or production certificate.

| Panel | Observed result / assessment |
|---|---|
| Summary | Model-directed router, 10,153 ms; **Canonical slate: Verified** despite blocked catalog and no products. No tools recorded despite provider research. Misleading summary |
| Events | Ten raw events available; visible interpretation-completed event. Opening succeeds, but one revision/one execution is not proved by this display |
| Execution | Structured connector resolved and compilation partial, followed by a separate concept branch empty/blocked. Branch history is useful but needs clear superseded versus terminal labeling |
| Research Breakdown | PRAGMATA; Parsed 2, Accepted 2, Rejected 0; partial, blocked. Below it: plan not executed, and another line says catalog qualification. Rejected compiler attribute is not counted |
| Why | PRAGMATA at 1080p still unresolved, no authoritative evidence, local/remote clarification. Contradicts researched identity; local-searxng leg says not configured/unavailable |
| Intent | Only Lane: filter. Does not explain product/workload relationship or performance target |
| Memory | No events; insufficient for a continuity certificate |
| Complexity | qwen3:14b identified, score 1/10; technical keyword `rag` appears for PRAGMATA, a misleading substring-derived explanation |
| Evidence | No evidence legs ran. At minimum the label is too broad: structured research is visible in the neighboring panel |
| Multimodal | Mostly placeholder fields, no image scan. Text-only turn should have compact explicit N/A |
| Security | Correctly distinguishes text from image checks. Shows text controls completed; this run does not exercise URL/redirect security |
| Market Intelligence | No scoped projection; consistent with no qualified products |
| Procurement | No procurement activity, economics unavailable. Plausible for this non-bulk turn; not a supplier-send certificate |
| Audit Trail | No revisioned decision run available; local SQLite/WORM chain not populated is explicitly disclosed. Durable revision audit not certified |
| Raw | Replay loads with empty tools and old no-requirements recommendation; not fully reconciled to researched terminal evidence |

The inspected screenshot additionally shows the buyer claim card **gpu vram gb >= 4 GB, verified official**, alongside the blocked/partial outcome. It also shows chat compressed into a very narrow column beside the claim card at this viewport. The authority/provenance label is a correctness issue; responsive layout is a separate UX issue.

External research is therefore **not uniformly broken or uniformly certified**: structured-provider evidence was obtained in this journey, while its separate open-world leg reported unavailable/not configured. No claim of general external-search readiness follows from this run.

## 3. Relevant code map and the changes it needs

| Boundary | File and anchor | Finding / intended responsibility |
|---|---|---|
| Installed definitions | `src/app/services/attribute_registry.py:44` | Enumerates installed verticals, not current governed product scope |
| Definition schema | `src/app/services/attribute_registry.py:54` | One `role`; replace authority use with explicit allowed uses while preserving legacy reading during migration |
| File loading and union | `src/app/services/attribute_registry.py:69`, `:101` | Cached JSON; first definition wins collisions. Resolve a pinned manifest rather than union all packs |
| Derivations | `src/app/services/attribute_registry.py:156` | Carry derivation rule revision, inputs and conditions with every derived value |
| Unit normalization | `src/app/services/attribute_registry.py:190` | Normalize structured value + explicit unit together; reject incompatible dimensions |
| Predicate evaluation | `src/app/services/attribute_registry.py:383`, `:405` | Type-specific operators and unknown/inapplicable outcomes |
| Compiler | `src/app/services/recommendation_core/requirement_compiler.py:31` | Missing tenant/product/manifest/relationship context |
| Global authorization | same file `:36`, `:72` | All packs unioned; role-based fit/regulatory test |
| Source identity | same file `:41`, `:43` | Record ID reused; rejection lacks attribute, value and scope context |
| Value and verification | same file `:81`, `:112` | Unit not passed to normalization; verification assigned unconditionally |
| Research types | `src/app/services/recommendation_core/research_contracts.py:466`, `:490` | Extend existing EvidenceClaim/CompiledRequirement, not a parallel claim language |
| Structured-provider adapter | `src/app/services/recommendation_core/workload_grounding.py:48`, `:68` | Hardware minimum extraction and GPU translation mixed with official claim creation |
| GPU comparison | `src/app/services/gpu_translation.py:66` | Derived desktop/mobile comparison must not masquerade as quoted publisher minimum |
| Frontend claim projection | `src/app/services/structured_requirement_claims.py:9` | Predicate IDs are improved; authority label remains unconditional |
| Outcome reducer | `src/app/services/research_outcome.py:168` | Replace recursive shape discovery with explicit ledger/projection input |
| Counts | same file `:197`, `:209`, `:216`, `:218` | Max-count heuristics are not unique claim accounting; nested rejections omitted from rejected count |
| Completeness | same file `:235` | Section completeness is not fulfilled compatibility obligations |
| Terminal prose | `src/app/services/terminal_research_narration.py:33` | Narrate the final typed result, including held, derived, rejected and missing obligations |
| Tenant profile | `src/app/platform/store_profile.py:36`, `:79` | Context/env/default and file-backed profile; pin revision in the operation |
| Request profile boundary | `src/app/platform/store_profile_middleware.py:40` | Existing context isolation should be retained and tested across async tasks |
| Tenant registry | `src/app/platform/tenant_registry.py:127` | Ensure authenticated tenant authorization, not a freely chosen client profile, determines permitted manifests |
| Separate CV/rule packs | `src/app/policy/vertical_pack.py:12`, `:50` | Existing versioned pack abstraction for rules/CV, with unknown-pack electronics fallback. Reuse relevant concepts, but do not mistake it for scoped procurement compilation |
| Catalog scope | `src/app/services/case_catalog_candidates.py:32`, `:83`, `:166`, `:195` | Existing scope; generalize category relationships using reviewed taxonomy data |
| Exact configuration | `src/app/models/orm.py:34` | Hardware-shaped fields; preserve adapter compatibility while adding generic product/variant/offer identity |
| Observation ledger | `src/app/models/orm.py:76` | Existing provenance-bearing observations are a reusable base, not missing storage altogether |
| Accepted catalog projection | `src/app/services/accepted_catalog_projection.py:61`, `:265`, `:371`, `:426` | Evaluate scoped claims, freshness and inventory separately; preserve missing vs failed evidence |
| Existing packaging arithmetic | `src/app/services/procurement_decision_context.py:58`, `:183` | Pack-size replenishment exists; not a general dimensioned packaging manifest |
| Chat adapter seams | `src/app/routers/chat.py:3778`, `:5365`, `:5607`, `:5664` | Claim projection, commit and terminal/scope assembly must share the pinned contract |
| Frontend projection | `frontend/src/App.tsx:2465`, `:2688`, `:3777` | Architecture alternatives and claims are wired; rendering correctness requires evidence tests |
| Trace state | `frontend/src/components/DecisionTrace.tsx:359`, `:477`, `:2140` | Legacy inferred strip plus canonical override; assess delayed and terminal state, not just button presence |
| Trace navigation | `frontend/src/components/decision-trace/traceNavigation.ts:8` | Six sections, 15 leaf panels |
| Misleading panel summaries | `frontend/src/components/DecisionTrace.tsx:2432`, `:2509`, `:2655` | Slate, tools and evidence-leg labels need terminal-bound semantics |
| Complexity explanation | `src/app/services/llm_provider.py:181` | Keyword explanation produced `rag` for PRAGMATA in this run; not reliable semantic reasoning |
| Definition data | `data/attributes/electronics.json:47` | Storage currently variant-only |
| Sensitive unit data | `data/attributes/pharmacy.json:4`, `:7`, `:13` | Generic IU-to-mass factor and pack alias need explicit substance/package applicability review; do not use as universal equivalence |

These are repair anchors, not a claim that every module needs rewriting. The missing capability is a consistently consumed scoped manifest contract, not absence of all manifest-like or evidence code. There are also five separate CV/rule packs (electronics, fashion, home_garden, luxury, sports); the three installed attribute packs and store profiles are a different inventory. Their inconsistent coverage is another reason to resolve capabilities explicitly rather than assume a vertical name implies full support.

## 4. Reordered roadmap

### P0-A — Characterize and pin the contract

Add failing tests for the six probes above before production changes. Capture the current browser failure with full terminal, claims and scope. Pin `tenant_id`, `case_revision`, `product_type_id`, `manifest_id`, `manifest_revision` and `relationship` (purchased item versus host/workload) in the existing turn contract.

An unresolved product type must yield an explicit unresolved scope. Do not choose electronics merely because it is the default storefront. A laptop for a coffee business is a hardware purchase with business context; coffee for that business is not.

### P0-B — Scoped definitions, permitted uses and typed units (one vertical slice)

Replace compiler-wide union with an explicit manifest resolver. Attribute definition describes type, dimension and canonical unit. A separate policy declares allowed uses: variant selection, fit, offer comparison, regulatory check. Merely defining a regulatory attribute does not grant regulatory authority.

Validate operator by attribute type and use. Validate structured source units; keep conversions explicit and versioned. Reject cross-category attributes, invalid operators and unit mismatches with distinct typed codes. Do not fix storage by relabeling every variant attribute as `fit`.

Start with the existing electronics manifest to reproduce the positive/negative behavior; add synthetic coffee/grocery manifests as tests of generality. Keep reviewed JSON import/export, but introduce immutable published manifest revisions in the governed persistence layer with tenant/category associations. Do not move unvalidated JSON blobs into PostgreSQL and call that governance.

### P0-C — Evidence lineage and authority

Give observed predicates stable identities distinct from provider records. Derived predicates cite input claim IDs, transformation/version and applicability. Approval is a separate record naming actor, scope and timestamp; verification is a separate policy verdict. Preserve original units, source spans, source revision and publication/observation times.

In particular, preserve the publisher GPU model alternatives and literal VRAM. A comparison-table mobile threshold is a derived heuristic, not an official minimum. GPU VRAM alone is not GPU performance compatibility.

Remove blanket `verified` / `verified_official` assignments from adapter paths. Retain observed, held, case-accepted and independently verified distinctions. Keep commerce authority separate.

### P0-D — Category-specific obligations and one outcome

Start the trace characterization tests alongside P0-A. The reproduced Summary/Why/Evidence contradictions must be fixed in this P0 outcome slice, not postponed as cosmetic frontend work.

Define a manifest-owned obligation set with applicability conditions and evaluator capabilities. Hardware may need CPU/GPU model compatibility, OS, API, architecture, storage medium/capacity and target constraints; coffee may need roast/product identity, net mass and pack count. Neither should inherit the other's checklist.

Not every attribute is mandatory in every journey. Buyer preferences do not become blocking compatibility obligations. Minimum/recommended document sections and number of parsed claims do not prove coverage.

Reduce typed ledger rows by claim ID, not max counts across arbitrary dictionaries. Include rejected claims and unmet obligations in the terminal result. Generate chat, shelves, questions and trace from that revision. A rejected irrelevant claim need not block otherwise complete fit; a missing critical requirement must block even if no parser rejection occurred.

### P0-E — Buyer-delivery and shortfall gates

Prove accepted complete applicable evidence + permitted matching stock produces a non-empty qualified shelf. Prove held/partial/incompatible evidence stays restricted without erasing useful observed evidence.

Distinguish technical incompatibility, missing verification, out-of-category, budget gap and stock shortage. A sourcing draft may preserve constraints and best alternatives, but explicit buyer confirmation is required; supplier sending remains human-authorized and is tested independently.

### P1-A — Broader products and packaging

Keep shared product, variant, offer, inventory/lot and packaging identities separate. A pack is a product-specific relation, not a universal base unit. Support exact decimal mass/volume conversions and declared pack hierarchies. Do not infer volume-to-mass conversion or ingredient/substance equivalence from a generic unit alias.

Coffee/grocery schema should cover only reviewed requirements relevant to the tenant (for example net contents, count, origin/roast or storage/expiry facts), with source and freshness policy. Pharmacy needs a separate qualified policy review before enabling regulated claims, substitutions or actions. An installed inventory row is not permission to make clinical recommendations.

Unknown/unstocked products should become clarification or explicit out-of-catalog sourcing offers, not a broad match against every SKU. Unrelated questions must not start procurement.

### P1-B — Extract only after behavior is sealed

Extract terminal projection from chat first, then research orchestration into existing owned boundaries. Keep a single execution and revision compare-and-set; keep database transactions out of bounded network work. Move hardware-specific interpretation behind a domain adapter while retaining an agnostic compiler.

Do not expand chat.py, create a second registry, or grow universal category phrase lists. Do not raise architecture ceilings. Fulfillment and shopping-case router extraction require their own characterization tests, not opportunistic moves during a compiler fix.

### Release — certify deployment and authority

Run complete recommendation-core and affected integration suites twice in different orders, with config/cache isolation and unchanged tracked files. Reproduce in a clean checkout, then clean PostgreSQL and hosted environment. Seal live failure injection and a rotating seed-recorded unknown-identity set. Complete eight independent source reviews and Rockwell's separately pending claim-authority review without automatic sign-off.

## 5. TDD design: explicit failing assertions

Extend `tests/services/test_requirement_compiler.py`, `test_attribute_registry.py`, `test_research_outcome.py` rather than creating an alternative test-only compiler.

1. Electronics scope + pharmacy strength -> `attribute_not_applicable`; pharmacy scope still requires allowed regulatory use and authority.
2. Storage definition allows declared fit use but not every variant's fit use.
3. `ram_gb=16, unit=mg` -> dimension mismatch; `1024 MB` conversion uses the manifest's declared convention, not a hidden assumption.
4. Numeric `contains` -> operator/type rejection. Unknown enum, non-finite number and out-of-bounds value remain invalid.
5. Two predicates from one source -> distinct claim IDs and shared source-record provenance. Repeated projection is idempotent.
6. GPU translation -> derived claim citing literal GPU row + rule revision; never `verified_official` merely because input was official.
7. Rejected compiler row -> same rejected count/reason on terminal and UI. Accepted+held cannot disappear through max-count selection.
8. Complete document with missing applicable CPU/OS obligations -> partial fit. Complete applicable accepted obligations + matching stock -> qualified.
9. Irrelevant rejected claim does not poison unrelated fulfilled obligations; evidence from shared word `CAD` does not bind to another software identity.
10. Quantity, monetary amounts, unit price and pack units remain independent. Three packs of 250 g = 750 g only under an explicit packaging relation.
11. Concurrent tenant requests and background completion cannot reuse a different tenant/manifest cache entry. Old manifest revision remains reproducible; unavailable pinned revision fails explicitly.
12. Subject switch invalidates incompatible obligations; a late result cannot overwrite the new case revision.

Integration tests use real migration-built databases and seeded reviewed manifests/inventory. Controlled fixtures establish causality but must be labelled; they do not certify public-network availability.

Bulk matrix: enough stock/within budget; enough stock/over budget; insufficient stock/within budget; both short; unknown stock; pack-rounding shortfall; expired price; incompatible currency. After explicit sourcing acceptance assert draft identity, quantity/unit, reason, source claim IDs and case revision, then independently assert zero supplier outbox dispatches and zero cart mutations.

## 6. Browser gate (zero configured retries, no conditional positive assertions)

Use one live-model browser worker and GPU-disabled Chromium. Record seed, runtime profile, manifest revision, terminal envelope and network receipts. Record queue/model/research/extraction/projection durations separately. A corrected harness rerun is diagnostic, not a first-attempt certificate.

| Journey | Required result |
|---|---|
| Unknown software + hardware purchase | Identity research or bounded clarification; no generic-office substitution |
| Complete accepted hardware evidence + matching SKU | Visible qualified product with actual matching values, not merely a successful endpoint |
| Partial GPU/OS evidence | Restricted result naming missing obligations; original and derived values distinguishable |
| Electronics storefront -> roasted coffee purchase | Honest out-of-category/sourcing result; no laptop shelf |
| Reviewed coffee tenant -> 3 x 250 g coffee | Correct net contents, offered pack and stock quantity |
| Grocery product / unrelated grocery conversation | Typed purchase versus unrelated route, with appropriate authority |
| Laptop for a grocery/pharmacy business | Hardware scope; business words do not select a regulated-product manifest |
| Pharmacy item | Applicable governed product policy; no implicit clinical suitability/substitution claim |
| Tenant/category switch and stale completion | No cross-tenant cache/evidence leakage; current revision on every surface |
| Bulk budget/stock shortfalls | Separate reasons, explicit draft-only sourcing, no dispatch |
| Unsafe URL / model offline / provider timeout / contradiction | Typed failure and safe authority; no invented verification |

Coffee/grocery positive live journeys require installed, reviewed manifests and inventory. Until then report them as unimplemented, not passed by testing an electronics refusal.

## 7. Every Decision Trace panel: what must be checked

For each panel check the same operation, trace, case and revision, then compare its content to the terminal result. Some specialist panels legitimately have no activity; they must say not applicable/not recorded, not imply successful execution. Wait for bounded async panel loading and report timeouts.

| Panel | Semantic assertion, beyond opening the tab |
|---|---|
| Summary | Current query, outcome, scope, model/fallback, products agree with terminal |
| Events | Ordered operation/revision transitions; one terminal commit; no stale subject |
| Execution | Queue/run timing, retries and actual external calls; core execution count |
| Research Breakdown | Identity, original/derived claims, held/accepted/rejected counts, missing obligations |
| Why | Qualified/blocked reason cites applicable predicates and actual SKU values |
| Intent | Purchased object, workload relationship, budget, quantity, modifiers; no lost 1080p target |
| Memory | Preserved/cleared constraints, tenant and manifest revision; no stale evidence |
| Complexity | Actual measured/estimated status labelled; no fabricated certainty |
| Evidence | Source applicability, exact spans, timestamps, lineage and authority |
| Multimodal | No upload = not applicable; upload = bounded scan/extraction receipt |
| Security | URL sanitation/redirect/egress verdict if used; no invented successful scan |
| Market Intelligence | Scoped SKU stock/price freshness, or explicitly not run |
| Procurement | Distinct budget/stock gaps; draft confirmation; no supplier send |
| Audit Trail | Persisted revision and policy/approval events, retrievable without auth loops |
| Raw | Same canonical contract as UI, sanitized; not another independently inferred truth |

## 8. Dirty tree and consolidation

At assessment start: one modified tracked file (`config/feature_flags.json`) and two untracked assessments (`SHOPSQUIRE_DELTA_REASSESSMENT_2026-09-07.md`, `SHOPSQUIRE_GODFUNCTION_AND_DETERMINISM_SURVEY_2026-09-07.md`). Git showed no textual config diff. Earlier substantive test pollution was backed up/restored in prior work; do not conflate that with today's line-ending/index state.

This assessment adds this roadmap only inside the repository. Diagnostic script/screenshots/raw responses remain outside source commits. Nothing was reset, deleted, approved, committed or pushed by this assessment.

Next source checkpoints should be dependency-complete: (1) scoped schema/compiler and red-to-green tests, (2) provenance/ledger and projection tests, (3) completeness/fit and browser delivery tests, (4) extraction with unchanged guards, (5) dated assessment documents separately. Preserve untracked dependencies in recoverable checkpoints; exclude secrets, databases and runtime logs. Verify each source checkpoint from a clean checkout.

## 9. Bottom line

Fix the compiler boundary, not a PRAGMATA exception. The highest-risk new finding is that declared units and operator types are not enforced at compilation. Scope, usage permissions, dimensions and evidence provenance form one coherent repair. Category-specific completeness and buyer delivery follow that repair; large extraction and new vertical rollout follow the tests.
