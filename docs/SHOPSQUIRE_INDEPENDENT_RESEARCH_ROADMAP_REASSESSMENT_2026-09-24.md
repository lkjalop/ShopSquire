# Independent research and roadmap reassessment — 24 September 2026

Assessment of the two supplied research documents and Claude's pasted investigation, against the current local working tree at HEAD `c7daafaa`. This is an assessment, not implementation authorization. No model configuration, running service, application source, or production database was intentionally changed. Tests used the repository's test setup.

**Verdict:** retain Claude's operational-first direction, correct its concurrency recommendation, move cross-surface invariants into the first repair sprint, and restore the September 14 report's credibility. ShopSquire needs a reproducible, measured buyer journey before new model, graph, or forecasting infrastructure.

**Evidence limits:** inspected relevant source and launcher paths, AST-measured functions, queried SQLite databases read-only, read Windows events and installed model metadata, ran four targeted test files, and executed synthetic reproductions. No GPU inference or live end-to-end research journey was performed. No crash dump was debugged. Primary sources were checked for the disputed papers and roadmap-driving claims; this is not a complete reproduction of every benchmark or verification of Compass's entire model catalogue. The working tree already contained 135 changed/untracked entries, so findings describe local files, not necessarily published code.

## 1. The research reviews need correction

The September 14 document explicitly separates authority continuity, mutation permission, outcome completion, and research validity. That separation is useful. Its paragraphs also explicitly discuss synthetic benchmarks, small samples, trusted components, and uncertain production transfer. Compass's blanket criticism that it has no links and is poorly sourced does not describe the supplied document: its Sources section contains eleven linked footnotes.

Five supposedly unverified papers resolve directly from those footnotes:

