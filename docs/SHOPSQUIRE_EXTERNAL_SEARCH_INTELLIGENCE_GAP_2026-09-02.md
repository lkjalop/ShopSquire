# ShopSquire — External Search Intelligence Gap (live clickthrough + code trace)

**Date:** 2026-09-02 · **Branch:** `checkpoint/turn-state-consolidation-20260830` · **HEAD:** `87987967` **plus the 42-file uncommitted working tree** (+1,787 / −326; that delta is GPT-5.6's P0-1..P0-6 implementation and it was the surface actually tested — the backend was started at 01:15:40 today, after the last edit).
**Stack under test:** FastAPI :8080 (`RESEARCH_POLICY_PROFILE=demo-safe-auto-v1`, `recommendation_core: primary`, `supplier_autonomy: off`), Vite :5173, SearXNG :8888 (live), Ollama :11434 (qwen3:14b for router + open-world proposer + narration, nomic-embed-text for candidates), Redis :6381, sqlite recording DB.
**Method:** 8 Playwright scenarios (11 turns) through the real browser UI with `USE_MOCK_LLM=0`, every `/api/v1/*` response captured, the Decision Trace modal opened, the Ollama access log and the interpretation-job table read afterwards. Scripts and raw captures: `scratchpad/probe/run.cjs`, `out/<scenario>.json`, `out/*.png`.

> **Environment caveat, stated once.** The stack's Ollama was down when I started; I launched `ollama serve` (`OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=30m`). A warm-up I ran at 10:30 loaded `granite4:micro`, which evicted qwen3:14b; the very first router call of scenario A therefore hit an Ollama `500` mid-reload. That single failure is mine. Every other number below is the platform's.

---

## 0. The one-line finding

**The platform has a model-driven interpretation stage, and in the live run it succeeded 0 times out of 4 attempts** (`open_world_query_proposal` timed out at exactly 6.0 s on every scenario that reached it), **so every "external search" you saw in the browser was produced by the lexical fallback plan** — alias tables, proper-name heuristics, title-keyword scores — with the model reduced to the router's lane/handle vote. The roadmap work of the last two weeks (both the 08-31 R1–R11 list and GPT-5.6's P0-0..P0-6) hardened the plumbing around that stage — receipts, revisions, id unification, fail-closed terminals — without ever measuring whether the stage runs. It does not, on this hardware, with these fixed budgets.

Three numbers to hold onto:

| Measure | Value | Where it comes from |
|---|---|---|
| Open-world model proposals that completed | **0 / 4** (A-t2, C, D, G — all `rejected_or_unavailable`, `latency_ms` 6000/6047/8094/6015, reason recorded as the string `"RuntimeError"`) | `shopping_case_interpretation_jobs.receipt_json` in the recording sqlite; Ollama access log shows the matching `500 | 6.00 s` client-abandoned requests |
| Router model calls that failed | **2 / 9** (one Ollama 500 during reload; one 10.18 s completion abandoned at the 10 s deadline — scenario D) | `backend.err.log` "router model call failed … error=RuntimeError"; Ollama log `200 | 10.18 s` |
| Model calls per turn that finished under 6 s | **3 / 13** (2.7 s, 4.1 s, 3.2 s); the rest 6.3–15.7 s | Ollama `[GIN]` access log, 10:32–10:41 |

Everything else in this document is downstream of that, plus five architectural gaps that would still exist if the model call always succeeded.

---

## 1. What the platform is supposed to do (agreed target, S0–S8)

This is the logic tree we agreed on before the investigation. The right-hand column is what exists today.

| Stage | Responsibility | Today |
|---|---|---|
| **S0 Fact reducer** | Keep budget, quantity, form-factor, named entities across turns as typed facts, never re-parsed from prose | PARTIAL — `canonical_facts` exists; scenario G lost the `$2,500` budget, scenario H accepted the model's *guessed* 32 GB/1 TB/8 GB floors as facts |
| **S1 Intent proposal** | Model emits closed-schema intent incl. `entities[{name, kind, known_to_model}]`; the platform must know when the model *doesn't know* the word | MISSING — router schema has `workload_entities[{kind, name}]` only (`turn_router.py:1581`); no "unknown" bit; "tarae" was routed as *general office laptop* |
| **S2 Identity resolution** | For an unknown entity: search (SearXNG) → model reads titles+snippets → proposes `{canonical_name, kind, publisher, release_state, nearest_equivalent}` → clamp against the retrieved rows | MISSING — `research_outcome._identity()` is a reducer over parser rows or page titles (`research_outcome.py:77`); the proposer prompt *forbids* naming a vendor the buyer did not name (`open_world_query_proposal.py:99-101`); discovery keeps titles only, snippets are dropped (`open_world_research_discovery.py:214`) |
| **S3 Acquisition ladder** T0 cache → T1 enrolled → T2 buyer link → T3 vendor API (Steam) → T4 discovered official origin auto-fetch → T5 nearest-equivalent proxy → T6 model estimate (labelled) | T1 and T3 exist. **T2 is a dead end** (scenario D). **T4 never happens** — every discovery ends at a human "Use for this case" (`shopping_case_open_world_research.py:322`), even under `demo-safe-auto-v1`. T5/T6 absent |
| **S4 Extraction** | Model extracts requirements from the fetched page into the closed attribute vocabulary with `quote_span`s; the existing deterministic critic clamps | HALF — 11 hand parsers (`official_workload_research.py:375`) else regex (`generic_requirement_extractor.py:75`); the critic (`:200`) is the right shape and stays |
| **S5 Feasibility + fit** | Release-state narration ("unreleased", "early access"), budget feasibility, form-factor hedge (desktop *and* mobile workstation shelves when unstated) | PARTIAL — Steam already returns `release_state`/`release_date` but no narration consumes it; one shelf only (scenario F: a sold-out RTX 3050 laptop, relevance 0.0, for "digital twin simulations") |
| **S6 Fit-shortfall → supplier leg** | When research says the floor is X and no in-catalog SKU under budget meets X, offer the sourcing brief carrying identity + claims + budget gap; human-only send | MISSING — `POST /cases/from-off-catalog` exists (uncommitted, `fulfillment_cases.py:765-880`) but is only reachable for *unstocked complements* (`core.py:2050-2100`); brief carries no research |
| **S7 Grounded narration** | One or two lines that restate the ask and what was found/not found, never contradicting the panel | BROKEN in 5/8 scenarios (see §2) |
| **S8 Trace + FinOps** | One id scheme; one outcome object; tokens and cost per turn; ROI link | PARTIAL — two id schemes, three disagreeing outcome views, tokens captured (`router_model_call.py:74-75`) but never surfaced or costed |

