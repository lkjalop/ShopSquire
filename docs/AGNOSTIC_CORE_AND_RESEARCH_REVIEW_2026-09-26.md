# Core assessment, bounded contract and current research — 26 September 2026

Execution follow-up: [contract/compiler integration](CONTRACT_COMPILER_EXECUTION_2026-09-26.md) now connects explicit contract selection to the authoritative compiler and typed evidence stage. End-to-end case activation remains incomplete.

The direction should be a **domain-independent decision engine with domain-owned evidence adapters and contracts**. The present V2 is partway there, not fully agnostic. This batch adds no application-name branches to routing, ranking or qualification and does not create V3.

## What actually runs

`src/app/bootstrap/recommendation_router_group.py` registers `recommend_compat.py`; its deprecated `/api/v1/recommend/suggest` route calls the V2 compatibility service. No active `recommend.py` or separate V3 implementation was found in this checkout. “V2/V3” labels do not establish an architecture boundary; the actual dependency path does.

| Inspected boundary | Assessment | Next treatment |
|---|---|---|
| `recommendation_core/core.py` | 2,801 lines; `_recommend_turn` is 1,308 lines. Typed stages exist but orchestration still contains policy and presentation details. | Extract along existing stage contracts and behavior checks. Do not replace it wholesale or add new workload branches. |
| `recommendation_core/turn_router.py` | 2,817 lines; `_route_turn_raw` is 1,347 lines. Literal clamps coexist with keyword and electronics-specific repair logic. | Evaluate unseen subjects, negation and changed requirements before removing repair paths; model interpretation should propose typed context, not decide authority. |
| `intent_resolver.py` | Registry-driven profiles are useful. `_salvage_title_requirements` still introduces finite game/software vocabulary and can run after a provider returns no material requirements. | A quality risk even when downstream qualification fails closed: inferred retrieval floors can hide candidates. Migrate curated title records through the same provenance/compiler boundary rather than treating a known name as proof. Not removed blindly in this batch. |
| `requirement_scope.py` + electronics manifest | Scope/revision checking is generic, but the electronics pack assumes named CPU/GPU and storage fields for all applications. | Separate attribute definitions from application obligations. A contract must not silently erase absent obligations or manufacture fields the publisher never required. |
| `accepted_catalog_projection.py` / `workload_decision.py` | Capability mappings and configuration hashing contain computer fields. | Keep these behind a product-domain adapter before claiming cross-domain qualification. Version any hash-schema migration; changing existing hashes would affect exact-effect bindings. |
| Publisher parsers | Blender table parsing is intentionally source-specific and remains outside the orchestration core. | Keep extraction schema tests, source revisions and abstention on layout drift. Do not move publisher HTML assumptions or software names into the core. Generalize only when a second demonstrated format needs it. |

Determinism is appropriate for identity, tenant boundaries, exact effects, expiry, revocation, units, comparisons and completeness. Brittle behavior comes from guessed intent, arbitrary keyword-to-hardware mappings, undocumented equivalence, or test phrases becoming policy. Moving such rules into JSON alone would not solve that problem.

## Portfolio scope update

The owner subsequently clarified that no real customer or private business data is expected. [The portfolio roadmap](PORTFOLIO_ROADMAP_2026-09-26.md) replaces real-tenant acquisition with an explicitly synthetic, reproducible decision demonstration. This changes the delivery target, not the evidence or authority rules. Synthetic qualification must remain labelled; real-world utility, real-publisher qualification and production commerce require their own evidence.

## Changes made

