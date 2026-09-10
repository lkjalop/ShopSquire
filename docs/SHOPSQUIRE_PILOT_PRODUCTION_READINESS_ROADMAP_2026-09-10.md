# ShopSquire pilot production readiness

## Executive assessment

ShopSquire is an engineering-pilot candidate, not yet a certified buyer-facing procurement service. Its strongest demonstrated capability is governed restriction: incomplete evidence stays incomplete, buyer review does not automatically verify a publisher, budgets can remain intact, and supplier actions have explicit boundaries. Its weakest demonstrated capability is the positive path: converting live, applicable requirements into useful, qualified inventory recommendations.

The immediate objective should be a narrow, dependable service, not another expansion of the platform. Start with one tenant, one reviewed electronics catalogue, a small named operator group, read-only operational integrations and draft-only sourcing. Treat recommendation delivery, operational reliability and transactional authority as separate launch gates. A procurement shadow pilot can proceed earlier than autonomous purchasing, but it still needs access control, privacy, recovery, monitoring and a defined support owner.

The required change is not a larger title dictionary or a broader authority bypass. It is completion of the existing contracts: identity to applicable evidence, evidence to typed compatibility, compatibility to exact inventory, and one revision-bound outcome to all presentation surfaces. After those contracts work, scale their execution and certify deployment.

## Evidence basis and limits

The assessed source baseline is commit `ad65cee4` plus the uncommitted stretch follow-up present on 10 September 2026. Before this report was added, the tree contained 14 modified tracked files and two untracked files. Those counts describe uncommitted work, not a defect count. The live API was restarted onto the stretch implementation in the preceding verification run. Tests and inspections in this assessment did not restart services, approve sources, dispatch suppliers or change application code.

Evidence has four distinct levels:

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| Source inspection | Implemented boundaries, current defaults and visible failure paths | Complete execution coverage or security certification |
| Fresh focused assessment: 36 tests passed | Approval-policy, manifest-scope, startup-readiness, ranking-nudge integration and isolated bitemporal query behaviour | Entire service suite, real-model intelligence, hosted concurrency or all browser tabs |
| Preceding same-workspace verification: 66 backend tests, 17 frontend tests, build and two live acceptance journeys passed | Explicit stretch/default-off acceptance, budget retention and restricted partial-evidence behaviour | Complete live product qualification |
| Strict live positive-delivery gate failed | BG3 returned two accepted claims, partial completeness, missing CPU/GPU/OS/storage-type requirements and blocked authority | Whether every other workload fails, or whether the publisher lacks those requirements |

The latest live readiness probe returned `status: ok`; its fast mode skipped direct frontend, Ollama, OCR and Redis probes. Ollama's own residency endpoint separately reported `qwen3:14b` with 9,646,353,939 bytes of VRAM. This is a point-in-time observation, not an availability, thermal-stability or capacity certificate. Readiness must not be read as proof of successful buyer delivery. [1][2]

No new full browser-tab sweep was executed for this report. The preceding live artifacts were inspected alongside the code. No full-suite, hosted restore, production WORM or multi-tenant penetration-test certificate is claimed.

## Current capability assessment

| Area | Assessment | Required next proof |
|---|---|---|
| Literal budgets and acceptance | Meaningfully improved; tested at service/API/browser levels | Multi-turn, bulk, currency, stale-review and concurrent-action matrix |
| Explicit stretch | Implemented for requirement acceptance only; unchecked opt-in, explicit per-item cap, original budget retained | Terminal/trace visibility and independent lifecycle coverage; do not advertise chat-wide consent |
| Live external research | Operational on demonstrated paths; not equivalent to complete requirements | Unknown-identity discovery through successful or honestly restricted fit on rotating inputs |
| Evidence compilation and fit | Conservative but incomplete in the live BG3 journey | Complete literal observations plus approved compatibility evaluation and nonempty permitted shelf |
| UI consistency | Ordering and hidden-panel fixes are real; legacy action projections remain | Every action installs one authoritative outcome, including clears and errors |
| Procurement | Strong architecture and historical test coverage; transaction certification remains narrow | Separate budget/stock shortfall, operator draft inspection, durable zero dispatch, concurrency |
| Bitemporal trace | Query behaviour passes isolated tests | PostgreSQL writes, retroactive corrections, historical UI and immutable dependency references |
| Model execution | Process-local priority scheduling exists | Shared capacity control across API workers and recovery from cancellation/timeouts |
| Category agnosticism | Manifest-scoped compilation is a good boundary | Durable reviewed manifest publication and packaging semantics |
| Audit retention | Local append plus optional Object Lock upload exists | Reliable export, delivery receipts, backlog alarms and destructive retention checks |
| Hosted production | Not established by the reviewed evidence | Reproducible deployment, security, restore, rollback, load and incident drills |