---

## 2. Live evidence, scenario by scenario

All turns real model, real SearXNG, real browser. Latency = browser send → terminal answer frame.

| # | Turn(s) | Lat. | Products | What the buyer saw | What actually happened |
|---|---|---|---|---|---|
| **A** | "gaming laptop, is 4000 ok?" → "what about for where winds meet is 3000 ok?" | 30.3 s / 19.5 s | 3 / **0** | t2: "Approved external research completed … found **0** candidate publisher source(s). Review the ranked ownership evidence…" | Entity clamped as `"for where winds meet"`; Steam identity ranking scored 0.825 < 0.90 and rejected (`steam_requirements.py:391`); taxonomy-exact hijack routed to *Wind Wheels & Spinners* (`turn_router.py:2510-2531`); proposer timed out (6.0 s); narration tells the buyer to review evidence that does not exist |
| **B** | same t1 → "actually i need something to simulate PLCs? what do you know of Rockwell Emulate3D?" | 23.8 s / 21.1 s | 3 / 0 | "I treated this as a new workload and **cleared the earlier gaming assumptions**…" then re-asks a gaming question | Rockwell source fetched, **8 claims parsed / 8 held / 0 accepted** because `independent_review.status` is still `…human_signoff_pending` (`config/official_workload_sources.json`, hold at `official_workload_research.py:1304-1379`); the answer's `research_outcome` says parsed 0 while the DOM summary says parsed 8; gaming floors survived the "clear" |
| **C** | "laptop for Agisoft Metashape photogrammetry under $4000" | 31.3 s | 0 | "…found **5** candidate publisher source(s). Review the ranked ownership evidence before approving…" labelled *degraded* | Lexical plan found the exact `agisoft.com/…/system-requirements` page as candidate #1 (score 29) — then stopped for a human click. Proposer timed out. Identity = the page *title*. A spurious duplicate `game` entity. 4.2 s of router transport overhead inside a 31 s turn |
| **D** | "I need hardware for CupixWorks. Please inspect this page: https://www.cupix.com/cupixworks" | 21.1 s | 0 | "…not an enrolled canonical source (no_canonical_enrolled_source_matched). I did not fetch its arbitrary path…" | The platform's own link assessment said `source_class: official_publisher`, `recommended_use: use_for_identity_or_context_then_find_official_requirements` — and **nothing consumes that recommendation**. Router call abandoned at 10 s (Ollama finished at 10.18 s); core → `v2_unavailable`; post-route override at `chat.py:4058-4066` wiped the answer; the async interpretation job was **superseded by the revision bump the same turn caused** (`error_code: case_revision_superseded`); the proposer never saw the domain because R3 redacted the URL to `[submitted official source]` |
| **E** | "tarae recommended specs, what laptop do I need under 3500?" | 27.6 s | **10** | "Yes – $3,500 is ample for **general**. Strong fits start at **$629**…" (a Ryzen 3) | No entity, no research plan, no discovery, no "I don't know this title" — the router simply did not recognise the word and the platform has no signal for that. **This is the headline S1 gap.** |
| **F** | "I need a computer to do digital twin simulations" | 8.3 s | 0 | "I created a provisional shopping case… The shelves are local catalog exploration, not verified fit." One shelf: a **sold-out RTX 3050 laptop, relevance 0.0** | Fast-shortcut path (`/shopping-cases/interpretations`); enrolled NIST context matched lexically → `discovery_queries: []` (enrolled match pre-empts discovery); no desktop/laptop hedge; Decision Trace never loads (id scheme `case-<hex>` vs `sc-<uuid>`) |
| **G** | "can my kid play bloodwalker the new witcher on a 2500 laptop?" | 39.3 s | 0 | "…found **0** candidate publisher source(s). Review the ranked ownership evidence…" + a canned *software* question | Budget 2500 **lost**; lane `COMPARE`; proposer timed out; no "no game called Bloodwalker found; the newest Witcher is unreleased" — although Steam's `release_state` would say exactly that if identity had resolved |
| **H** | "workstation for Rockwell Emulate3D under AUD 6000" → "it also needs to run Factory IO as well" | 7.9 s / 22.9 s | 0 / 0 | t2: "I identified Factory IO, but no enrolled authoritative provider returned current requirements…" | Factory I/O **is** enrolled and approved (`factory_io_official_docs`, aliases "PLC-controlled factory", "PLC factory", "PLC simulation") but "Factory IO" without the slash does not bind lexically; the model's guessed floors became requirements; lane `PROCUREMENT`, node *Laptops* despite "workstation" |