- Added `src/app/services/requirement_contract.py`: immutable, data-owned subject/version/platform/workload context, explicit obligations, content revision and an evidence-coverage assessment. No application, manufacturer or attribute vocabulary is embedded in this module. Source bodies cannot change obligations or grant fit/commerce authority. Its input is an already-governed claim ledger; it is not an authenticator for arbitrary model JSON.
- Added [the bounded Blender contract](../config/requirement_contracts/blender-5.0-windows-opengl.json): **Blender 5.0, Windows x86-64, interactive modelling, OpenGL viewport, CPU rendering**, recommended resources plus minimum compatibility obligations. Eleven obligations preserve CPU instruction support, API extensions, supported GPU/driver and architecture gaps. GPU rendering, Vulkan, large-scene capacity and render-time claims are excluded from this specific contract.
- Integrated that contract assessment into the existing gap-report command. It is a diagnostic coverage boundary, **not yet an executable replacement for the live V2 compiler scope**. Coverage never grants qualification. Production selection must eventually receive explicit typed context and validated applicability; no keyword shortcut or automatic release binding was added.
- Fixed the shared research outcome so evidence from different tiers or conditions cannot combine into false completeness.
- Fixed product freshness so a future-dated observation is unknown rather than fresh. An older test was incorrectly calling an August 11 specification fresh on August 8; the expectation now reflects the time boundary.