The older assessment's ranking-nudge failure is not current: both integration cases passed in the fresh focused run. They exercise `/api/v1/recommend/suggest` with controlled model/feedback inputs. Keep the experiment out of the pilot critical path until the actual deployed chat path is independently covered; neither declare it universally broken nor universally certified. [3]

## Architecture to retain

The intended ownership chain is sound:

```text
Authenticated tenant + buyer turn
  -> canonical literal facts + typed semantic proposal
  -> server-selected category, relationship and manifest revision
  -> identity resolution and governed research
  -> immutable observations + separately approved derivations
  -> applicable requirements + category completeness
  -> exact-configuration fit + current stock and economics
  -> one committed terminal outcome
  -> chat / shelves / review controls / Decision Trace
  -> explicit draft-only sourcing, separately authorized sending
```

Keep models responsible for interpreting language, proposing identities and queries, extracting cited candidates and explaining outcomes. Keep deterministic code responsible for money, units, identity references, tenant boundaries, revision checks, evidence validation, applicability, authority and side effects. These responsibilities are complementary. More deterministic *application-name routing* is undesirable; precise deterministic *contract enforcement* is necessary.

Do not rewrite the platform or replace these boundaries with a new general agent framework. Extract code only where ownership is already known and covered by characterization tests. The source-size ratchet passing means growth ceilings were respected; it does not mean orchestration complexity has disappeared.

## Findings that materially change the roadmap

### 1. Live product delivery is still the first buyer-value blocker

The live BG3 outcome contains two accepted claims and reports missing `cpu_model`, `gpu_model`, `os` and `storage_type`. It returns `requirements_incomplete`, blocked catalogue authority and no shelf. The compiler explicitly rejects derived claims without policy and validates source provenance, units, operators and manifest applicability. Simply allowing rejected fields or equating RAM/VRAM with compatibility would create false confidence. [2][4]

Separate three jobs. First, deliver literal publisher observations with exact identity/version and retained source spans. Second, evaluate exact device compatibility, distinguishing CPU/GPU models, desktop/mobile variants, OS and architecture, storage medium and conditional requirements. Third, introduce reviewed equivalence rules only where literal comparison is insufficient. Each derivation needs input claim IDs, versioned rule identity, reviewer, applicability limits and a reproducible output. A broad GPU-memory threshold is not equivalent to model compatibility or promised frame rate.

Positive delivery needs both sides: complete authorized workload requirements and sufficiently evidenced stock configurations. Do not assume the catalogue contains a qualifying SKU merely because several laptops are expensive. If none qualifies, a correct shortfall is a successful negative case, not a positive-delivery certificate.

### 2. Manifest completeness is improved but identity continuity is unfinished

The compiler selects one manifest and pins its content revision. Fit rechecks currentness and groups accepted attributes by artifact name, version, tier and condition. That prevents complementary partial workloads from filling each other's gaps, but string names are not stable concept IDs. The manifest resolver still reads local attribute-pack JSON and explicitly describes durable publication as separate work. [4][5]

Use stable IDs for concepts, canonical products, obligations, claims and origins. Keep label corrections separate from identity replacement. Pin the server-selected relationship and product type at the operation boundary; do not let a provider-selected scope or a client taxonomy hint authorize a different category. For historical views, replay the recorded manifest revision rather than interpreting yesterday's decision against today's manifest.

### 3. Stretch is intentionally narrow, not a new purchasing budget