**Hidden taxes measured along the way**
- `shopsquire.telemetry` writes ~6 decision-log events/s from `src/app/security/escalation.py:247` and `src/app/services/ticketing.py:202/300/386` during idle browsing; `/api/v1/cart` took 5.3 s and a product SVG 4.8 s under it.
- Ollama runs qwen3:14b with `-c 4096 -np 1` (one slot, 4 k context). Router, proposer, Steam narration and embeddings serialise on that slot; `OLLAMA_MAX_LOADED_MODELS=2` only helps the embedder (2.3 GB fits, a second 14B does not).
- Both model-failure surfaces throw away the reason: `router_model_call.py:80-81` raises `RuntimeError("router_model_http_error")` without the Ollama error body; `open_world_query_proposal.py:268-282` records `type(exc).__name__`. The receipts literally say `"RuntimeError"`.

---

## 3. What is wrong — five root causes, ranked by how much they explain

### RC1 · The model interpretation stage is budgeted to fail (explains A-t2, C, D, G)
- `open_world_query_proposal.py:60` — shadow executor submits with `timeout_s=6.0`; `:174` clamps `max(1.0, min(timeout_s or 6.0, 10.0))`; `:141` asks for `max_output_tokens=420` with the comment *"keeps a prewarmed 14B local model inside the six-second worker budget"*. On a 12 GB RTX 5070 Ti laptop qwen3:14b needs 6.3–10.2 s per call for prompts this size; 420 output tokens alone is ≈ 12–15 s at the decode rate the Ollama log implies. **It cannot succeed on the reference hardware.** Nothing measures this: `tests/scripts/test_research_runtime_profile.py:46-57` asserts the string `QUERY_PLANNER_PREWARMED=$QueryModel` exists in a PowerShell script.
- The router has the same shape: fixed 10 s deadline, 4 k context, `ROUTER_NUM_PREDICT=320` (`router_model_call.py:47`); D's call completed 180 ms after the deadline and was discarded.
- Failure is then **mislabelled as catalog trouble**: facade `recommendation_facade.py:1341-1368` turns a router failure into `outcome("degraded", reason="grounding:grounded")`; `recommendation_delegation_policy.py:110-125` emits `execution_mode: v2_unavailable`, `semantic_resolution.reason: recommendation_core_unavailable`, `workload_authorization.reason: recommendation_core_unavailable`. The buyer-visible and trace-visible cause is wrong, which is why the 08-24 memory note "degraded blames the CATALOG when the real cause is a deadline" is still true.

### RC2 · There is no identity-resolution stage (explains E, G, A, C's fake identity)
- The only place the model sees the buyer's words for research is the proposer prompt, and that prompt says *"Do not name a vendor unless the buyer named it … Do not include URLs … claims"* (`open_world_query_proposal.py:95-107`) and discards `interpretations` on the way out. The router's `workload_entities` clamp (`turn_router.py:2185-2205`) accepts only literal substrings of the query — it can never say *"tarae" is unknown to me*, or *"bloodwalker the new witcher" is not a real title; nearest is The Witcher IV (unreleased)*.
- `research_outcome.py:77 _identity()` picks `canonical_title`/`resolved_name` from parser rows or falls back to a candidate's page **title**. That is why C reports an identity that is a web page heading.
- Steam already solves half of S2 for games (`steam_requirements.py:357 rank_game_identity_candidates`, `:391 _live_identity_candidate`, returns `release_state`, `release_date`, `publisher`) — but only when the entity string is clean. "for where winds meet" (A) failed the 0.90 gate at 0.825 because `_identity_tokens` (`:347`) strips *the/new/upcoming/of/and* but not the preposition the router leaked.

### RC3 · Discovery is a dead end by design (explains C, D, F)
- `discover_open_world_publishers` (`open_world_research_discovery.py:165`) keeps `domain`, `title`, path — no snippet, no page text — and ranks with `_quality_score` (`:72`): +points for "requirements"/"documentation"/"official" in the title. The exact right page was #1 in C **and then nothing happened**: `shopping_case_open_world_research.py:322` returns `publisher_resolution_required` unconditionally; `execute_case_candidate_research` (`case_publisher_candidate_workflow.py:193`) runs only from the approve endpoint. `demo-safe-auto-v1` grants *discovery*, never *fetch of the discovered origin*.
- The buyer's own link (T2) is inspected, classified `official_publisher / use_for_identity_or_context_then_find_official_requirements`, and then discarded: the post-route override at `chat.py:4038-4066` replaces the whole answer with the not-enrolled message; the early-boundary comment at `chat.py:1800-1805` promises that safe links "continue through semantic routing … and launch governed publisher discovery" — the promise is not kept 2,200 lines later. Worse, R3's URL redaction hands the proposer `[submitted official source]`, so even a working proposer could not use `cupix.com` as a domain hypothesis.
- Enrolled lexical match **pre-empts** discovery (`case_research_plan.py:355 build_case_research_plan`): scenario F matched the NIST digital-twin *context* source and therefore emitted `discovery_queries: []`. Context-only evidence should narrow discovery, not cancel it.

### RC4 · Extraction and source binding are lexical (explains B, H, and the 08-29 "two extractors" finding)
- `_SOURCE_PARSERS` (`official_workload_research.py:375`) is 11 hand parsers; everything else is `extract_generic_requirements` (`generic_requirement_extractor.py:75`), a regex table that read "5 GB free disk space" as `ram_gb>=5` on 08-29 and still does. The critic (`:200`) — deterministic, closed vocabulary, right shape — is the clamp that should sit *behind a model extractor*, not behind regex.
- Entity → enrolled source binding is alias-string matching in the plan builder, never the model's entity: H identified "Factory IO" and the platform said no provider exists while `factory_io_official_docs` sat approved in config. Same class as the Rockwell hold (`config/official_workload_sources.json` → `rockwell_emulate3d_official_requirements.independent_review.status = automated_policy_checks_passed_human_signoff_pending`), which is R1 of the 08-31 roadmap, still not done: 8/8 claims held in B.

