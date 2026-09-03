# ShopSquire External Search — Delta Verification, Current Architecture and Remaining Gap

**Date:** 2026-09-02 · **Branch:** `checkpoint/turn-state-consolidation-20260830` (dirty worktree, HEAD 87987967)
**Verifies:** GPT-5.6's "Implemented and live" report against the live stack (`.artifacts/identity-auto-fetch-live/`, qwen3:14b resident, `RESEARCH_POLICY_PROFILE=demo-safe-auto-v1`, `OPEN_WORLD_IDENTITY_RESOLVER_ENABLED=1`, `REQUIREMENT_MODEL_EXTRACTION_ENABLED=1`).
**Method:** code read (file:line), an independent 8-scenario Playwright clickthrough (A–H below, different prompts from GPT-5.6's battery, deliberately *non-instructive*), the model latency ledger from `agent_run_event`, and direct probes of the Steam connector.
**Companion:** `docs/SHOPSQUIRE_EXTERNAL_SEARCH_INTELLIGENCE_GAP_2026-09-02.md` (the S0–S8 target logic tree and FIX-0..8). This document says what of that is now done, what is not, and what to do next.

---

## 0. Executive summary (read this if nothing else)

GPT-5.6's report is **accurate about the safety and governance layer and inaccurate about the buyer outcome.** Every claim about *what the platform refuses to do* verifies (no arbitrary URL fetch, tracking params stripped, human-only supplier send, kill switches, cited-row identity clamp, no unrelated-title promotion). Almost nothing about *what the platform now does for the buyer* survives a non-instructive prompt:

| User's own acceptance examples | Result on the live stack today |
|---|---|
| "tarae recommended specs, what laptop do I need under 3500?" (E) | **Total miss.** Router emits no entity, no research runs, 10 office laptops from $629, narration "Yes – $3,500 is ample for general … For office, which level fits?" Steam resolves `Tarae` → **"TARAE: The Unbound", release "To be announced"** in 0.8 s when asked directly — nobody asked it. |
| "I need a computer to do digital twin simulations" (F) | **Contradiction.** "These all handle engineering simulation, starting at $3,499." next to **Found 0 products**. `architecture_alternatives` (laptop / mobile workstation / fixed workstation / server) is computed server-side and **rendered nowhere** — the frontend has zero references to it. |
| "what about for where winds meet is 3000 ok?" (A) | Identity resolved ("Where Winds Meet") but candidates are aggregators → no auto-fetch → 0 products, generic "found 12 candidate publisher source(s)". The Steam connector returns **min 16 GB / GTX 1060 6 GB / 130 GB, released 14 Nov 2025** in 0.6 s for the canonical title — but it was asked with the router's raw string "for where winds meet" *before* identity resolution and returned nothing. |
| "I need a laptop for Agisoft Metashape … under $4000" (C) | Auto-fetch **worked** (9 held claims from agisoft.com in 16.5 s) and then the terminal contract, the narration and the UI **all deny it** ("Parsed 0 · Held 0", "no enrolled authoritative provider returned current requirements"). 40.5 s turn. |
| "…it also needs to run Factory IO as well" (H-T2) | Enrolled Factory I/O source returned **3 accepted claims** + Rockwell **8 provisional**; terminal `research_outcome` says 0/0/0, `workload_authorization` says "no enrolled provider", narration says "I need approved current requirements for the added workload". |

The pattern is one architectural fact, not many bugs: **the platform now has three evidence paths (enrolled sources, connector registry, open-world case research) and one terminal contract that reads none of them.** Plus two capacity facts: the router still runs on a fixed 12 s deadline with a 17.5 % timeout rate, and model extraction times out 15/17 because a 14 k-char page is pushed at a 4096-context runner.

The good news: the expensive parts (identity resolver, proposer, auto-fetch policy, Steam connector, enrolled parsers, off-catalog sourcing endpoint) exist and work in isolation. **The remaining work is wiring order and one contract, not new intelligence.** Section 6 gives the ordered roadmap; the first three items are each < 1 day and would flip A, C, E and H from "miss" to "answered".

---

## 1. Claim-by-claim verdict

Legend: ✅ fixed & live-verified · 🟡 built but not effective for the buyer · ❌ not fixed / claim does not hold

| # | GPT-5.6 claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Model-assisted identity resolution, no alias tables | ✅ | `open_world_identity_resolution.py` (`resolve_open_world_identity`, prompt `open-world-identity-resolution`, ≤8 cited rows, `_grounded` clamp, one semantic repair). Live: 53/53 completed, p50 4.6 s, p90 5.3 s. A→"Where Winds Meet", C→"Agisoft Metashape", D→"CupixWorks", G→"The Witcher 3: Songs of the Past". |
| 2 | One bounded semantic repair | ✅ | same file; `model_calls` 1–2 in receipts. |
| 3 | Identity no longer requires proven publisher ownership | ✅ | `research_outcome.py` prefers `status == resolved`; A/G resolve from aggregator rows. |
| 4 | Official-origin auto-fetch requires cited identity + direct-origin evidence + policy approval + no kill switch | ✅ (policy) 🟡 (reach) | `research_policy.py:62 resolved_origin_auto_fetch_policy`, `shopping_case_open_world_research.py:162 official_origin_auto_fetch_eligible`, `:393-435` branch. Fired once in 8 scenarios (C). A/D/G: `explicit_case_approval_required` because deterministic queries land on aggregators/support sites, never the publisher's requirements page. |
| 5 | Arbitrary pasted URLs not fetched; tracking params stripped | ✅ | `buyer_link_assessment.py:16/88/147`; D receipt `arbitrary_submitted_path_fetch_allowed: false`, `canonical_fetch_eligible: false`. **Side effect:** buyer pasted the publisher's own page (`source_class: official_publisher`) and still got 0 requirements after 22 s. |
| 6 | Canonical identities propagate to workload authorization and revision-bound research outcome | 🟡 | Propagates to `identity_only_workload_authorization` (open-world path only). Does **not** propagate to `resolve_named_workloads` / the Steam connector (`workload_grounding.py:104-140` runs *before* identity resolution with the raw router entity — A: `"for where winds meet"` → `steam: no_authoritative_result`). |
| 7 | Failed identity cannot promote an unrelated search title | ✅ | `research_outcome.py` `_identity`; no false promotion seen in A–H. |
| 8 | Raw research rebound to terminal case revision | ❌ **this is the defect** | `chat.py:5093-5099` `TurnCommit.research = {policy, execution_state, ambiguity_exploration, source_resolution, workload_authorization}` — omits `server_research_result.research` (claims / provisional_claims / receipts / `official_origin_auto_fetch`). `chat.py:5124-5126` then **overwrites** `out["research_outcome"]` with the read model built from that partial dict, and `:5210-5214` overwrites `server_research_result.research_outcome` with the same zeroed object. Result: C 9 held → "Held 0"; H-T2 3 accepted + 8 provisional → "Parsed 0"; B 8 provisional → "Parsed 0". |
| 9 | Shortfall/RFQ projection retains identity/claims/sources/budget gap/nearest alternative | 🟡 | `fulfillment_cases.py:764 OffCatalogSourcingBody`, `:780 POST /cases/from-off-catalog` exist and are human-only. Projection only fires at `shopping_cases.py:1236` on **explicit requirement acceptance** with `accepted and not shelf_products`. Auto-fetched/held claims never reach acceptance on the chat path (item 8, 12) → leg unreachable from chat in all 8 scenarios (`off_catalog: null` everywhere). |
| 10 | Supplier send human-only | ✅ | `supplier_contacted: False`, `supplier_send: human_only_not_authorized`; `FULFILLMENT_AUTONOMOUS_RFQ=0`. Invariant intact. |
| 11 | Live A–H Playwright matrix passed in 4 min | 🟡 | `frontend/e2e/live-external-search-battery.spec.ts` prompts are instructive ("Please inspect this page …") and assertions check presence of panels, not correctness of the answer. My non-instructive matrix: 2/8 scenarios produce a buyer-usable answer (B-T1, E — and E is wrong). |
| 12 | Six Decision Trace tabs / cart empty / frontend build | ✅ (as stated) | But no frontend reference to `architecture_alternatives` or `official_origin_auto_fetch`; held claims card only renders from `data.buyer_requirement_claims` (`App.tsx:2649`), which chat.py fills only from pasted text (`chat.py:3475-3494`). |
| 13 | qwen3:14b resident; proposer p50 5.6 s / p90 6.3 s / deadline 10 s | ✅ | Ledger: proposer n=58 p50 5.5 s p90 6.3 s, 58/58 completed. (Model had been evicted before my run — `/api/ps` empty — re-warmed with keep_alive 30 m; `ROUTER_PREWARM_REQUIRED=1` does not keep it warm across idle.) |
| 14 | Outstanding: 8 sources need human review; SQLite; PG rerun; `release_state` may be `unknown` | ✅ honest | `release_state` was `unknown` in **every** scenario (A, D, G) even when the cited snippet said "confirmed for 2027". |

**Score:** 8 ✅ · 5 🟡 · 1 ❌ — but the one ❌ (item 8) neutralises items 4, 6, 9 and 12 for the buyer.

---

## 2. Live probe results (non-instructive prompts, fresh sessions)

| Sc. | Prompt(s) | Turn ms | Products | Identity | Auto-fetch | Terminal contract | What the buyer sees |
|---|---|---|---|---|---|---|---|
| A | gaming laptop 4000 → "what about for where winds meet is 3000 ok?" | 15.5 s / 17.6 s | 3 / 0 | ✅ Where Winds Meet (aggregators) | ✗ `explicit_case_approval_required` | held / identity_only / release `unknown` | "found 12 candidate publisher source(s)… Review the ranked ownership evidence" — no answer to "is 3000 ok?" |
| B | gaming laptop 4000 → "actually i need something to simulate PLCs? what do you know of Rockwell Emulate3D?" | 11.8 s / 14.2 s | 3 / 0 | enrolled source | 8 provisional (human sign-off pending) | "Parsed 0 · Held 0" | "cleared gaming… For gaming, which level fits?" (stale template) |
| C | "I need a laptop for Agisoft Metashape photogrammetry under $4000" | **40.5 s** | 0 | ✅ Agisoft Metashape | ✅ **9 held claims**, agisoft.com, 16.5 s | "Parsed 0 · Held 0 · identity only" | "no enrolled authoritative provider returned current requirements. Provide an approved requirements document…" |
| D | "I need hardware for CupixWorks. Please inspect this page: https://www.cupix.com/cupixworks" | 22.0 s | 0 | ✅ CupixWorks (support.cupix.works rows) | ✗ `explicit_case_approval_required` | held / identity_only | Same generic "found 12 candidate…" text; pasted official page classified `official_publisher` but not fetched |
| E | "tarae recommended specs, what laptop do I need under 3500?" | 13.9 s | **10 generic** | — (router emitted no entity) | — | `research_status: not_applicable` | "Yes – $3,500 is ample for general… standard office — from ~$500 / executive — from ~$900" |
| F | "I need a computer to do digital twin simulations" | 18.7 s | 0 | — | — | catalog `blocked`, `fetch_status: completed` (NIST context source) | "These all handle engineering simulation, starting at $3,499." + **Found 0 products**; no form-factor shelves |
| G | "can my kid play bloodwalker the new witcher on a 2500 laptop?" | 26.3 s | 0 | ✅ The Witcher 3: Songs of the Past (allthings.how, vulkk.com) | ✗ | release `unknown` (snippet: "confirmed for 2027"); budget 2500 **not parsed** (`budget_max: None`); router 2nd entity `"bloodwalker the new witcher on a 2500 laptop?"` | generic "found 2 candidate publisher source(s)" |
| H | "workstation for Rockwell Emulate3D under AUD 6000" → "it also needs to run Factory IO as well" | 13.1 s / 12.5 s | 0 / 0 | enrolled ×2 | T2: **Factory I/O 3 accepted** + Rockwell 8 provisional | "Parsed 0 · Held 0", `workload_authorization: no_enrolled_provider_result` ×2 | T1 honest hold; T2 "I need approved current requirements for the added workload" (Factory I/O's *are* approved) |

Direct Steam connector probe (`connectors/steam_requirements.py:503 get_game_requirements`, `allow_live=True`):

```
'for where winds meet'             -> None                                   (1.4 s)  <- what the core asked
'Where Winds Meet'                 -> released 14 Nov 2025, min 16 GB / GTX 1060 6 GB / 130 GB  (0.6 s)
'Tarae'                            -> "TARAE: The Unbound", release "To be announced", reqs TBU   (0.8 s)
'The Witcher 3: Songs of the Past' -> None   (expansion is not a separate Steam app)
```

---

## 3. Measured model ledger (live sqlite `agent_run_event`, after the probe)

| prompt_id | n | p50 | p90 | max | outcomes | deadline | verdict |
|---|---|---|---|---|---|---|---|
| `recommend-router-v2` | 143 | 6.0 s | **12.0 s** | 12.1 s | 118 completed / **25 timeout (17.5 %)** | fixed `ROUTER_TIMEOUT_SEC` 12 (`turn_router.py:65`) | p90 == deadline ⇒ the deadline is the p90. Not derived from the ledger (proposer's is). |
| `open-world-identity-resolution` | 53 | 4.6 s | 5.3 s | 9.2 s | 53/53 completed | derived (`open_world_identity_resolution.py:168`) | healthy |
| `open-world-query-proposal` | 58 | 5.5 s | 6.3 s | 6.7 s | 58/58 completed | derived (`open_world_query_proposal.py:264`) | healthy **but consumed only as a receipt** (600 ms wait, `shopping_case_open_world_research.py:82`); deterministic queries still drive discovery |
| `official-page-requirement-extraction` | 17 | 12.0 s | 18.0 s | 18.0 s | **15 timeout / 2 completed** | 12 s (`official_workload_research.py:394`), 18 s env | dead: `model_requirement_extractor.py:49` sends `text[:14000]` (~4 k tokens) to a runner at `num_ctx=4096` (`OLLAMA_NUM_CTX` unset, `llm_provider.py:335`); regex fallback does all the work |
| token usage | — | — | — | — | — | — | **not recorded** — `agent_run_event` has no token/cost columns (`details_json` = output hash only). S8 FinOps not started. |

---

## 4. Current-iteration architecture (what actually runs today)

Legend: `[M]` model-decided · `[D]` deterministic · `[R]` computed but receipt-only (not consumed) · `[X]` computed but never rendered · `[!]` defect

```
 buyer turn ─────────────────────────────────────────────────────────────────────────────────────
   │
   ▼
 ┌─ S0 fact reducer [D] ────────────────────────────────────────────────────────────────────────┐
 │  budget grammar / quantity / URL intake (buyer_link_assessment: utm strip, no fetch)  ✅       │
 │  [!] "on a 2500 laptop" not parsed (G)                                                          │
 └──────────────────────────────────┬────────────────────────────────────────────────────────────┘
                                    ▼
 ┌─ S1 router  recommend-router-v2 [M] qwen3:14b, fixed 12 s deadline, 17.5 % timeouts [!] ───────┐
 │  emits lane / node / workload_entities / subject_role / entity_frame                             │
 │  [!] no known_to_model bit → unknown titles ("tarae") emit NO entity → nothing downstream (E)   │
 │  [!] entity strings dirty: "for where winds meet", "…on a 2500 laptop?"                          │
 │  validate_subject_role [D] regex wins unless UNRESOLVED → "laptop for X" = PROCURE_SUBJECT (C)  │
 └──────────────────────────────────┬────────────────────────────────────────────────────────────┘
                                    ▼
 ┌─ core (recommendation_core/core.py) [D] ──────────────────────────────────────────────────────┐
 │  resolve_named_workloads (workload_grounding.py:104)  ← connector registry ONLY (Steam, games) │
 │     asked with RAW router entity, BEFORE identity resolution  [!]  → "no_authoritative_result"  │
 │  retrieval + fit + set_message (core.py:1757 "These all handle …")                              │
 │  [!] message composed while products exist; products later cleared by semantic block (F)       │
 └──────────────────────────────────┬────────────────────────────────────────────────────────────┘
                                    ▼
 ┌─ chat.py post-route  (server-owned research, awaited ≤ 45 s inside the turn) ──────────────────┐
 │                                                                                                 │
 │   path 1  ENROLLED  shopping_case_enrolled_research.py                                          │
 │     official_workload_sources.json (20) → _SOURCE_PARSERS [D] → compile_source_claims           │
 │        parser ▸ model extraction [M] (15/17 timeout [!]) ▸ regex fallback [D] ▸ critic [D]       │
 │     independent_review.status pending → claims PROVISIONAL (Rockwell :136)  [human field]       │
 │     Factory I/O → 3 ACCEPTED (H-T2)                                                             │
 │                                                                                                 │
 │   path 2  OPEN-WORLD  shopping_case_open_world_research.py                                      │
 │     proposer [M] → [R] 600 ms wait, deterministic queries [D] drive SearXNG                      │
 │     discovery → snippets retained → S2 identity [M] cited-row clamp ✅                           │
 │     auto-fetch policy [D] ✅ → execute_case_candidate_research → claims HELD (C: 9)              │
 │     [!] no structured-store tier (Steam) after identity; release_state always "unknown"          │
 │     [!] publisher origin rarely in candidate set (games → aggregators) → auto-fetch rarely fires │
 │                                                                                                 │
 │   path 3  CONNECTOR  (already ran in core, above)                                               │
 │                                                                                                 │
 │   ┌───────────────── terminal contract  chat.py:5048 TurnCommit → build_turn_read_model ──────┐ │
 │   │ research = {policy, execution_state, ambiguity_exploration, source_resolution,             │ │
 │   │             workload_authorization}          ← NONE of path 1/2 claims  [!!]               │ │
 │   │ research_outcome := zeros; overwrites srr.research_outcome (:5124, :5210)                  │ │
 │   │ recommendation_status "held"; catalog_authority blocked/unknown                            │ │
 │   └────────────────────────────────────────────────────────────────────────────────────────────┘ │
 │   narration [D]: publisher_resolution_required → "found N candidate publisher source(s)…"       │
 │                  else server assistant_message (None) → stale core message  [!]                 │
 │   architecture_alternatives [X]  off_catalog: null (needs human acceptance first)  [!]           │
 └──────────────────────────────────┬────────────────────────────────────────────────────────────┘
                                    ▼
 ┌─ frontend App.tsx ────────────────────────────────────────────────────────────────────────────┐
 │  renders: research_outcome summary (zeros) · ambiguity panel · candidates "Use for this case"   │
 │  claims card ONLY from data.buyer_requirement_claims (:2649) ← chat.py fills from paste only     │
 │  no reference to architecture_alternatives / official_origin_auto_fetch / identity_resolution    │
 └───────────────────────────────────────────────────────────────────────────────────────────────┘
                                    ▼
   shortfall → sourcing leg  (fulfillment_cases.py:780, human-only ✅)  reachable only via manual accept
```

### Why this shape produces the observed failures

1. **Ordering:** connector (Steam) runs in the core with the raw entity; identity resolution runs later in chat.py. The canonical title never flows back. A is answerable in 0.6 s.
2. **Three registries, one contract:** enrolled manifest (`official_workload_sources.json`), connector registry (`connectors/workload_evidence.py`), open-world case candidates — `build_research_outcome` and `workload_authorization` each read one of them. `workload_grounding.py:104` is connector-only, so every *software* workload is "no enrolled provider" even when the enrolled parser just returned accepted claims (H-T2).
3. **Rebinding drops evidence:** `chat.py:5093-5099` is the single line-range that zeroes C, B and H.
4. **Narration composed before the terminal state:** `set_message` runs in the core; the semantic block clears products afterwards (F); the server research branch returns `assistant_message=None` so the pre-research message survives (B "cleared gaming…").
5. **No unknown-entity path:** when the 14B does not know a title it emits nothing, and nothing downstream is triggered (E). This is the `known_to_model` gap from FIX-1, unchanged.

---

## 5. Delta gap mapped to the target logic tree (S0–S8) and FIX-0..8

| Stage | Target (companion doc) | Now | Gap | Anchor |
|---|---|---|---|---|
| S0 fact reducer | budget/qty/URL facts once | ✅ mostly | "on a 2500 laptop" (G) unparsed | `budget_grammar.py` |
| S1 intent proposal with `known_to_model` | model says *what it thinks the subject is* + whether it knows it | ❌ | no `known_to_model`; no entity when unknown (E); dirty spans; regex-first subject_role | `turn_router.py` schema, `subject_role.py:112` |
| S2 identity resolution | model over cited rows, clamp | ✅ | not fed back to connector (A); `release_state` never grounded | `open_world_identity_resolution.py`, `workload_grounding.py:104` |
| S3 acquisition ladder T0–T6 | cache → enrolled → **structured store** → publisher page (auto) → buyer link → upload → RFQ | 🟡 | T2 structured store (Steam) absent from ladder; T3 auto-fetch fires only when the publisher origin is in the candidate set (1/8); proposer queries unused | `shopping_case_open_world_research.py:82,:393` |
| S4 extraction with quote_span | model proposal + deterministic critic | 🟡 | model extraction 15/17 timeouts → regex fallback (`provider_neutral_deterministic_heuristic_fallback` on all 9 Agisoft claims) | `model_requirement_extractor.py:49`, `official_workload_research.py:394`, `llm_provider.py:335` |
| S5 feasibility / form-factor hedge | two shelves when form factor unstated | ❌ for buyer | `architecture_alternatives` computed, never rendered; F contradicts itself | `infrastructure_alternative_projection.py:143`, frontend (no refs) |
| S6 shortfall → supplier leg | auto-project when fit fails | 🟡 | endpoint exists; reachable only after manual acceptance | `shopping_cases.py:1236`, `fulfillment_cases.py:780` |
| S7 grounded narration | one composer over the terminal outcome | ❌ | three views disagree; stale templates; generic candidate-count text | `chat.py:4269-4279`, `core.py:1757` |
| S8 trace + FinOps | tokens/cost per turn, ROI | ❌ | no token columns; latency only | `agent_run_event` schema |

FIX status: FIX-0 (terminal contract) ❌ regressed by rebinding · FIX-1 (`known_to_model`) ❌ · FIX-2 (identity) ✅ · FIX-3 (ladder) 🟡 · FIX-4 (extraction) 🟡 built, dead · FIX-5 (hedge) 🟡 server-only · FIX-6 (shortfall) 🟡 · FIX-7 (narration) ❌ · FIX-8 (FinOps) ❌.

---

## 6. Updated roadmap (ordered by buyer impact ÷ effort; each item names its proof)

### Tier 1 — wiring, < 1 day each, flips the live scenarios

**R1. One evidence ledger into the terminal contract** (fixes C, B, H; FIX-0)
`chat.py:5093-5099`: include `server_research_result.research` (claims, provisional_claims, claim_compilation_receipts, `official_origin_auto_fetch`) and `official_origin_auto_fetch.claims` in `TurnCommit.research`; populate `RequirementCommit.accepted/unresolved` from them (`chat.py:5003-5013` currently reads only pasted-text claims); stop overwriting `srr.research_outcome` with a poorer object (`:5124`, `:5210`) — assert equality instead.
*Proof:* C shows "Held 9", H-T2 shows "Accepted 3 · Held 8"; add a contract test that `research_outcome.parsed_claim_count >= len(srr.research.claims)+len(provisional)`.

**R2. Structured-store tier after identity, with the canonical title** (fixes A; answers E once R4 lands; FIX-3/T2)
In `shopping_case_open_world_research.py` after `resolve_open_world_identity`: call `default_registry().resolve_with_trace(kind, identity.canonical_title, allow_live=…)` and, if resolved, compile via `compile_workload_evidence_requirements` (already shared) → accepted claims with `source=steam`, `release_date` → `release_state`. Also strip the router's leading prepositions is **not** the fix — pass the canonical title.
*Proof:* A-T2 returns min 16 GB / GTX 1060 / 130 GB, release 2025-11-14, and answers "is 3000 ok?".

**R3. Surface what exists** (fixes C/H visibility, F hedge; FIX-5 UI)
`chat.py` after server research: set `out["buyer_requirement_claims"]` = held+accepted claims with `buyer_requirement_proposal` so the existing review card (`App.tsx:2649/2694`) renders on the chat path. Render `architecture_alternatives` as two shelves ("Mobile workstation" / "Fixed workstation") with `catalog_relationship` badges when `selected_class` is null.
*Proof:* F screenshot shows two shelves; C shows a claims card with Accept/Reject.

**R4. `known_to_model` in the router schema** (fixes E; FIX-1)
Add `subject_candidate: {span, kind, known_to_model: bool, confidence}` to `recommend-router-v2`; when `known_to_model=false` or no entity but an unrecognised capitalised/rare token exists, open a case and run S2 identity on the literal span ("tarae"). Deterministic clamp = the span must be a substring of the query (already `validate_entity_frame`). No alias table.
*Proof:* E → identity "TARAE: The Unbound", release "To be announced", narration "not released yet; nearest equivalent Diablo-like ARPG requirements…", no office-laptop shelf.

### Tier 2 — capacity, 1–2 days

**R5. Router deadline derived like the proposer's** — `turn_router.py:65` ← `observed_model_latency_ms("recommend-router-v2") × 1.25` clamped [8, 20] s; keep the model warm (`keep_alive` on the prewarm, not only `ROUTER_PREWARM_REQUIRED`). *Proof:* timeout rate < 3 % over 100 turns.

**R6. Extraction that fits the model** — section-select before the model (`model_requirement_extractor.py:49`): pass only the requirements block (heading-anchored, ≤ 1,500 tokens) instead of `text[:14000]`; set `OLLAMA_NUM_CTX=8192` in the recording env; derive the deadline from the ledger. *Proof:* `official-page-requirement-extraction` completes ≥ 80 %, extractor label `model_proposal_deterministic_critic` on Agisoft.

**R7. Consume the proposer** — raise the bounded wait to the proposer's p90 (6.3 s) *or* run discovery with deterministic queries and the model queries in parallel, merging candidates; keep the publisher-domain hypothesis as a ranking prior so `official_origin_auto_fetch_eligible` sees the publisher row. *Proof:* auto-fetch fires for ≥ 50 % of software titles with a public requirements page.

### Tier 3 — narration and commerce, 2–3 days

**R8. One narrator over the terminal outcome** (FIX-7) — compose `assistant_message` **after** `terminal_outcome` from a single template set keyed by `(recommendation_status, research_status, requirement_completeness, release_state, budget_verdict)`; model narration (≤ 2 lines, grounded on that object) optional and clamped; delete the `publisher_resolution_required` count template (`chat.py:4269-4279`) and re-run `set_message` when products are cleared (`core.py:1757`). *Proof:* B no longer says "cleared gaming"; F cannot say "these all" with 0 products; A answers the budget question.

**R9. Auto-project the shortfall leg** (FIX-6) — when accepted/held requirements exist and fit yields 0 products, project `off_catalog` (identity, claims, sources, budget gap, nearest alternative) on the chat turn, human-only send unchanged. *Proof:* C ends with a "Request supplier sourcing (human review)" affordance.

**R10. `release_state` grounded** — allow the identity resolver to cite a date/keyword span from snippets ("confirmed for 2027", "To be announced", Steam `release_date`) and map deterministically to `{released, early_access, announced, unreleased, unknown}`. *Proof:* G = announced/2027, E = unreleased/TBA, A = released 2025-11-14.

### Tier 4 — FinOps and governance

**R11. Token/cost ledger** (FIX-8) — persist Ollama `prompt_eval_count`/`eval_count` per `agent_run_event`; per-turn and per-tenant rollups; Decision Trace "Cost" tab; abuse guard = tokens/turn ceiling per uid. **R12.** Human sign-off of the 9 pending sources (one JSON field each; Rockwell is `config/official_workload_sources.json:136`). **R13.** Replace the instructive e2e battery with A–H non-instructive prompts and answer-shape assertions (products/claims/release_state/narration invariants), gated on the same ledger thresholds.

---

## 7. What to do with the architecture

Keep the doctrine (model proposes over an unbounded space → closed-vocab clamp → deterministic validation) — the identity resolver proves it works on a 14B. Change three structural things:

1. **Invert the order to identity-first.** S1 (router) must only *name a span* and say whether it knows it; S2 resolves; S3 acquires (cache → enrolled → Steam/structured → publisher auto-fetch → buyer link → upload → RFQ) **with the canonical title**. Today the connector runs first with the raw span and the ladder never revisits it.
2. **One evidence ledger.** Collapse the three registries behind one `WorkloadEvidence` list per case revision (source_id, tier, claims with quote spans, acceptance status, ownership status). `build_research_outcome`, `workload_authorization`, the claims card, the shortfall projection and the narrator read only that list. This is R1 + a thin adapter for the connector and enrolled paths.
3. **Narrate last.** The assistant message is a projection of `terminal_outcome`, never composed mid-pipeline.

Small-model thesis (BYO ≤ 8B): every model call is already bounded (≤ 8 rows, ≤ 320/180/520 tokens); the fixes above shrink prompts further (extraction sections, router span-only). With R5/R6 the p90 per call stays ≤ 6 s on the 14B, which leaves headroom for a 7–8B at the same deadlines. Nothing in Tier 1–3 adds regex or aliases.

---

## 8. Decisions for the owner

1. **Rockwell sign-off:** flip `independent_review.status` at `config/official_workload_sources.json:136` (and the 8 other `pending_independent_human_review` sources) — human-only field, unblocks B/H immediately.
2. **Latency budget:** research is awaited inside the chat turn (`AUTOMATIC_RESEARCH_TIMEOUT_SEC=45`); C took 40.5 s. Either accept a two-phase answer (identity + "researching…", then claims) or cap the in-turn budget at ~15 s and stream the rest.
3. **Auto-fetch reach vs. safety:** current eligibility (publisher row must be in the candidate set, ownership ≥ 0.75) fired 1/8. Options: R7 (publisher-domain prior) keeps the same policy; alternatively allow a *buyer-pasted* page classified `official_publisher` to be fetched under the same ownership test (D).

---

## 9. What GPT-5.6's verification did and did not prove

- Proved: governance invariants, resolver correctness on cited rows, policy gates, the endpoint contracts, unit coverage (42 backend / 18 identity-outcome).
- Did not prove: that a buyer gets an answer. The battery's prompts pre-name the publisher and paste URLs; its assertions check panel presence. None of the five acceptance examples in Section 0 is in it. The "live status" numbers are correct for the proposer and identity roles and omit the router (17.5 % timeouts) and extraction (88 % timeouts) roles, which are the two that decide the answer.

Artifacts: `scratchpad/probe/out2/*.json|png` (A–H network + DOM + screenshots), `latency_profile.py` output above.