The current implementation captures a confirmed revision and explicit per-item cap, preserves the original unit budget, records a reviewer/timestamp receipt and limits use to the current acceptance. Both projection branches receive the allowance. This is useful and live-tested. It is not permission for subsequent turns, supplier contact or an automatic budget amendment. [6]

Remaining work includes showing the receipt consistently in the terminal/trace, verifying that idempotent replay cannot broaden it, and providing clear expiry/revocation semantics if stretch is later expanded beyond one action. For bulk orders, present original total budget, original unit allowance, stretch unit cap and implied maximum total separately. The current per-item wording is necessary but not sufficient for enterprise financial clarity.

### 4. Atomic presentation is still a system-wide invariant, not a single hook

The UI generation gate rejects superseded responses and revision regressions. The latest live test also caught and fixed a hidden-panel regression: a valid ambiguity outcome did not open the right panel when products were empty. This demonstrates why passing backend tests cannot certify presentation. [7]

Inventory every state-changing entry: chat, interpretations, research completion, source approval, claim acceptance/rejection, manual specifications, retry, identity confirmation, cart proposal and sourcing confirmation. Each must yield the same terminal envelope or a retrievable operation. Installing a new outcome must clear incompatible shelves, questions, review cards and trace references together. Historical messages can remain visible but must not retain actionable controls for an obsolete case.

### 5. Procurement needs concurrency and separation-of-duties proof before real sending

Dispatch checks operator role and content hash. Approval tiers are opt-in. The dispatch route explicitly documents a category-budget race: two approvals can each read committed spend without observing the other's pending commitment. A category-scoped transaction lock or equivalent serializable reservation is needed before that budget policy is relied upon. Human pacing is not a concurrency guarantee. [8]

The reviewed dispatch path does not establish requester-versus-approver separation merely by recording a user ID. Prove policy at the actual approve/send/PO endpoints: requester cannot self-approve where dual control is required, approver has current authority, edited drafts invalidate approval, and cross-tenant objects are inaccessible. The pure approval helper also coerces malformed values to zero; dispatch separately rejects unknown spend, so this is not proof of an exploitable bypass, but other consumers must not treat malformed monetary inputs as low-value approvals. [8]

For a draft-only shadow pilot, disable dispatch at both application and transport/IAM boundaries. For a transactional pilot, require the stronger controls before launch. Do not label a draft-only pilot as autonomous procurement.

### 6. Audit export currently has best-effort failure semantics

`append_worm_record` catches exceptions; local writes catch errors; S3 uploads are optional and errors do not propagate to the action. Consequently an application success does not establish that an immutable external audit record exists. This is a confirmed code property, not a demonstrated production data-loss incident. [9]

Use a durable transactional audit outbox, idempotent export, retry/dead-letter handling, sequence reconciliation and alerts on age/backlog. Define which privileged actions must stop when audit persistence is unavailable. Do not synchronously freeze ordinary read-only chat on an S3 outage; distinguish durable local acceptance of the audit event from completed immutable export.

Cloud retention requires configuration and destructive testing. S3 Object Lock protects particular object versions; a simple delete marker is not proof that the protected version was deleted. Verify version IDs, retention metadata and permanent-version deletion denial using a restricted test identity. Retention duration must be a reviewed business policy, not an inherited seven-year code default. [10]

### 7. Model scheduling is process-local

The local model role gate orders router, identity, extraction and optional narrative work, and limits concurrency per model artifact. This is better than unrestricted calls. Its waiters, locks and statistics live in one Python process, however. Multiple API workers can each believe they own the GPU capacity. [11]

Before adding workers or tenants, introduce shared inference admission or a dedicated inference service. Include bounded queues, tenant fairness, cancellation, total operation deadlines and backpressure. Record queue, execution, transport, truncation and fallback separately. Validate model behaviour under contention, not just warmed single-turn speed. A resident model is not evidence that the next request will meet its deadline.

### 8. Bitemporal storage, UI truth and WORM are different guarantees

The decision query supports valid-time and knowledge-time predicates. Fresh isolated tests cover retroactive corrections, tenant filtering, invalid timestamps and timezone-equivalent cutoffs. Those tests use SQLite with a small schema, not the complete historical write path. [12]