### RC5 · Research never reaches the supplier leg (explains why the "shortfall" journey cannot be demonstrated)
- The only trigger for `supplier_rfq_offer` is an **unstocked complement** (`response_stage.py:10-15`, `core.py:2050-2100`). There is no "researched floor > best in-catalog under budget" trigger. `POST /fulfillment/cases/from-off-catalog` (`fulfillment_cases.py:765-880`, uncommitted) builds a `sourcing_brief = {subject, quantity, commercial_terms, constraints}` — no identity, no accepted claims, no budget gap, no source URLs. The RFQ preview therefore cannot say *"Emulate3D requires ≥ 32 GB and a certified GPU; nothing under AUD 6,000 in catalog qualifies; requesting quotes for …"*. Human-only send is intact (good) — but there is nothing worth sending.

### Cross-cutting (S7/S8)
- Contradictory narration is emitted from `chat.py:4217-4223` ("found 0 candidate publisher source(s). Review the ranked ownership evidence…") whenever discovery returns nothing; "cleared the earlier gaming assumptions" (B) is narrated while the gaming floors persist in `constraints_used`.
- Three outcome views disagree on one turn: answer `research_outcome` (parsed 0), `ResearchOutcomeSummary` DOM (parsed 8, "Held for review"), `AmbiguityExplorationPanel` (`AmbiguityExplorationPanel.tsx:100-119`, its own status ladder from `exploration.status/evidence`).
- Two id schemes: shortcut path `sc-case-<hex>` / trace `case-<hex>` / op `interpretation:…:v1`; chat path `sc-<uuid>` / trace `<uuid>` / op `chat:<uuid>`. F and H-t1 (shortcut) cannot open a Decision Trace.
- FinOps: `prompt_tokens`/`output_tokens` are captured per router call (`router_model_call.py:74-75`) and per Ollama client call (`ollama_client.py:69-70`); `timing_breakdown` surfaces ms only (`core.py:167-202`); `token_budget.py` is prod-only unless `TOKEN_BUDGET_ENABLED`; `provider_accounting` counts calls not tokens (`chat.py:2417/2474/3813/4125`). No per-turn cost, no per-case cost, no cost-vs-conversion.

---

## 4. Roadmap verdicts

### 4a. `docs/SHOPSQUIRE_RESEARCH_PATH_REPAIR_ROADMAP_2026-08-31.md` (R1–R11, the "Opus 5" roadmap)

| Item | Claimed | Verdict (live) | Evidence |
|---|---|---|---|
| R1 Rockwell claim hold | CRITICAL | **NOT DONE** | B: 8 parsed / 8 held / 0 accepted; config still `…human_signoff_pending` |
| R2 Politeness becomes the search subject | CRITICAL | DONE | no politeness tokens in any discovery query |
| R3 Budget + raw URL leak into the query | CRITICAL | PARTIAL / **over-fixed** | budget no longer leaks; the URL is redacted to `[submitted official source]` *before the proposer*, deleting the one identity hint the buyer gave (D) |
| R4 CamelCase proper names | LOW | NOT DONE | "CupixWorks" never became a subject term |
| R5 Fallback parser knows four attributes | CRITICAL | NOT DONE | extractor still regex; critic added (good) but it clamps regex, not a model |
| R6 Candidates ranked by shape not subject | TRUST-CRITICAL | PARTIAL | subject-term overlap added (`open_world_research_discovery.py:224`), title-shape score still dominates; C happened to rank right |
| R7 Buyer's own URL is a dead end | HIGH | **NOT DONE** | D |
| R8 Model plans queries for a turn that already ended | HIGH | DONE… and now self-defeating | async job exists; D's job was superseded by the revision bump the URL intake caused, before it could finish |
| R9 UI/UX | — | PARTIAL | panels exist; three views disagree (B); trace does not open on the shortcut path (F, H-t1) |
| R10 Market intel off not shadow | — | NOT DONE in demo | `HIPPOGRAPH_FEEDBACK_ENABLED` absent from `config/feature_flags.json` and the running env; `_mi_mode` (`recommend_intelligence_stage.py:90-107`) → off |
| R11 Works depending on which script | — | PARTIAL | string assertions on scripts; no measured readiness |

**Verdict on the roadmap itself:** correct list of symptoms, right priorities for R1/R5/R7, but it treats the model proposer as a working component to be *protected* (R8) rather than a component that has to be *proven to run*. Items R2/R3/R4/R6 are lexical-plan polish — exactly the reactive determinism the user does not want more of — and they are the ones that got done.

### 4b. GPT-5.6's revised roadmap (claims 1–5, P0-0..P0-6, P1) — implemented as the uncommitted delta

| Item | Verdict | Evidence |
|---|---|---|
| Claim 1 (research path fragmented across two entries) | Correct | shortcut vs chat path, two id schemes, confirmed |
| P0-0 Characterise failures | PARTIAL | `terminal_outcome`/`failure_code` exist; the actual reasons collapse to `"RuntimeError"` / `recommendation_core_unavailable` |
| P0-1 Preserve facts | PARTIAL | A keeps budget; G loses it; H accepts model-guessed floors as facts |
| P0-2 One core execution | DONE | `core_invocation_count` in `execution_evidence`; no double-invoke seen |
| P0-3 Frontend terminal split | PARTIAL | terminal frame lands; three views still disagree |
| P0-4 Unify identity / trace refs | PARTIAL → introduced a regression | shortcut path still `case-<hex>`; revision-bound supersede kills the in-flight interpretation job (D) |
| P0-5 Network outside DB txn | DONE | `db.commit()` before provider work in `shopping_cases.py:419` path |
| P0-6 Runtime profile readiness | DONE as string tests, **FAILS as a measurement** | 0/4 proposals completed; readiness never exercised the model |
| P1 Intelligence | NOT STARTED | — |