The release-specific [Blender 5.0 announcement](https://devtalk.blender.org/t/system-requirements-for-blender-5-0/41457) distinguishes graphics backends and additional OpenGL requirements. A generic memory floor cannot prove these. The moving requirements table still does not prove applicability to this release; the new contract intentionally leaves that unresolved. The release source also requires governed enrollment before production use.

## Exact configuration evidence

The [MSI Australian specification page](https://au.msi.com/Laptop/Titan-18-HX-A2WX/Specification) explicitly includes **Titan 18 HX A2WJ-1038AU**. It distinguishes neighboring configurations, including their memory layouts. Six observations were recovered for `SCORP-126982`: CPU core count, VRAM, OS, literal memory-module layout, CPU identity and GPU identity.

They are recorded as **unverified/held observations** in the isolated `.artifacts/roadmap-proof.sqlite3`, with capture hash and source URL. Web retrieval supplied readable source content, but direct origin capture returned HTTP 403. No direct-fetch success, new governed publisher enrollment, current price/stock or verified fit was invented. Old observations and timestamps remain intact; a database backup precedes this write. Module layout was not silently converted into an authorized total-memory derivation.

Evidence: [refresh audit](../.artifacts/agnostic-contract-2026-09-26/evidence-refresh.json), [updated gap report](../.artifacts/agnostic-contract-2026-09-26/gap-report.json), [fetch receipts](../.artifacts/agnostic-contract-2026-09-26/fetch-receipts.json). All eleven contract obligations remain uncovered: some literal values exist, but release applicability or required compatibility predicates do not. This is truthful progress in diagnosis/evidence collection, not a completed qualified journey.

## Research checked as of this review

These are external findings and design inputs, not performance results for ShopSquire. Abstracts/project documentation were reviewed; the papers' empirical results were not independently reproduced here.

| Primary source | Useful finding | Application to this repository |
|---|---|---|
| [DeepResearch Bench II, revision 10 September 2026](https://arxiv.org/abs/2601.08536v3) | Uses expert-derived, fine-grained rubrics for information, analysis and presentation across diverse research tasks. | Judge whether each decision obligation is supported, not how many searches, sources or rows were accumulated. Freeze evaluator version and include independent human labels and counterevidence. |
| [DuMate-DeepResearch, June 2026](https://arxiv.org/abs/2606.07299) | Studies auditable iterative research with rubric-driven reasoning. | Trial bounded search expansion against unresolved obligations and explicit stopping criteria. This does not justify adopting a multi-agent system or its reported benchmark ranking without a local comparison. |
| [Leakage-aware forecasting benchmark, June 2026 preprint](https://arxiv.org/abs/2606.22719) | Distinguishes information available at decision time from later revised/released data. Its empirical setting is macro/equity factors. | Store publication, observation, ingestion and effective times separately; replay market decisions using only then-available evidence. Methodological relevance does not establish retail/SKU forecast quality. |
| [BrowseSafe, revision 12 August 2026](https://arxiv.org/abs/2511.20597v2) | Evaluates realistic HTML injection and consequences for actions, and argues for layered defenses. | Expand beyond short malicious-string classification to actual attempted exfiltration, changed approvals and contaminated evidence. Include long benign distractors and false-positive measurements. |
| [OpenAI source-to-effect defense analysis, 11 March 2026](https://openai.com/index/designing-agents-to-resist-prompt-injection/) | Input classifiers alone cannot reliably stop contextual manipulation; restrict the consequences of a compromised agent. | Preserve exact-effect authorization and enforce data disclosure at network and effect boundaries even if the model follows a malicious instruction. |
| [OpenAI URL disclosure defenses, 28 January 2026](https://openai.com/index/ai-agent-link-safety/) | URL retrieval itself can transmit sensitive information. | A permitted hostname does not make an arbitrary query string safe. Cover search terms, redirects, paths, URL parameters and rendered remote resources with disclosure controls. |
| [Anthropic incident assessment, 9 September 2026](https://www.anthropic.com/research/alignment-assessment-cybersecurity-incidents) | Describes cyber evaluation incidents involving unintended real-internet connectivity despite simulation framing. | Enforce actual network isolation for adversarial tests. A prompt saying “sandbox” is not containment, and these incidents do not establish comparative production model safety. |

## Security and search priorities grounded in this code

The existing global `egress_allowlist.py` defaults to non-strict monitoring. Specific governed adapters apply stronger policies, but that does not establish universal enforcement. Its built-in endpoint allowlist is also not a data-disclosure policy. `external_research_httpx.py` correctly keeps the search host fixed and encodes the query, but its `scrubbed_query` argument name is not proof that every caller removed sensitive data. `prompt_injection_eval.py` contains a five-message seed corpus; other defenses exist, so this is not a count of all security coverage, but it is insufficient evidence on its own.

1. **One immutable research task scope:** tenant, purpose, approved disclosure fields, source capabilities, budget and cancellation. Page text, OCR, cached memories and search snippets remain evidence inputs; they cannot enlarge that scope.
2. **Measure action outcomes under attack:** direct hostile requests and indirect webpage/PDF/email/image injections; cross-turn poisoning; fake policy/approval messages; cached attacks; redirects; claims that an environment is only simulated. Use canary secrets and fake effect providers. Required safety result: no unauthorized disclosure or effect, even when the model's text is compromised.
3. **Separate interpretation from enforcement:** model/extractor proposes typed observations and citations; validator checks spans, applicability, provenance and freshness; compiler owns executable predicates; independent authorization owns effects. A detection score must not become an effect permit.
4. **Make search answer obligations:** discover candidates, verify official origin, preserve cell/section/version context, look for contradictions, stop on complete supported coverage or bounded unavailable/denied outcomes. Use caches keyed by tenant, source revision, parser/policy and selected context; revalidate at consumption.
5. **Make market data answer one tenant decision:** approve actual subject mapping, retain independent lineage, normalize region/currency, enforce freshness at use and evaluate incremental decision utility. Compare against a no-new-data baseline. No real tenant mapping or new forecasting win was established here.

## Validation and next release gates

- 38 initial contract/parser/compiler/provider checks passed. After the general coverage/freshness fixes, 69 contract/outcome/catalog/provider/terminal checks passed. These sets overlap. Synthetic unseen-subject tests show the new coverage mechanism has no subject-name dependency; they are not broad semantic-quality benchmarks.
- Function-size and undefined-name checks passed. Source captures and a pre-refresh database copy are preserved under `.artifacts/agnostic-contract-2026-09-26`.
- Next delivery work: integrate the typed contract selection into the governed compiler path; enroll version-specific requirements; obtain an acceptable direct-origin product capture or reviewed manufacturer document; compile missing compatibility clauses; then verify API/UI/trace agreement for the qualified and refusal cases.
- Distinct-person approval, complete effect recovery, varied 60-minute/overnight reliability and independently reviewed representative benchmarks remain open. No larger-context, graph-infrastructure or model-quality-winner conclusion follows from this batch.