Certify a full lifecycle on PostgreSQL: original evidence recorded; later correction becomes known; current result changes; the old knowledge-time query still returns the original; all evidence and policy references resolve; historical UI controls cannot mutate the live case. Separately prove append-only/retention enforcement. A timestamp field, visible tab or HMAC digest is not itself bitemporal or immutable storage certification.

### 9. PostgreSQL certification is now honest but deliberately narrow

The replacement certificate checks an isolated PostgreSQL database name, actual dialect and migration head, rejects skipped tests, and checks durable sourcing without new outbound rows. It explicitly disables automatic drafting in that test and invokes a route with controlled dependencies. It is valuable evidence, but not a hosted end-to-end operator draft, authentication, transport, backup or restore certificate. [13]

Do not restore the older blanket claim that PostgreSQL production is certified. Extend the narrow certificate into a deployment-specific suite and retain both the migration identity and execution receipts.

## Ordered implementation and release roadmap

| Stage | Work and ownership | Exit criterion |
|---|---|---|
| 0 — Define pilot | Product owner + operator: tenant, catalogue, users, capabilities, unsupported domains, data retention, escalation and rollback owner | Signed scope; dispatch/payment disabled for shadow; exact build/profile/database recorded |
| 1 — Deliver evidence and fit | Backend + evidence reviewer: literal CPU/GPU/OS/storage pipeline, stable applicability and reviewed equivalence; inventory owner verifies exact configurations | Positive workload with authorized complete evidence and matching stock returns visible qualified products; negative cases remain restricted |
| 2 — Unify actions and trace | Backend/frontend: one terminal action contract, canonical facts, clear semantics and stale-result rejection | Every action and every visible trace panel agrees on operation/revision, authority, money and inventory |
| 3 — Seal procurement boundaries | Backend/security: distinct shortages, draft-only acceptance, current ATP, idempotency, zero-dispatch proof; SoD and atomic spend control before send | Budget and stock cases pass separately; no unauthorized external job/message; transactional gates pass concurrent and adversarial tests |
| 4 — Publish pilot data | Data owner/backend: immutable manifest revisions, catalogue/source freshness and review workflows; connector contracts | Pilot manifest and inventory are reproducible; updates are reviewed, scoped and reversible; no unapproved cross-category fit |
| 5 — Harden operation | Platform/security: managed PostgreSQL, backups, durable jobs/audit outbox, shared inference limits, secrets, tenant auth, telemetry | Restart, restore, replay, throttling and dependency failures have bounded, observable outcomes without duplicate side effects |
| 6 — Certify hosted candidate | QA/platform/independent reviewer: clean build, production-shaped database, real-model browser matrix, load and failure injection | Signed certificate tied to immutable release/config/manifest/model identities; no skipped critical gates or retry-hidden passes |
| 7 — Shadow, then assisted pilot | Product/operator: limited cohort, daily review, measured handoffs and incident response | Agreed observation window meets safety and usefulness thresholds; expansion approved separately |

Stages 1–2 are the engineering critical path for buyer recommendations. Source reviews, pilot data preparation and staging provision can proceed alongside them. Stages 3 and 5 are prerequisites for any real external action, even if product delivery becomes green earlier. Do not queue a large orchestration extraction ahead of the failing buyer-delivery gate.

## What green means in TDD

Each defect needs a failing test at the actual boundary, then the smallest repair, then the broader contract tests. Do not change expected authority to hide a failure, raise source-size ceilings, conditionally skip positive shelf assertions, or substitute a fabricated accepted source in a live certificate.