**Verdict:** the P0s are correct *plumbing* and they are mostly in — but not one of them touches S1, S2, S3-T4, S4 or S6, and P0-6 gave the team a green light on a component that does not run. The permanent browser gate GPT-5.6 asked for exists in spirit (`frontend/e2e/live-buyer-regression-matrix.spec.ts`) but still runs under `USE_MOCK_LLM=1` — it proves the clamps, not the model.

---

## 5. The fix list — every file and line, in dependency order

Rule applied to every item: **the model proposes over an unbounded space, code validates against a closed vocabulary or retrieved evidence.** No item below adds an alias, a regex, or a title-keyword score. Where a deterministic piece is kept it is a *clamp* (validation), not a *decider*.

### FIX-0 · Make the model stage actually run, and tell the truth when it doesn't (prerequisite for everything)

| # | File:lines | Change | Why this is harness, not patch |
|---|---|---|---|
| 0.1 | `src/app/services/open_world_query_proposal.py:60`, `:174` | Replace the fixed `6.0` with a budget derived from the **measured** model profile: p90 of the last N router `wall_ms` from `AgentRunEventLedger` (`model_execution_gateway.py:126`) × 1.5, floor 8 s, ceiling from `RESEARCH_TOTAL_TIMEOUT_MS`. Expose it in `research_outcome.execution` | A BYO-model platform cannot hard-code a 14B-on-a-5070 latency; the ledger already has the numbers |
| 0.2 | `open_world_query_proposal.py:141` (`max_output_tokens=420`) and the prompt at `:95-107` | Shrink the proposal to what is used: `{entities:[{name, kind, known_to_model, release_state_belief}], nearest_equivalent, queries:[≤3]}` ≈ 120 tokens; drop `interpretations/shared_concepts/divergent_axes` (they are discarded today anyway) | Output tokens are the cost on a 14B; a 3× smaller contract fits an 8B on the same budget — this is the "8B should work" lever |
| 0.3 | `open_world_query_proposal.py:268-282`; `router_model_call.py:80-81`; `turn_router.py:186-191` | Record `result.failure_code` (`model_execution_timeout`, `model_execution_unavailable`, Ollama error body) instead of `type(exc).__name__`; include Ollama's `error` string in metrics | Receipts that say `"RuntimeError"` cannot drive policy or dashboards |
| 0.4 | `src/app/services/recommendation_facade.py:1341-1368`; `recommendation_delegation_policy.py:110-125`; `chat.py` terminal builder for `v2_unavailable` | When `execution_evidence.failure_code` starts with `model_execution_`, the terminal must say **model unavailable/timed out** (`semantic_resolution.reason`, `workload_authorization.reason`, assistant sentence), never `recommendation_core_unavailable` / catalog grounding; never silently fall through to legacy on a router failure in `primary` mode | Blaming the catalog for a model deadline is the false narration the 08-24 note flagged |
| 0.5 | `router_model_call.py:47-49`, `:56-79` | Log `prompt_tokens` against the runtime `num_ctx` (Ollama loaded qwen3:14b with `-c 4096`); if the router prompt approaches the context, the truncation is silent today. Pass `options.num_ctx` explicitly from the runtime profile | Silent prompt truncation is the other way a 4 k slot degrades routing without an error |
| 0.6 | `src/app/services/shopping_case_interpretation_jobs.py:181-190` | Supersede on `buyer_text_hash` change, **not** on `case.revision` bump. URL intake, research receipts and consent bump the revision without changing the buyer's words | D: the platform cancelled its own interpretation |
| 0.7 | `tests/scripts/test_research_runtime_profile.py:46-57` → new `scripts/measure_research_runtime_profile.py` + a startup readiness step in `src/app/main.py:189-203` | Readiness = one real proposer call on the configured model completes inside the computed budget; publish `{model, p50_ms, p90_ms, budget_ms, ok}` on `/readiness` and in `commerce_feature_readiness` (`commerce_feature_readiness.py`, the new `requirement_authority_ready` split) | Turns P0-6 from a grep into a measurement |
| 0.8 | Ops (no code): `OLLAMA_NUM_PARALLEL=2`, explicit `OLLAMA_CONTEXT_LENGTH` ≥ router need, keep `OLLAMA_MAX_LOADED_MODELS=2` | One slot serialises router + proposer + narration; the 6 s budget started *after* the router released the slot in C and still failed | 

Acceptance: re-run scenarios A-t2/C/D/G → `shopping_case_interpretation_jobs.receipt_json.status == "accepted"` in ≥ 3/4; no `RuntimeError` string in any receipt.

### FIX-1 · S1 — the model must be able to say "I don't know this" (E, G)