| Item | Independent verification | Implication |
|---|---|---|
| Beyond Agent Harnesses | [Primary paper](https://arxiv.org/abs/2609.08472) exists; abstract confirms matched-intent execution guarding and residual planner failures. | Keep live authorization at the mutation boundary. |
| EvidenceNet | [Primary paper](https://arxiv.org/abs/2609.10181) exists; [full text](https://arxiv.org/html/2609.10181v1) confirms 32 successful admissions among 45 traces. | Verify post-change state separately from command success. |
| ADMET-EvO | [Primary paper](https://arxiv.org/abs/2609.10121) confirms the 22-task benchmark, 96.77 score and 72.2% fitting-time reduction. | Adopt frozen evaluation and retained negative results; do not infer retail uplift. |
| Big Enough to Break Out | [Primary paper](https://arxiv.org/abs/2609.10780) explicitly reports confounding and no observed outcome improvement from its memory interventions. | Diagnose failure classes before buying more memory. |
| Consort | [Primary paper](https://arxiv.org/abs/2609.09671) exists and describes externally enforced gates; quality benefits remain hypotheses. | Reuse engineering discipline without adopting the whole framework. |

Finding a paper verifies existence and the checked claims, not every numerical detail or external validity. EvidenceNet has an especially important nuance: its 24 planted content defects were caught by a separate narrow rule checker, not the operational gate as originally configured; both tested LLM verifiers accepted them. Its deterministic gate cannot enforce predicates that were never encoded. This strengthens the need to test contract coverage rather than treating determinism alone as sufficient assurance.

Compass and Claude also incorrectly change CONTINUITY's code licence to CC BY 4.0. The repository's [LICENSE](https://raw.githubusercontent.com/zast-ai/continuity/main/LICENSE) is **MIT**. Paper and code licences must be checked separately; pin the actual revision before reuse.

Compass does contribute useful breadth: hybrid model architecture, evidence sufficiency, stage-aware retrieval, and forecasting alternatives. But three architectural conclusions need revision:

1. **Do not collapse preflight, authorization, and completion into one pre-effect gate.** Planning feasibility, permission to cause an exact effect, and evidence that the effect achieved its purpose are different checks at different times. Shared contracts are sensible; one pre-effect verdict cannot establish a later outcome.
2. **Active MoE parameters are not resident model size.** The [Qwen3-Next model card](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct) describes an approximately 80B-total model. A 3B active path does not establish 3B deployment memory or end-to-end serving cost. An idealized 80B four-bit weight payload alone is about 40 GB before overhead. This is not a low-risk upgrade for this laptop.
3. **A release is not an adoption case.** [Google's TimesFM-3 announcement](https://www.research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/) supports the release claim. Its [repository notice](https://github.com/google-research/timesfm#license-notice-for-pretrained-weights) distinguishes Apache-licensed code from non-commercial, non-production v3 weights. Neither novelty nor public benchmark leadership justifies replacing ShopSquire's forecast engine before defining and measuring the target series.

The original report's security ordering is stronger than Compass's model-first P0. Its remaining weakness is breadth: applying almost every pattern to several verticals does not demonstrate value in any one of them. Use ShopSquire-specific failure cases to select experiments.

## 2. Claude's findings: corroboration and contrast

| Claude claim | Independent result | Assessment |
|---|---|---|
| NVIDIA crash history and hardware | Confirmed six bugcheck events, 222 nvlddmkm events including 131 event-153 entries; RTX 5070 Ti Laptop, 12,227 MiB, driver 592.01. | Strong evidence of instability; precise causal chain still unproven. |
| Router failure causes collapse | Four synthetic failures all became `error / model_execution_failed`. | Confirmed. Preserve typed causes through the gateway and router. |
| Shared concurrency-one gate | Confirmed model/digest/limit key and role priorities. | Intentional protection, not inherently a defect. Splitting by role defeats it. |
| Root DB incomplete | Root DB has 82 tables and lacks `conversation_case_state`; recording DBs have 267. | Confirmed schema mismatch. A migration already exists; repair bootstrap, not dependence on an opaque recording DB. |
| Degraded proposal becomes accepted trace | Minimal source-level reproduction gives `model-proposal: degraded`, then `platform-authorization: accepted`. | Confirmed trace defect; not proof of unauthorized payment or supplier send. |
| Policy differs from effective behavior | Under buyer-consent profile plus legacy override, reported auto-authorization is false while helper returns true. | Confirmed. Resolve and serialize one effective policy. |
| Search only configured in artifact scripts | Multiple checked-in launchers configure it. | Incorrect as a repository-wide claim. `start_demo.ps1` still does not configure it itself. |
| No launcher selects a research profile | Live procurement, portfolio, and recording launchers select `demo-safe-auto-v1`. | Incorrect. Launcher fragmentation is the broader problem. |
| Private-host allowance bypasses checks | `_host_is_safe(..., allow_private=True)` returns before DNS/address checks. | Confirmed broad bypass. Endpoint is operator-controlled, so this alone does not establish arbitrary buyer-driven SSRF. |
| Market pipeline is unfed | Both recording DBs have zero ingestion runs/watermarks/rollups; one has one market signal, the other two. | Corroborated for these DBs, not all deployments. |
| Freshness flag and watermark unused | Backfill reads the flag; adapters gate ingestion; watermark code reads/writes records. | Too broad. Enforce freshness again when serving evidence. |
| 4,692-line chat function | AST confirms exactly 4,692 lines. Other reported large function sizes also match. | Confirmed; function ratchet useful after behavior coverage. |
| Backup frontend file committed | File exists, but `git ls-files --error-unmatch` rejects it. | Not tracked in this checkout; do not claim committed debt. |
| DMARC earlier finding withdrawn | Router-level role dependency exists; auth default is production. | Withdrawal supported by source. Production request-path verification remains separate. |

Relevant paths: `src/app/services/local_model_roles.py`, `recommendation_core/router_model_call.py`, `recommendation_core/trace_ontology.py`, `research_policy.py`, `src/app/adapters/external_research_httpx.py`, `src/app/tasks/market_signal_tasks.py`, `src/app/services/market_signal_adapters.py`, and `scripts/start_*`.

### Crash causality and capacity

The local model inventory confirms 9.3 GB qwen3:14b, 6.1 GB qwen3-vl:8b, 6.6 GB qwen3.5:9b-q4_K_M, and 17 GB qwen3.8:27b. These are artifact sizes, not measured concurrent VRAM allocations. GPU runtime buffers, context, display usage and offloading matter; GB/GiB subtraction is not an exact headroom measurement.

[Ollama's documentation](https://docs.ollama.com/faq#how-does-ollama-handle-concurrent-requests) says simultaneous model loading depends on available memory, otherwise requests queue and idle models unload. Therefore “file sizes sum beyond VRAM” does not prove both were resident or that this caused all bugchecks. The September 4 resource-related status supports investigating memory pressure but is not VRAM-specific proof.

Use single-model/single-request settings as a conservative diagnostic baseline, configure the actual server process, and verify the effective configuration after restart. Machine scope is not intrinsically required: Windows Ollama can inherit user variables. Benchmark the already installed 9B candidate with bounded context before selecting it. Preserve driver/Ollama logs and investigate minidumps if instability persists. Do not prescribe a bigger model or higher concurrency to solve an unmeasured queue.

### Existing controls are valuable but narrower than claimed

The stage guard restores owned response fields; it cannot roll back database writes or external effects. The typed coordinator validates order and dependencies, not arbitrary long-horizon planning. A fixed pipeline is a reasonable product architecture until concrete cases require replanning.

A schema-constrained lane enum is useful, but does not complete closed-world tool resolution. Tool identity, schema/version, principal, tenant, argument scope and live authorization still need validation at dispatch. Typed memory similarly needs migration, conflict, revocation and cross-model tests; schema versioning alone does not prove portability.

The market registry contains seven sources, four with fetch profiles, but its coverage does not supply competitor price/availability. CPSC recall data is product-specific, so “all macro” is inaccurate. More importantly, US weather and recalls need explicit regional relevance before supporting an Australian retail decision. SearXNG is one discovery option, not the only realistic data source: internal demand events, supplier feeds and licensed commercial feeds are alternatives. A search result or a registry licence label is not a verified price observation or evidence of reuse rights.

## 3. Additional findings from this assessment

**P0: timeout can release the artifact lock before work stops.** The gateway runs transport in a daemon thread and may return a timeout while that thread is alive. `execute_local_model_role` then releases the model gate in its `finally` block. A synthetic blocking transport reproduced this sequence:

```text
first_call_failure model_execution_timeout transport_still_active True
second_call ok overlapped_first [True]
```

This used injected transports and no model inference. It proves possible application-side overlap, not that it caused a particular GPU crash. Tie resource ownership to actual transport termination or confirmed provider cancellation; quarantine late output as well. A caller deadline and resource completion are separate events.

**The gate is process-local.** It cannot protect the server from another backend worker, separate application, or direct Ollama client. Different artifact gates also do not enforce one shared GPU budget. Keep server-level capacity limits and, if multiple workers are supported, establish shared admission control. Reusing one resident model can reduce swapping; role fan-in alone is not evidence that multiple models would improve latency.

**Timing can be stale as well as incomplete.** Artifact verification failure occurs before schedule recording. Thread-local schedule metrics are not cleared at call entry, while the router retrieves the last metrics by role. A prior same-role call can therefore contaminate failure telemetry. Bind timings to an execution ID; record verification, both queue stages, execution, timeout and completion separately. This is a source-derived risk, not a reproduced live trace.

**Cross-surface tests are already started.** `frontend/e2e/helpers/turnOracle.ts` checks operation/revision identity, budget parity, stale qualified shelves, evidence acceptance and commerce authority. Evaluation contracts and release-gate work also exist in the dirty tree. Extend these now; do not schedule a wholly new harness next quarter. RAG grading and deterministic commerce invariants serve different purposes. MCC can summarize classification performance but must not hide a forbidden effect among many correct negatives.

**Passing component tests did not catch the reproduced disagreements.** The four targeted files produced 30 passing tests. The policy tests explicitly remove the legacy override, illustrating why the conflicting-profile case escapes that coverage.

## 4. Revised roadmap and exit criteria

Timing below is sequencing guidance, not a delivery estimate. Complete work against exit criteria before advancing autonomy.

| Priority | Work | Exit evidence |
|---|---|---|
| P0: runtime and reproducibility | Fix timeout/resource lifetime; retain shared model gate; bound optional narration; preserve typed errors and execution-bound timings. Consolidate launch profiles and verify server capacity. Add migration/schema readiness and documented seed/bootstrap. | No synthetic overlap after timeout; no stale metrics; distinct failure codes; clean migrated DB starts; one bounded text/research journey and one text/image/text journey pass on the selected profile without new reset events. |
| P0: truth and authority | Propagate per-field provenance and degradation, make effective policy equal displayed policy, block stale/revoked revisions at decision/effect boundaries. Extend the existing deterministic oracle. | Injected model failure, consent withdrawal, revision change and expired evidence cannot yield unsupported qualification or any commerce effect. Trace, API and UI agree. Valid benign cases still complete. |
| P1: search and evidence | Enroll a named SearXNG endpoint, replace blanket private access with explicit endpoint allowance, verify discovery-to-source-to-claim-to-answer flow and controlled failure outcomes. | Consented request produces current accepted evidence; denied consent causes zero unauthorized fetches; empty, unavailable and rejected-evidence outcomes are distinguishable. |
| P1: maintainability | Characterize terminal projection/research-entry behavior, then extract them; add a per-function growth ratchet and consolidate launch configuration. | Existing oracles pass before and after; function complexity declines without semantic divergence. |
| P2: market data | Select one decision and relevant source first; run governed ingestion with receipts, deduplication and advancing watermarks; enforce expiry at retrieval/narration; add supplier/competitor observations only through qualified sources. | A raw observation can be traced to a current, correctly scoped fact and a specific decision; stale, wrong-currency, wrong-region and mismatched-product cases are rejected. |
| P2: outcome and effect assurance | Inventory real effect sinks; add exact-action, tenant, revision, policy, expiry and idempotency binding where missing. Define post-effect completion checks separately. | Duplicate/replayed requests do not duplicate effects; revoked permits fail; successful tool return cannot falsely close an incomplete business outcome. |
| P3: measured improvements | Compare stage-aware retrieval and Graphiti only on observed failure cohorts; benchmark smaller/larger models on routing and end-to-end latency; benchmark forecasting after a usable series exists. | Predeclared quality, safety, cost and latency thresholds beat the existing baseline on held-out cases. |

For the first invariant suite, cover seven explicit contracts (proposed coverage, not an assertion that these match an earlier document's I1–I7 numbering): identity/revision agreement; budget/quantity/unit agreement; provenance and evidence sufficiency; consent/effective policy agreement; stale/revoked state exclusion; exact-effect authorization and retry safety; post-action completion truth.

Do not make all degraded ancestry an automatic global veto. A failed optional narrator need not block a valid deterministic budget calculation. Track provenance per field/artifact and require the specific evidence and authority needed by the next action.

For market work, freshness needs both observation time and validity appropriate to the signal. Annual mineral statistics and a current stock quote cannot share one arbitrary TTL. Search discovery should produce candidates; verified observations need source identity, product identity, region, currency, tax/shipping basis, observation time and permitted use.

For forecasting, retain simple seasonal/last-value baselines, use rolling time splits, prevent future-covariate leakage, evaluate intervals as well as point error, and assess the resulting inventory/procurement decision. Sparse market-signal rows do not prove the entire business has no order history; inventory the actual target series before deciding readiness. Defer TimesFM-3 production use under its current weight terms and evaluate appropriately licensed candidates only when the data and decision warrant it.

Keep Hippograph feedback in shadow until held-out decision outcomes justify promotion. Retain failed and inconclusive experiments. Defer broad graph replacement, autonomous skill evolution, diffusion models and full formal-verification frameworks. Verified research can inspire small controls immediately without requiring adoption of its entire stack.

## 5. Validation record

Executed:

```text
python -m pytest tests/services/test_local_model_roles.py
  tests/services/test_research_policy.py
  tests/adapters/test_external_research_httpx.py
  tests/services/test_typed_recommendation_stage_coordinator.py
  -q --disable-warnings

Result: 30 tests passed (one combined invocation).
```

Additional temporary, in-memory probes reproduced four collapsed failure causes, policy/report disagreement, degraded-to-accepted trace projection, and overlapping transport after caller timeout. No new regression tests or application fixes were added as part of this review. The next implementation should turn those reproductions into lasting regression coverage.

Remaining evidence needed: real queue-versus-execution breakdown for Claude's 18.5-second turn; successful end-to-end search journey; effective server configuration under the selected launcher; driver dump analysis for definitive crash attribution; complete effect-sink coverage; production-mode authorization and cross-tenant request probes. Existing logs, passing component tests, signatures, or research benchmark scores do not substitute for those checks.