| Test family | Required assertion |
|---|---|
| Canonical facts | Same budget, currency, quantity, total/unit scope and subject role across ingress, persisted revision and all UI surfaces |
| Approximation/stretch | About 3000 preserves 3000; no automatic stretch; explicit cap is bounded, revision-scoped and cannot grant commerce authority |
| Identity | Unknown and misspelled concepts trigger discovery or clarification; sequel/DLC/editor confusion cannot silently substitute a product |
| Manifest applicability | Wrong tenant, product type, relationship, revision, unit or operator rejects; complementary unrelated workloads cannot form complete evidence |
| Literal/derived evidence | Exact source spans retained; observed and derived identities distinct; unreviewed equivalence cannot qualify |
| Positive delivery | Complete authorized applicable evidence + exact matching permitted stock produces a nonempty qualified shelf and visible correct product values |
| Honest restriction | Partial, held, contradictory or incompatible evidence does not qualify; absent stock produces explicit shortfall, not a generic laptop list |
| Money versus inventory | Sufficient stock but insufficient budget differs from sufficient budget but insufficient stock; quantity reconciliation includes local/transfer/supplier components |
| Sourcing | Explicit confirmation creates one draft-only case; repeated requests are idempotent; outbound message/job counts remain unchanged |
| Temporal consistency | One logical operation and terminal commit; late results rejected; past knowledge-time views remain historically correct after corrections |
| Failures | Offline model, truncation, provider timeout, unsafe redirect, parser zero-yield and database failure return typed outcomes without unauthorized effects |
| Isolation | Wrong-tenant and wrong-principal requests fail; flags/caches do not leak between tests; test runs leave tracked configuration unchanged |

Use four independently labelled execution tiers: pure tests, real-database integration, controlled browser fault injection, and live model/provider browser tests. A release needs all relevant tiers. A fixture is valuable for reproducibility but is not evidence of public-network availability.

The rotating intelligence suite should draw from official feeds, record the selection seed and source rows, exclude fixture-known names, and include typos, ambiguity, future releases, incomplete requirements, non-Steam software and a fabricated identity. Keep exact historical failure prompts too. Rotation tests generality; permanent regressions prevent rediscovery of old defects.

## Browser and Decision Trace certificate

For every turn, capture the terminal envelope and displayed state. Assert values rather than only successful HTTP responses. Include a held-workload to storage purchase switch, budget refinement, additive workload, category replacement, stale identity confirmation, source approval, manual acceptance and explicit stretch. Click all sections and subsections visible in that build; record their registry names rather than relying on a historical count of 15.

| Surface | Required truth |
|---|---|
| Chat and right panel | Same subject and budget; no conflicting completed/no-evidence/verified statements |
| Decision summary | Correct operation, revision, catalogue authority and next action |
| Research & Fit | Source execution counts, accepted/held/rejected claims, completeness and exact missing attributes |
| Reasoning | Auditable rationale and evidence references, not purported private model thought; correct failure/degradation source |
| Evidence & Risk | Applicable sources, origin status, URL/redirect security receipts and observed versus derived claims |
| Commercial Journey / procurement | Original money and quantity, stock versus budget gap, explicit draft state and absence/presence of authorized send |
| Technical/audit sections | Stage timing, model fallback, operation dependencies, correct historical snapshot and no silent 401/404 polling loops |

Pass blocked and superseded cases as rigorously as positive cases. On authority downgrade, old qualified cards must disappear or be explicitly historical and non-actionable. A current-view spinner is not historical evidence; an absent metric should not become a favourable default.

## Production operating envelope

Adopt explicit initial service targets as product decisions, not claims about measured performance. Suggested starting targets are: visible acknowledgement within two seconds; an initial governed state or operation handle within 10–15 seconds at the agreed pilot load; bounded asynchronous research with progress and cancellation; zero silent terminal hangs. Measure p50/p90/p95 by role and route and publish breach rates. Do not solve latency by extending every timeout.

Provision a hosted staging environment that resembles the intended deployment: authenticated tenant routing, managed PostgreSQL, bounded worker queues, isolated secrets, TLS, real reverse proxy and the chosen model endpoint. Redis should remain disposable transport/cache, not sole durable conversation truth. Define backup retention, point-in-time recovery objectives, an actual restore drill and rollback to a known release without destroying new case data.

Security sign-off must cover principal-to-object authorization, session/CSRF controls, upload handling, egress/redirect validation, secret redaction, rate limits, dependency inventory and incident handling. OWASP ASVS is a suitable source of technical verification requirements; select and record the applicable requirements rather than claiming compliance from framework tags. Use NIST AI RMF as a structure for risk ownership, measurement and ongoing management, not as a product certificate. [14][15]

Deploy audit export with separate credentials and observable delivery state. Set source/claim review expiry, parser version, model artifact, manifest revision and source observation times in the release evidence. A source change or authority revocation must invalidate affected current qualifications without rewriting historical decisions.