| # | File:lines | Change |
|---|---|---|
| 1.1 | `src/app/services/recommendation_core/turn_router.py:1581` (schema line) and `router_prompt.py:100-115` | `workload_entities: [{kind: game|software|standard, name, known_to_model: true|false, release_state_belief: released|unreleased|early_access|unknown}]`. Instruction: *"If you do not recognise a named title, still emit it with known_to_model=false; never map an unrecognised title to a generic use case."* |
| 1.2 | `turn_router.py:2185-2205` (entity clamp) | Keep the literal-substring clamp for `name`; **add** the rule: any entity with `known_to_model=false` ⇒ `research_plan_required=true` on the decision and the lane may not resolve to a generic use case (`general`, `office`) for that entity. Do not add title heuristics — the model carries the bit |
| 1.3 | `turn_router.py:2510-2531` (taxonomy-exact hijack) | An entity token sequence that also matches a sold taxonomy node (Wind Wheels & Spinners) must not override a `workload_entities` entry; taxonomy-exact applies to *product* mentions only |
| 1.4 | `turn_router.py:2185` region — `recover_literal_workload_identity` | Strip leading prepositions/articles from the literal recovery so `"for where winds meet"` → `"where winds meet"` — that is string hygiene on a model output, not intent detection |
| 1.5 | `src/app/services/recommendation_core/core.py` decision → plan (where `research_plan` is attached) and `case_research_plan.py:355` | `research_plan_required` from 1.2 must produce a plan with `publisher_status: unresolved` **even when an enrolled context source matches** (F). Enrolled context becomes an `anchor_source`, not a discovery veto |

Acceptance: E → no products, one-line narration "I don't recognise *tarae* — checking whether it is a released title…", discovery runs. G → same, budget 2500 retained in `canonical_facts`.

### FIX-2 · S2 — identity resolution as a model-read-then-clamp stage (A, C, E, G, H)

| # | File:lines | Change |
|---|---|---|
| 2.1 | `src/app/services/open_world_research_discovery.py:165-230` | Retain `snippet` (SearXNG `content`) per row, capped 300 chars, marked `untrusted_discovery_text`. It is *read* by the model, never *compiled* as a claim (the existing rule at `:173` still holds for claims) |
| 2.2 | New `src/app/services/entity_identity_resolution.py` | Input: entity from S1 + top-K discovery rows (domain, title, snippet) + Steam candidates when `kind=game` (`steam_requirements.py:357 rank_game_identity_candidates` already produces them). One model call, closed schema: `{canonical_name, kind, publisher, publisher_domain, release_state, release_date, nearest_equivalent:{name, why}|null, supporting_row_ids:[…]}`. Clamp: every string must be a substring of a cited row (or Steam payload); `publisher_domain` must be one of the retrieved domains; otherwise `identity.status = unresolved`. Confidence is the clamp's, not the model's |
| 2.3 | `steam_requirements.py:391` (`_live_identity_candidate`) | Keep the 0.90/0.15 gate as the *offline* clamp; when the gate fails, hand the ranked candidates to 2.2 instead of returning `None` — the model breaks the tie, the clamp keeps it honest |
| 2.4 | `research_outcome.py:77` (`_identity`) and `:169-189` | Identity comes from 2.2's clamped output; page titles are no longer an identity source. `discovery_status: degraded` only when all queries failed — not when one of five did (C) |
| 2.5 | `workload_grounding.py:102-200` (`resolve_named_workloads`) and `workload_evidence.py:60` | Add a provider for `kind=software` that binds a **resolved identity** (2.2) to enrolled sources by `publisher_domain`/`canonical_name`, replacing alias-string binding for the model path. Factory I/O (H) binds because `docs.factoryio.com` is the enrolled canonical host, whatever the buyer typed |
| 2.6 | `open_world_query_proposal.py:95-107` | Delete *"Do not name a vendor unless the buyer named it"*; replace with *"name the publisher you believe owns the title; it is a discovery hint only"*. The clamp in 2.2 (domain must be retrieved) is what keeps it safe |
| 2.7 | `chat.py:4038-4066` and `src/app/services/buyer_evidence_source_resolution.py:32` (the R3 redaction that produces `[submitted official source]`) | A safe, not-enrolled buyer link becomes a **T2 discovery seed**: `{domain, path_hash, link_assessment}` is passed to 2.2 as a row; the answer is not overwritten with the not-enrolled message; the trace keeps the zero-fetch receipt. Redact the path from prompts, keep the registrable domain |

Acceptance: A-t2 → identity "Where Winds Meet", Steam release_state surfaced; C → identity "Agisoft Metashape", publisher_domain agisoft.com; D → identity "CupixWorks", cupix.com; G → identity unresolved + nearest_equivalent "The Witcher IV (unreleased)".

### FIX-3 · S3-T4 — auto-fetch the discovered official origin under policy (C, D, E, G)