## Agnostic categories and database manifests

Do not make pharmacies, coffee or groceries inherit a hardware compatibility checklist. Publish versioned tenant/category manifests with attribute definitions, units, allowed operators, permitted uses and completeness profiles for the specific relationship. Variant matching, compatibility, offer comparison and regulated eligibility are different evaluations.

Packaging requires unit and conversion provenance: each, pack, case, weight, volume, minimum order, divisibility and currency/cadence. For example, 12 packs of 250 g is not 12 kg, and a price per case is not a price per item. The core should evaluate typed quantities; the manifest supplies meaning and allowed conversions. Unknown or unreviewed category data should yield an honest unsupported/manual-review outcome.

An existing pharmacy profile or attribute file is not a production pharmacy capability. Keep regulated categories outside the initial pilot until a domain owner approves catalogue constraints, allowed advice, workflow and applicable obligations. No production review is inferred from fixture coverage.

## Git, refactoring and release hygiene

The last committed checkpoint remains `ad65cee4`. The stretch follow-up and strict failing delivery test are uncommitted. Preserve them. The third-party defect register is historical analysis, not executable dependencies or a release certificate.

Separate reviewable checkpoints into: acceptance/stretch code plus its tests; evidence/compatibility delivery plus its tests; terminal/trace reconciliation; deployment/certification artifacts; dated assessment documents. Keep logs, database files, screenshots, videos and credentials outside source commits. A green stretch checkpoint may be recorded independently, but it must not be labelled a green delivery release while the strict positive gate is red.

After each coherent extraction, rerun characterization, integration and relevant browser tests from a clean checkout. Prioritize terminal projection and research orchestration ownership; do not split files solely to improve line counts. Audit callers before retiring legacy paths. The currently passing ranking integration makes blanket removal particularly inappropriate without a deployed-path inventory.

## People, data and decisions required

1. A product owner must choose the initial tenant, supported category and whether the pilot is shadow-only or includes actual sends.
2. A catalogue owner must supply exact configurations, dependable stock/price feeds, update cadence and commercial permission to use the data.
3. Independent reviewers must approve source scope and compatibility derivations with named identity, timestamp and permitted claim types. The registry currently has eight top-level pending sources and twelve marked approved; Rockwell additionally retains a separate pending independent-review block. A registry label alone is not comprehensive human sign-off. [16]
4. A platform owner must provide staging, deployment credentials through approved secret storage, model capacity, backup targets and an on-call/rollback owner.
5. Integration owners must provide read-only sandbox credentials and contracts for WMS, pricing, supplier and carrier data. Connector enrollment code is not proof of a live connected system. [17]
6. Security/procurement owners must approve role separation, spend policy, retention and escalation. Real sending requires stronger evidence than draft-only browsing.

Do not request credentials in chat, bulk-sign pending reviews or silently enable dispatch to shorten this list.

## Go/no-go decision

**Now:** suitable for supervised engineering evaluation with explicit limitations. Not yet green for buyer-facing qualified recommendation promises or real autonomous procurement.

**Read-only shadow pilot:** conditional go only after scoped access, data/privacy approval, operational monitoring, bounded failures and zero-dispatch controls are proven. Product shortfalls must remain visibly unverified.

**Assisted buyer pilot:** no-go until the live positive-delivery and terminal/trace gates pass on a representative, rotating set and the hosted environment passes recovery/security checks.

**Transactional production:** no-go until separation of duties, atomic financial controls, durable audit export, dispatch idempotency and failure/concurrency certification are complete.

The next engineering slice is literal compiler-to-fit delivery, followed by terminal/trace reconciliation. Start hosted provisioning and independent reviews concurrently. Expanding categories, autonomous actions or framework size before those gates would increase risk without addressing the demonstrated buyer failure.

## Sources and verification references

References are to the assessed working tree and local artifacts unless an external publisher is named. Line numbers are navigation anchors, not immutable identifiers; bind a release certificate to its commit and manifest hashes.

1. [Startup readiness](C:/AI/ShopSquire/src/app/main.py:1566); [startup capability contract](C:/AI/ShopSquire/src/app/bootstrap/startup_readiness.py:15). Live fast probe and Ollama `/api/ps` observed during this assessment.
2. [Strict live delivery gate](C:/AI/ShopSquire/frontend/e2e/live-unresolved-purchase-boundary.spec.ts:5); [failed live artifact log](C:/AI/ShopSquire-checkpoints/positive-delivery-strict.log); [prior verification receipt](C:/AI/ShopSquire/docs/SHOPSQUIRE_ATOMIC_PRESENTATION_BUDGET_DELTA_2026-09-10.md).
3. [Ranking integration](C:/AI/ShopSquire/tests/integration/test_ranking_nudge_wiring.py:80); [focused assessment log](C:/AI/ShopSquire-checkpoints/pilot-assessment-focused.log). The 36-test run is new to this assessment.
4. [Requirement compiler](C:/AI/ShopSquire/src/app/services/recommendation_core/requirement_compiler.py:53); [structured claim projection](C:/AI/ShopSquire/src/app/services/structured_requirement_claims.py:9); [accepted fit](C:/AI/ShopSquire/src/app/services/accepted_catalog_projection.py:340).
5. [RequirementScope and file-backed resolution](C:/AI/ShopSquire/src/app/services/recommendation_core/requirement_scope.py:16); [electronics manifest](C:/AI/ShopSquire/data/attributes/electronics.json).
6. [Stretch/budget receipt](C:/AI/ShopSquire/src/app/services/catalog_shortfall_projection.py:11); [acceptance wiring](C:/AI/ShopSquire/src/app/routers/shopping_cases.py:793); [live acceptance tests](C:/AI/ShopSquire/frontend/e2e/live-acceptance-budget.spec.ts:4).
7. [UI ordering gate](C:/AI/ShopSquire/frontend/src/lib/terminalInstallation.ts:8); [terminal installation](C:/AI/ShopSquire/frontend/src/App.tsx:2455); [Decision Trace](C:/AI/ShopSquire/frontend/src/components/DecisionTrace.tsx:359).
8. [Dispatch and documented budget race](C:/AI/ShopSquire/src/app/routers/fulfillment_cases.py:1578); [approval policy](C:/AI/ShopSquire/src/app/services/fulfillment/approval_policy.py:43).
9. [WORM append/export failure handling](C:/AI/ShopSquire/src/app/observability/worm.py:42).
10. Amazon Web Services, [Locking objects with Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html), official documentation accessed for this assessment. Supports the version-specific retention and delete-marker distinctions, not deployment certification.
11. [Process-local priority scheduling](C:/AI/ShopSquire/src/app/services/local_model_roles.py:46); [model execution gateway](C:/AI/ShopSquire/src/app/services/model_execution_gateway.py:95); [durable event store](C:/AI/ShopSquire/src/app/services/agent_run_event_store.py:27).
12. [Bitemporal query predicates](C:/AI/ShopSquire/src/app/routers/decisions.py:208); [isolated temporal tests](C:/AI/ShopSquire/tests/test_decision_bitemporal_query.py:10); [decision writes](C:/AI/ShopSquire/src/app/services/decision_log.py:349).
13. [Isolated PostgreSQL runner](C:/AI/ShopSquire/scripts/run_tests_postgres.ps1:1); [dialect/migration/zero-dispatch test](C:/AI/ShopSquire/tests/certification/test_postgres_draft_boundary.py:19).
14. OWASP Foundation, [Application Security Verification Standard](https://owasp.org/www-project-application-security-verification-standard/), project source and [official 5.0 publication](https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/OWASP_Application_Security_Verification_Standard_5.0.0_en.pdf). The project search result was accessible; direct project-page fetch failed during this assessment.
15. NIST, [AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework), including the Generative AI Profile reference. This is risk-management guidance, not ShopSquire approval.
16. [Official source registry](C:/AI/ShopSquire/config/official_workload_sources.json:8); Rockwell independent-review block at line 136. Counts taken directly from current registry JSON.
17. [Operational connector enrollment](C:/AI/ShopSquire/src/app/services/operational_connector_registry.py:38); [case ingestion](C:/AI/ShopSquire/src/app/services/operational_connector_ingestion.py:30).