| # | File:lines | Change |
|---|---|---|
| 3.1 | `src/app/services/shopping_case_open_world_research.py:322` (`publisher_resolution_required`) and `case_publisher_candidate_workflow.py:36/193` | After `persist_discovered_candidates`, if the top candidate's domain == identity `publisher_domain` (2.2) **and** the policy grants `auto_fetch_official_origin`, call `execute_case_candidate_research` in the same governed operation; record `approval_basis: policy:demo-safe-auto-v1`. Otherwise fall back to today's human "Use for this case" |
| 3.2 | `config/research_policies.json:13-20` (`demo-safe-auto-v1`) and `src/app/services/research_policy.py:17-48` | Add two grants next to `auto_authorize_read_only`: `auto_fetch_discovered_official_origin: true` and `pasted_url_policy: "identity_seed_zero_fetch"` (the link's registrable domain seeds discovery; the submitted path is still never fetched). Kill switch: admin flag (tenant-scoped, feature-flag loader) **and** a per-case "stop automatic fetch" action in the Decision Trace. Default on for the demo profile, off in `buyer-consent-v1` / `network-disabled-v1` |
| 3.3 | `official_workload_research.py:827 research_official_sources` | Accept a *discovered* origin (not just enrolled config) with the existing SSRF/allowlist/robots/size checks; tag claims `authority: discovered_official_pending_review` |
| 3.4 | `frontend/src/components/AmbiguityExplorationPanel.tsx:100-119`, `PublisherCandidates` component | Show "fetched automatically under policy X — stop" rather than only "Use for this case" |

Acceptance: C → agisoft page fetched, claims extracted, products ranked against them, under $4,000, in one turn.

### FIX-4 · S4 — model extraction behind the existing critic (B, H, 08-29 finding)

| # | File:lines | Change |
|---|---|---|
| 4.1 | New `src/app/services/requirement_extraction_model.py`; wire in `official_workload_research.py` where `_SOURCE_PARSERS` (`:375`) misses | One model call over the fetched page text (chunked): closed attribute vocabulary from `generic_requirement_extractor.py` (`ram_gb`, `gpu_vram_gb`, `storage_gb`, `cpu_cores`, `os`, …), each with `quote_span` (verbatim substring) and `tier: minimum|recommended` |
| 4.2 | `generic_requirement_extractor.py:200 critique_extracted_requirements` | Keep as the clamp; add: reject any claim whose `quote_span` is not a substring of the page; reject unit mismatches ("5 GB free disk space" cannot ground `ram_gb`) |
| 4.3 | `generic_requirement_extractor.py:75` | Demote regex to **T6-style fallback** only when the model extractor is unavailable; label claims `authority: heuristic` so they never become `accepted` |
| 4.4 | `config/official_workload_sources.json` → `rockwell_emulate3d_official_requirements.independent_review.status` | Flip to the approved value (R1) **or** make the hold advisory (`held_pending_signoff` shown, still ranked) — 8/8 held with zero narration is the worst of both |

### FIX-5 · S5 — feasibility and form-factor hedge (F, G, E)

| # | File:lines | Change |
|---|---|---|
| 5.1 | `core.py` fit stage (where `workload_fit` is produced) | Consume `release_state`/`release_date` from Steam and from 2.2: narration must state *unreleased / early access / released <date>* before any product |
| 5.2 | `core.py` shelf assembly (single `shared` shelf today, F) | When the buyer says "computer/workstation/machine" with no form factor and the researched floor is met by both, produce **two shelves** (`Desktop workstations`, `Mobile workstations`) with the same floor; never show a 0.0-relevance sold-out SKU as the answer |
| 5.3 | `turn_router.py` handle choice for "workstation" (H → *Laptops*) | The model's `wanted_category` should win over the lexical default; clamp only to sold nodes |

### FIX-6 · S6 — fit-shortfall → sourcing brief, human-only send

| # | File:lines | Change |
|---|---|---|
| 6.1 | `core.py:2050-2100` (complement offers) and `response_stage.py:10-15` | Add a second trigger: `accepted_claims` define a floor **and** no in-catalog product under `canonical_facts.budget` meets it ⇒ `off_catalog = {mode: "source", reason: "fit_shortfall", identity, floor, best_in_catalog, budget_gap}` |
| 6.2 | `src/app/routers/fulfillment_cases.py:765-880` (`OffCatalogSourcingBody`, `sourcing_brief`) | Carry `identity`, `accepted_claim_ids`, `source_urls`, `budget_gap`, `research_outcome.operation_id` into `state_json.sourcing_brief`; the RFQ preview renders them |
| 6.3 | `frontend/src/lib/api.ts:321-345`, `OffCatalogSourcingCard.tsx:23`, `App.tsx:2436-2447`, `chat.py:4468-4478` | Thread the new fields; card copy: "Researched floor … nothing under AUD 6,000 qualifies — draft a supplier request (you send it)" |
| 6.4 | Unchanged, by design | `FULFILLMENT_SUPPLIER_TRANSPORT=sandbox`, `FULFILLMENT_AUTONOMOUS_RFQ=0`; the send stays human-only |

### FIX-7 · S7 — narration that cannot contradict the evidence

| # | File:lines | Change |
|---|---|---|
| 7.1 | `chat.py:4217-4223` | Never say "review the ranked ownership evidence" when `candidate_count == 0`; the sentence must be generated from `research_outcome` (`identity`, `discovery_status`, `failure_code`) — one composer, priority ladder, like the `set_message` composer in core |
| 7.2 | `chat.py` subject-switch narration ("cleared the earlier gaming assumptions", B) | Emit only when `constraints_used` actually lost the prior floors; otherwise say what was kept |
| 7.3 | Steam/2.2 output → narration | "*Bloodwalker* isn't a title I can find; the newest Witcher (The Witcher IV) is unreleased — here is what it is likely to need and what $2,500 buys today" — the two-line summary you asked for |

### FIX-8 · S8 — one id, one outcome, cost per turn

| # | File:lines | Change |
|---|---|---|
| 8.1 | `src/app/routers/shopping_cases.py:419` (`create_case_interpretation`) | Emit the same `sc-<uuid>` / `<uuid>` / `chat:<uuid>` scheme as chat; retire `sc-case-<hex>`/`interpretation:…:v1` — F/H-t1 traces then open |
| 8.2 | `research_outcome.py:104 build_research_outcome` | Make it the **only** source for `ResearchOutcomeSummary`, `AmbiguityExplorationPanel` status and the answer; delete the panel's own ladder (`AmbiguityExplorationPanel.tsx:100-119`) |
| 8.3 | `core.py:167-202` (`timing_breakdown`), `router_model_call.py:74-75`, `ollama_client.py:69-70`, `model_execution_gateway.py:126` | Surface `prompt_tokens`, `output_tokens`, `model`, `estimated_cost` per model call per turn; roll up per case in the trace |
| 8.4 | `token_budget.py`; `recommend_intelligence_stage.py:90-107` | Enable per-tenant token budgets in the demo profile with a soft cap that degrades to T1/T3-only (no proposer) — the DDoS-prompt guard you described; when `HIPPOGRAPH_FEEDBACK_ENABLED` is on, join model cost to conversion events for cost-per-converted-case |
| 8.5 | `src/app/security/escalation.py:247`, `src/app/services/ticketing.py:202/300/386`, `observability/telemetry.py:119` | Rate-limit or batch idle decision-log emitters; measured ~6/s degrading cart/SVG latency to 5 s |

---

## 6. The BYO-model harness contract (what makes an 8B work)

The question you asked — *"if the owner wants an 8B or smaller, the platform should work due to better harness engineering"* — is answered by four properties, none of which exist yet:

1. **Budgets derived from measurement** (FIX-0.1/0.7): the platform times the configured model at startup and after every N calls; no literal seconds in service code.
2. **Small closed contracts** (FIX-0.2, 1.1, 2.2, 4.1): each model call asks for ≤ ~150 output tokens of JSON that a clamp can verify. Big models don't need it; small models can't do without it.
3. **Retrieve-then-read, never recall** (FIX-2, 3, 4): the model reads snippets and pages the platform fetched; knowledge cutoff stops mattering (qwen3:14b not knowing "tarae" is fine if it can read the search results).
4. **Graceful degradation with truthful labels** (FIX-0.4, 8.4): when the model stage is over budget or over quota, the platform drops to T1/T3 and *says so* — it does not blame the catalog or serve a general-purpose laptop.

Cost control follows: with 2 and 4 in place the per-turn token ceiling is bounded and known, a prompt-flood degrades to zero-model paths under the tenant budget, and 8.3/8.4 give the market-intelligence ROI view (model spend vs converted cases).

---

## 7. Permanent browser gate (re-run after each fix)

`scratchpad/probe/run.cjs` already drives these; move it to `frontend/e2e/live-external-search-battery.spec.ts` and run it **without** `USE_MOCK_LLM`. Pass criteria per scenario:

| Scenario | Must be true |
|---|---|
| A-t2 "for where winds meet" | identity = Where Winds Meet; release_state narrated; ≥ 1 product under $3,000 or a truthful shortfall |
| B-t2 Rockwell | claims accepted (or held **with** narration); gaming floors gone from `constraints_used`; three views agree |
| C Agisoft | agisoft.com fetched automatically; ≥ 1 claim accepted; products ranked under $4,000 in one turn |
| D pasted URL | cupix.com used as identity seed; discovery ran; no answer overwrite |
| E tarae | no products until identity resolves; narration says unknown title → researching |
| F digital twin | two shelves (desktop / mobile workstation); no 0.0-relevance sold-out SKU |
| G bloodwalker | budget 2500 retained; nearest-equivalent narration; release_state |
| H Factory IO | binds to `factory_io_official_docs` via identity; node ≠ Laptops for "workstation" |
| All | `interpretation_jobs.receipt_json.status == accepted` ≥ 75 %; no `"RuntimeError"` string in receipts; trace opens on every path; tokens + cost present in `timing_breakdown` |

---

## 8. What not to do

- Do not add aliases for "Factory IO", "CupixWorks", "tarae" — every one is a symptom of FIX-1/2 missing.
- Do not raise the proposer timeout to a new literal — derive it (FIX-0.1).
- Do not ship R4/R6-style ranking polish; ranking should come from identity (2.2), not title shape.
- Do not extend `_SOURCE_PARSERS`; the 12th hand parser is the 08-29 "two extractors" bug again.
- Do not touch the human-only supplier send.

---

## Appendix A — raw model-call timings (Ollama access log, 10:32–10:41)

```
10:32:46  500  12.04 s   router (A-t1; reload after my granite eviction — environment)
10:33:13  200   2.71 s   router (A-t2)
10:33:27  500   6.01 s   proposer (A-t2)  ← client abandoned at 6.0 s
10:35:28  200   4.06 s   router (B-t1)
10:35:59  200   3.22 s / 0.52 s  (B-t2)
10:36:04  200   1.69 s   /api/embed (candidates)
10:36:45  200   7.30 s   router (C)
10:37:00  500   6.01 s   proposer (C)     ← abandoned
10:37:37  200  10.18 s   router (D)       ← completed 0.18 s after the platform gave up
10:37:49  500   6.00 s   proposer (D)     ← abandoned
10:38:15  200   7.41 s   router (E)
10:39:51  200   9.48 s   router (G)
10:40:10  500   6.01 s   proposer (G)     ← abandoned
10:41:19  200   6.30 s   router (H-t2)
```
Runner: `llama-server … -c 4096 -np 1`; qwen3:14b 9.2 GB of 11.0 GB free VRAM.

## Appendix B — running env that mattered
`ROUTER_MODEL=qwen3:14b` · `OPEN_WORLD_QUERY_MODEL=qwen3:14b` · `OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED=1` · `EXTERNAL_RESEARCH_ENABLED=1` · `EXTERNAL_RESEARCH_AUTO_AUTHORIZED=1` · `STEAM_REQUIREMENTS_LIVE_ENABLED=1` · `RESEARCH_LANE_TIMEOUT_MS=8000` · `RESEARCH_TOTAL_TIMEOUT_MS=10000` · `EXTERNAL_RESEARCH_SEARCH_URL=http://127.0.0.1:8888/search?q={query}&format=json` · `USE_MOCK_LLM=0` · `HIPPOGRAPH_FEEDBACK_ENABLED` unset.
