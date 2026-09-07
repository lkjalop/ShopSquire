# ShopSquire External Search — Independent Re-verification #2 (2026-09-03)

**Scope.** Re-run of my own deep dive after GPT-5.6 delivered rounds #2–#4
(novel-title certificate PRAGMATA / MIO / Dawnwalker; priority scheduler;
continuity regressions; idempotency + single-flight + polling; rotating
official-feed certificate; cited-span extraction — commits `f2244313`,
`7f0514a6`, `d3ae5534`, `be3382b9`; worktree dirty on top of HEAD `87987967`).
Everything below was measured on the live stack
(`.artifacts/p0-transition-scheduler-live-20260903/`, profile `demo_v2`,
`RECOMMEND_CORE_MODE=primary`, qwen3:14b for every role, SearXNG :8888) with
a fresh `uid` per scenario, then cross-checked in code and in the durable model
ledger (`agent_run_event`). Nothing in the repo was modified; nothing committed.

Predecessor: `docs/SHOPSQUIRE_EXTERNAL_SEARCH_DELTA_VERIFICATION_2026-09-02.md`
(R1–R13). Companion gap analysis:
`docs/SHOPSQUIRE_EXTERNAL_SEARCH_INTELLIGENCE_GAP_2026-09-02.md` (S0–S8).

---

## 0. One-paragraph verdict

GPT-5.6's four rounds fixed the **governance** of the research path (the ledger
now reaches the terminal contract, the router deadline is derived instead of a
12 s cliff, the priority scheduler serialises the single-GPU box honestly,
idempotent polling stops duplicate turns, release_state is grounded) — 4 of the
13 roadmap items are ✅ in code *and* live. But the **buyer outcome is still
❌**: across 10 non-instructive scenarios (A–J, 14 turns) every turn that
triggered research returned **0 products**, and three turns narrated something
false (C denies its own 9 held claims; G confidently resolves "bloodwalker the
new witcher" to *The Witcher 3 REDkit* — a modding toolkit; H-T1 says "No
qualified in-catalog match under $6,000" when the real event was a truncated
router output). The re-verification also found **four new harness defects that
were invisible to GPT-5.6's certificates** because those certificates run with
`USE_MOCK_LLM`/fixtures and never touch a socket:

| # | New finding | Measured impact |
|---|---|---|
| N1 | `OLLAMA_URL=http://localhost:11434` → Windows resolves `localhost` to `::1` first, Ollama listens on `127.0.0.1` only, the IPv6 connect is refused after ~2.0 s | **~2 s tax on every Ollama HTTP call**; identical governed router call 4.4–4.9 s vs 0.18–0.23 s; a research turn pays it 4–6× (8–12 s) |
| N2 | `ROUTER_NUM_PREDICT` defaults to **320** tokens and nobody checks Ollama's `done_reason` | Any message that makes the router emit `semantic_proposal` (every novel workload) needs ~400 tokens → **truncated JSON → parse `None` → `fallback:model_unavailable`** → narrated as a catalog fact |
| N3 | The 300–1000 ms *entity-repair* calls are ledgered under the router's own `prompt_id`, and the derived deadline is the p90 of the last 32 runs | Repairs (and any fast call) **pull the deadline down to the 12 s floor**; a 404-token turn (~10 s decode) + N1 tax (4 s) then **times out** — H-T1 did exactly this |
| N4 | The new `commercial_terms` layer reads "$3000 laptop" as `quantity=3000, unit="laptop"` | Single-item turn I asks *"Is that budget per item, or the total for all 3000?"* (`gates.py:107`) — a regression introduced by the delta |

The intelligence the user asked for (tarae → specs + release state + budget
feasibility; digital-twin → desktop **and** mobile workstation shelves with
honest narration) is still not delivered, and the reason is unchanged from
2026-09-02: the expensive pieces exist and work in isolation; the harness
drops their output on the floor at four seams (ordering, output cap, transport,
projection).

---

## 1. Method

* **Code**: read every file GPT-5.6 named in rounds #2–#4 plus the seams they
  depend on (list in §7).
* **Live browser/API probe**: `scratchpad/probe/run3.cjs` (Playwright against
  `:5173`, fresh `uid` per scenario, streams then polls `POST
  /api/v1/chat/query` with the same `Idempotency-Key` exactly like
  `App.tsx:2226-2416`), plus direct `requests` replays of I and H-T1 to capture
  `router_outcome`, `model_invocation`, `terminal_outcome.execution_evidence`.
* **Offline router replay**: `scratchpad/probe/router_replay.py` builds the
  *real* router prompt through `route_turn_outcome(...)` against the live
  sqlite (read-only) and sends it to Ollama over `127.0.0.1` with the exact
  options the app uses (`router_model_call.py:47-63`) so prefill / decode /
  output-token counts are attributable.
* **Ledger**: `agent_run_event` in the live sqlite (accepted → terminal wall
  time per `prompt_id`).
* **Transport**: `cProfile` of a governed router call; `socket.getaddrinfo` +
  timed connects to `localhost` vs `127.0.0.1`.

Scenario set (non-instructive by design — no "run"/"play" verbs where a buyer
would not naturally use them):

| ID | Turns | Purpose |
|---|---|---|
| A | "gaming laptop under 3000" → "what about for where winds meet is 3000 ok?" | continuity + released Steam title |
| B | "gaming laptop under 3000" → "actually I need it for Rockwell Emulate3D" | continuity + enrolled software source |
| C | "workstation for agisoft metashape under 4000" | open-web software with official page |
| D | pasted Cupix URL | URL intake |
| E | "tarae recommended specs, is 3500 enough" | unreleased/novel game (user's example) |
| F | "computer for digital twin simulations" | architecture alternatives (user's example) |
| G | "can my kid play bloodwalker the new witcher on a 2500 laptop" | colloquial mis-title (user's example) |
| H | "workstation for Rockwell Emulate3D under AUD 6000" → "also Factory IO" | enrolled + additive workload |
| I | "will a $3000 laptop run where winds meet?" | single-turn feasibility |
| J | "is 3000 enough for pragmata?" | GPT-5.6's own certified novel title |

---

## 2. Live results (A–J)

`products` = shelf count returned to the buyer; `claims` = parsed / held /
accepted in `terminal_outcome.research_outcome`.

| ID | products | claims | Narration / terminal | Verdict |
|---|---|---|---|---|
| A-T1 | 3 | — | gaming shelf, budget honoured | ✅ |
| A-T2 | **0** | — | entity repair **not attempted** (regex gate: "what about for where winds meet is 3000 ok?" has no run/play relation) → no identity → no Steam → continuation with 0 products | ❌ (the model *would* have answered — see N6) |
| B-T1 | 3 | — | ok | ✅ |
| B-T2 | **0** | 8 / 8 / 0 | Rockwell enrolled source fetched; **8 held**, `independent_policy_human_signoff_pending`; narration: "widen your budget" (non-sequitur — budget was never the blocker) | 🟡 ledger ✅ / narration ❌ |
| C | **0** | 9 / 9 / 0 | Agisoft official page auto-fetched, 9 claims via **regex fallback** (extractor timed out at 12 s, `late_result_quarantined`); narration **denies** research ("I could not verify requirements") while the trace shows "claims 0 accepted, 9 held" | 🟡 ledger ✅ / narration ❌ |
| D | **0** | — | URL resolved via enrolled_domain, held | 🟡 |
| E | **10** | — | "tarae" not emitted as an entity; 10 general laptops; "ample for general use" — **total miss** (unchanged since 09-02) | ❌ |
| F | **0** | — | "These all handle engineering simulation, starting at $3,499" + Found 0; `architecture_alternatives` computed server-side, **0 references in `frontend/src`** | ❌ |
| G | **0** | 2 / 2 / 2 | identity → **"The Witcher 3"** → Steam → **"The Witcher 3 REDkit"** (modding tool, released 21 May 2024) narrated as *verified evidence* | ❌ wrong identity, confidently narrated |
| H-T1 | **0** | 8 / 8 / 0 | Rockwell 8 held; on direct replay the router hit `model_execution_timeout` at `deadline_ms 12000` (N2+N3), `execution_mode v2_unavailable`; narration "No qualified in-catalog match under $6,000" | ❌ misattributed failure |
| H-T2 | **0** | — | Factory IO ADD_WORKLOAD → `no_enrolled_provider_result`; `desired_outcome` polluted with the clarification text | 🟡 |
| I | **0** | — | `commercial_terms.quantity=3000` → "Is that budget per item, or the total for all 3000?" | ❌ regression (N4) |
| J | **0** | — | identity resolver rejected; `coverage_abstention_shadow` flagged concept "pragmata" (material, `research_then_clarify`) but nobody hands it to Steam — while `get_game_requirements("pragmata", allow_live=True)` returns min 16 GB / GTX 1660 / 40 GB, released 2026-04-16, in **1.15 s** | ❌ |

**Products across all research turns: 0 / 11.** The only turns with shelves
were the two plain "gaming laptop" openers and the mis-routed tarae turn.

---

## 3. Roadmap items R1–R13 — status after rounds #2–#4

Legend: ✅ done in code and observed live · 🟡 partial · ❌ not done.

| R | Item | Status | Evidence |
|---|---|---|---|
| R1 | Research ledger → `TurnCommit` / terminal contract | ✅ | B/C/H show Parsed 8–9 · Held 8–9; decision trace "claims 0 accepted, 8 held". Residual: the turn-2 scheduler receipt is **overwritten** by the repair call (shows 4 s, `deadline_ms 4000`) |
| R2 | Steam **after** identity with canonical title | ✅ code / 🟡 live | `shopping_case_open_world_research.py:398` retries enrolled after cited resolution; `workload_grounding.py:214-293 resolve_canonical_workload_identity` only fires when identity `status == resolved` → J (`canonical_identity_not_resolved`) and A-T2 (no entity) never reach Steam; G reaches it with the **wrong** title |
| R3 | Project claims to top-level `buyer_requirement_claims` + render `architecture_alternatives` shelves | ❌ | top-level `buyer_requirement_claims == []` in all 10 scenarios (proposal stays nested in `server_research_result`); `grep -r architecture_alternatives frontend/src` → 0 |
| R4 | Entity coverage / `known_to_model` | 🟡 | `_repair_missing_workload_entity` exists (`turn_router.py:1793-1840`) but (a) gated by a regex relation (`:2005-2050`, `has_explicit_workload_relation`) so A-T2 is never repaired; (b) its prompt forbids inference ("Do not infer, normalize, correct, or complete a title") so E/I/J return `null`; (c) certificate prompts contain play/run verbs by construction; no `known_to_model` field anywhere |
| R5 | Router deadline derived from measured p90 | ✅ but fragile | `turn_router.py:58-96`; 2 timeouts / 110 (1.8 %) vs 17.5 % on 09-02. Fragile because of N3 (series pollution) and N1 (the tax inflates the p90 it derives from) |
| R6 | Section-select extraction + `OLLAMA_NUM_CTX` | 🟡 | cited-span extractor shipped, still **times out at 12 s live** (n=1, `late_result_quarantined`) → C's 9 claims are regex fallback; `OLLAMA_NUM_CTX` still unset |
| R7 | Consume proposer output | 🟡 | 600 ms bounded wait, receipt-only (`fallback_used: true`) — n=27 all completed at p50 4.9 s, i.e. **never in time** |
| R8 | Narrate LAST from terminal outcome | 🟡 | C denies held claims; B-T2 "widen budget"; G narrates wrong title as verified; H-T1 narrates a truncation as a catalog fact; F/G show the "Verified evidence" label with 0 accepted / wrong identity |
| R9 | Chat-path shortfall → `off_catalog` | ❌ | `off_catalog` key present but never populated on chat research turns |
| R10 | `release_state` grounding sentence | ✅ | "It is released (…)" / TBA sentence emitted from Steam `release_date` |
| R11 | Token / queue ledger (FinOps) | ❌ | `agent_run_event.details_json` carries only `{dlp_hits, output_hash, late_result_quarantined}`; `prompt_tokens/output_tokens/transport_overhead_ms` live in-memory only (`router_model_call.py`) |
| R12 | Human sign-off of enrolled sources | ❌ | Rockwell (and 7 others) still `independent_policy_human_signoff_pending` — every enrolled-source turn is *held* by design until a human signs |
| R13 | Non-instructive e2e certificate | 🟡 | rotating official-feed certificate exists; prompts are verb-instructive; runs under mock LLM |

Score: **4 ✅ · 6 🟡 · 3 ❌** — and the three ❌ are exactly the items that
decide whether a buyer sees a shelf.

---

## 4. New findings (N1–N8) with measurements

### N1 — Loopback IPv6 tax on every Ollama call (root cause of most "latency")

* `.env:80` `OLLAMA_URL=http://localhost:11434` (user-owned, **not modified**).
  `local_model_roles.py:184` `base_url = os.getenv("OLLAMA_URL",
  "http://127.0.0.1:11434")`; `ollama_artifact_verification.py:39-100`
  `_default_fetch = requests.get(url, timeout)` with `timeout_s = min(max(t,
  0.1), 2.0)`; `llm_provider.py:21/345` httpx.
* Windows resolves `localhost` → `::1` first; Ollama binds `127.0.0.1:11434`
  only; the IPv6 connect is refused after **~2042 ms**, then IPv4 succeeds.
  `cProfile`: `{method 'connect' of '_socket.socket'}` 2 calls **2.015 s**.
* Same governed router call, cached prompt:
  `http://localhost:11434` walls **[4947, 4557, 4439, 4435] ms** vs
  `http://127.0.0.1:11434` **[232, 182, 202, 234] ms**.
* Direct live probe of I: router wall 5156 ms = model 907 ms +
  `transport_overhead_ms` **4071** (= verify GET 2 s + generate POST 2 s).
* A research turn makes 4–6 Ollama calls (router, repair, proposer, identity,
  extractor, artifact verify) → **8–12 s of pure connect tax per turn**, which
  the derived deadline (R5) silently absorbs and which the extractor (12 s)
  cannot absorb.
* **Fix (ops, 1 line, user-owned):** `OLLAMA_URL=http://127.0.0.1:11434` in
  `.env` (or make Ollama listen on `[::1]` via `OLLAMA_HOST`). **Fix (code,
  hardening):** resolve the configured host once, prefer the IPv4 loopback
  literal, and reuse a pooled keep-alive `Session`/`httpx.Client` across
  verify + generate so a connect happens once per process, not per call.

### N2 — Router output cap truncates every novel-workload turn

* `router_model_call.py:47` `max_tokens = int(os.getenv("ROUTER_NUM_PREDICT",
  "320"))`; `:63` `options.num_predict`. Not configured anywhere in the repo,
  `.env`, or the recording env → **320**.
* Offline replay of the *real* prompt for H-T1 ("workstation for Rockwell
  Emulate3D under AUD 6000", 2,376 prompt tokens):
  `num_predict=320` → `done_reason: "length"`, 320 tokens, 7.7 s decode,
  `parse_router_payload(...)` → **`None`**.
  `num_predict=1024` → `done_reason: "stop"`, **404 tokens**, 9.7 s, parses OK
  (`lane PROCUREMENT`, `workload_entities [Rockwell Emulate3D]`, full
  `semantic_proposal` with `material_unknowns`).
  Plain "gaming laptop under 3000" → 109 tokens, 2.7 s; "digital twin" → 150
  tokens, 3.6 s (and lane PROCUREMENT / handle `el-6-2` *Computer Servers* —
  not a workstation node).
* Nobody reads `done_reason` (grep across `src/app/services`: zero hits) so a
  truncated body is indistinguishable from a model outage:
  `router_outcome.source = "fallback:model_unavailable"`, `execution_mode
  v2_unavailable`, `workload_authorization.reason model_execution_unavailable`
  → narrated as *"No qualified in-catalog match is established under $6,000"*.
* Why it is so expensive: the schema makes the model pretty-print (≈40 % of the
  tokens are whitespace) and echo the whole buyer message twice
  (`semantic_proposal.concepts.text` and `.query_span`). At ~41 tok/s on this
  GPU that is 400 tokens ≈ 10 s before any transport tax.
* **Fix:** (1) treat `done_reason == "length"` as a typed failure
  `router_output_truncated` (never "model_unavailable", never a catalog
  sentence); (2) raise the cap to ≥ 768 **and** ask for single-line JSON; (3)
  stop echoing the message in `semantic_proposal` (emit spans as offsets or
  omit `text`); (4) longer term, move `semantic_proposal` to a second bounded
  call that only runs when the first call reports an unresolved concept.

### N3 — The derived deadline is polluted by its own repair calls

* `model_runtime_profile.py:18-60`: p90 over the **last 32 runs** of
  `prompt_id = "recommend-router-v2"`. `turn_router.py:78-81`:
  `inference_s = min(30, max(12, p90 × 1.75))`.
* `_repair_missing_workload_entity` (`turn_router.py:1819`) calls the same
  `fn` → `execute_router_model` → **same `prompt_id`**, at 300–1000 ms.
  Every repair (and every warm fixture-free probe) drags the p90 toward the 12 s
  floor. Observed: deadline **19042 ms** during the morning probe (p90 10.9 s)
  → **12000 ms** by the H-T1 replay (recent p90 < 6.9 s). A 404-token turn
  (~10 s) + N1 tax (~4 s) > 12 s → `model_execution_timeout`.
* **Fix:** ledger repairs under their own `prompt_id`
  (`recommend-router-entity-repair-v1`), and derive the deadline from the p90
  of *completed full-contract* runs only (the profile already returns
  `last_success_at_ms`; filter on the primary role / output-token band).

### N4 — `commercial_terms` regression: "$3000 laptop" becomes quantity 3000

* `envelope.py` (delta) `CommercialTerms`; projected by
  `chat_recommendation_dispatch.py:66-77` (`commercial_terms`,
  `requested_quantity`, `budget_scope`); consumed by
  `gates.py:107-121 material_pre_retrieval_clarify(quantity, budget_known,
  budget_scope)`.
* Live I: `commercial_terms = {quantity: 3000, quantity_unit: "laptop",
  budget_scope: "unknown"}` → clarification "Is that budget per item, or the
  total for all 3000?" on a single-item question. The model's own
  `quantity` is ignored on a fresh turn (`turn_router.py:2440-2510`) but the
  deterministic term parser is not.
* **Fix:** a number that is also the budget's `source_span` (or is prefixed by
  a currency symbol) can never be a quantity; require the model-proposed
  quantity to agree before `material_pre_retrieval_clarify` may fire.

### N5 — Identity mis-resolution is accepted and narrated as verified (G)

* Chain: router entity "bloodwalker the new witcher" → identity resolver
  (`open-world-identity-resolution`) proposes canonical title **"The Witcher
  3"** with a cited row; clamp `official_origin_auto_fetch_eligible`
  (`shopping_case_open_world_research.py:160-190`) checks title-token
  containment against the *cited page title*, not against the buyer's phrase
  → passes.
* Steam: `_live_lookup` (`connectors/steam_requirements.py:428-470`) keeps
  every storesearch item where `_title_matches` (`:307-315`, **substring**)
  holds, then **sorts by shortest name** (`:446`) → "The Witcher 3 REDkit"
  (4 words) beats "The Witcher 3: Wild Hunt" (5 words). The REDkit modding
  toolkit's `pc_requirements` become the buyer's "verified evidence".
* The buyer meant *The Blood of Dawnwalker* (Rebel Wolves, ex-Witcher devs) —
  which Steam returns for "blood of dawnwalker" with release "2 set 2026"
  (an Italian-locale string; `min` requirements None). GPT-5.6's certificate
  covers "Dawnwalker" typed correctly; the colloquial phrasing the user gave is
  the case that fails.
* **Fix:** (1) identity acceptance must require **buyer-phrase overlap or a
  model-stated alias justification** (`known_to_model`), and a
  low-confidence identity must become a *clarifying question* ("Did you mean
  The Blood of Dawnwalker?") not a fetch; (2) Steam matcher: prefer the item
  whose normalised name **equals** the request, and reject items whose name
  extends the request with a tool/DLC marker (REDkit, Soundtrack, SDK, Demo)
  unless requested; (3) never label a held/rejected outcome "Verified
  evidence" in `DecisionTrace.tsx`.

### N6 — Repair is regex-gated exactly where the model would succeed

* `turn_router.py:2005-2050`: repair only runs when `role_hint ∈
  {RUN_SUBJECT_ON_PRODUCT, COMPATIBILITY_CHECK}` **or**
  `subject_role.has_explicit_workload_relation()` (regex `_RUN`/`_COMPAT`).
* A-T2 "what about for where winds meet is 3000 ok?" has neither → repair
  skipped. Calling the repair function directly on that message returns
  `"where winds meet"` — i.e. the model is right and the gate is wrong.
* The same repair returns `null` for I/J/E because its prompt forbids
  inference and the titles are unknown/novel — which is the correct behaviour
  for the *repair* role, and the reason a separate `known_to_model` /
  coverage-abstention hand-off is needed (N7).
* **Fix:** drop the regex gate; run the repair whenever the router emitted no
  entity **and** the coverage-abstention shadow (already computed) marks a
  material unresolved concept.

### N7 — Coverage abstention already finds the concept; nothing consumes it

* J: `coverage_abstention_shadow` = concept "pragmata", status unresolved,
  material, `proposed_action: research_then_clarify`. That is precisely the
  input an enrolled structured provider needs — and
  `get_game_requirements("pragmata", allow_live=True)` answers in 1.15 s.
* Today the order is proposer → discovery (raw query) → identity resolver →
  Steam (only if resolved). For a concept the open web can't name, the
  structured provider should be tried **first** (it is cheaper, allow-listed,
  and returns identity + release state in one call).
* **Fix:** identity ladder = coverage-abstention concept → enrolled structured
  providers (Steam / Rockwell manifest) → open-web identity resolver → clarify.
  One ledger entry regardless of which rung answered.

### N8 — Failure narration still names the wrong culprit

Three distinct harness failures were narrated as buyer-facing facts this
session: truncation → "no qualified in-catalog match under $6,000" (H-T1);
extractor timeout → "I could not verify requirements" while 9 claims are held
(C); wrong identity → "Verified evidence · The Witcher 3 REDkit" (G). The
narration composer still has a path from `execution_mode v2_unavailable` to a
catalog-shaped sentence. **Fix:** the composer must switch on
`terminal_outcome.execution_evidence.failure_code` first (typed:
`router_output_truncated`, `model_execution_timeout`,
`independent_policy_human_signoff_pending`, `identity_low_confidence`) and
only then on catalog state; a held claim count > 0 must always be spoken.

---

## 5. Ledger (live sqlite, 2026-09-03 03:53 → 12:10)

| prompt_id | n | p50 ms | p90 ms | max | completed | timeout |
|---|---|---|---|---|---|---|
| recommend-router-v2 | 110 | 2572* | 10683 | 11931 | 108 | 2 |
| open-world-query-proposal | 27 | 4943 | 5241 | 5604 | 27 | 0 |
| open-world-identity-resolution | 39 | 3634 | 4152 | 4851 | 39 | 0 |
| official-page-requirement-extraction | 1 | 11998 | — | 11998 | 0 | **1** |

\* p50 is dragged down by repair calls and by my own eight `127.0.0.1`
measurement calls — which is N3 demonstrated on the real ledger.

No token, queue, or transport columns exist (R11 ❌); `details_json` only
carries `dlp_hits / output_hash / late_result_quarantined`.

---

## 6. Current architecture (as measured, not as designed)

```
 Buyer (Vite :5173)
   │  POST /api/v1/chat/stream ── in_progress after ~12 s ──► poll /chat/query
   │  same Idempotency-Key (App.tsx:2226-2416); single-flight chat.py:1006-1060  OK
   ▼
 chat.py ─► chat_recommendation_dispatch ─► recommendation_facade ─► recommendation_core
                                                                        │
   ┌────────────────────────────────────────────────────────────────────┤
   │ TURN ROUTER  turn_router.py                                        │
   │  build prompt (~2.4k tok, cached prefix)                           │
   │  ─► execute_router_model  num_predict=320   N2  no done_reason chk │
   │  ─► deadline = p90(last 32 of SAME prompt_id)×1.75, floor 12 s  N3 │
   │  ─► every call: verify GET (2 s cap) + generate POST               │
   │        └─ localhost→::1 refused→127.0.0.1  ≈ +2 s each   N1        │
   │  entity missing? ─ regex relation gate N6 ─► repair (same id)  N3  │
   │  commercial_terms: "$3000 laptop" → qty 3000  N4 → clarify gate    │
   └───────────────┬────────────────────────────────────────────────────┘
                   │ TurnDecision + coverage_abstention_shadow (computed, unread  N7)
                   ▼
   ┌── OPEN-WORLD RESEARCH  shopping_case_open_world_research.py ───────┐
   │ proposer (600 ms wait, receipt-only  R7)                           │
   │ discovery (SearXNG, raw query)                                     │
   │ identity resolver (model + cited clamp) ─ accepts wrong title  N5  │
   │   └─ resolved? ─► Steam _live_lookup (substring, shortest-name N5) │
   │      not resolved ─► canonical_identity_not_resolved → STOP (J)    │
   │ auto-fetch official page ─► extractor (12 s, times out  R6)        │
   │                              └─ regex fallback claims              │
   │ claims → HELD (human sign-off pending  R12) / accepted             │
   └───────────────┬────────────────────────────────────────────────────┘
                   ▼
   TERMINAL CONTRACT  terminal_outcome.research_outcome   R1 OK (parsed/held/accepted)
        │ top-level buyer_requirement_claims = []                    R3
        │ architecture_alternatives computed, never rendered         R3
        │ off_catalog never populated                                R9
        ▼
   NARRATION  (answer_quality / composer)  ─ speaks a catalog sentence on
        v2_unavailable / truncation / timeout                        N8 R8
        ▼
   DecisionTrace.tsx  "Verified evidence" label on held / wrong identity  N5
   ProductShelvesPanel  0 products on every research turn
```

---

## 7. Files read / verified this pass

`src/app/services/recommendation_core/{turn_router.py, router_model_call.py,
router_prompt.py, router_parser.py, envelope.py, gates.py,
workload_grounding.py, turn_outcome.py}`,
`src/app/services/{local_model_roles.py, model_execution_gateway.py,
ollama_artifact_verification.py, model_runtime_profile.py,
agent_run_event_store.py, chat_recommendation_dispatch.py,
shopping_case_open_world_research.py, llm_provider.py}`,
`src/app/services/connectors/steam_requirements.py`, `src/app/routers/chat.py`,
`frontend/src/{App.tsx, components/DecisionTrace.tsx,
components/ProductShelvesPanel.tsx}`, `.env` (read only),
`.artifacts/p0-transition-scheduler-live-20260903/recording-env.ps1`.

---

## 8. What is done, what is left, and why

### Done (keep)
* Governance spine: ledgered model execution with DLP sanitise, late-result
  quarantine, priority scheduler receipts, idempotent polling, human-only
  supplier send, allow-listed egress, cited-clamp identity, release_state.
* Research ledger reaches the terminal contract (R1) — the 09-02 headline bug
  is fixed.
* Router deadline is measured, not a cliff (R5) — with the two caveats above.

### Left — in the order that removes the most buyer-visible failure per hour

| # | Item | Why this order | Owner |
|---|---|---|---|
| 0 | **N1** `OLLAMA_URL=http://127.0.0.1:11434` (ops) + pooled IPv4 client (code) | Removes 8–12 s per research turn for free; makes every deadline/timeout number below trustworthy. I must not edit `.env`; the user sets it | user (ops) / code |
| 1 | **N2** `done_reason` → `router_output_truncated`; cap ≥ 768; single-line JSON; stop echoing the message in `semantic_proposal` | Every novel-workload turn currently dies here before any research starts | code |
| 2 | **N3** own `prompt_id` for repairs; deadline from full-contract runs | Otherwise fix #1 still times out after the first few repairs | code |
| 3 | **N4** quantity ≠ budget span; model quantity must agree | Regression on the simplest single-item question | code |
| 4 | **N7 + N6 + R2** identity ladder: abstention concept → enrolled structured (Steam) → open-web resolver → clarify; drop regex gate; `known_to_model` in schema | Makes tarae / pragmata / where-winds-meet answer from a 1 s allow-listed call instead of a 20 s open-web chain that stops at "not resolved" | code |
| 5 | **N5** identity acceptance needs buyer-phrase overlap or alias justification; Steam exact-name preference + tool/DLC rejection; low confidence → question | Stops confident wrong answers (worse than no answer) | code |
| 6 | **R3** project held/accepted claims to top-level `buyer_requirement_claims`; render `architecture_alternatives` shelves (desktop + mobile workstation) | This is the user's digital-twin acceptance case; the server already computes both | code (frontend + dispatch) |
| 7 | **R12** sign off the 8 enrolled sources (or demo policy: held ⇒ *hedged shelf* "assuming these requirements…") | Until then every enrolled-source turn is held by design → 0 products | user (policy) |
| 8 | **N8 / R8** narration switches on `failure_code` first; held count always spoken; drop "Verified evidence" on held/rejected | Truthfulness; cheap once 1–5 stop producing fake failures | code |
| 9 | **R9** chat-path shortfall → `off_catalog` | Honest "we don't stock this" instead of an empty shelf | code |
| 10 | **R6** `OLLAMA_NUM_CTX=8192` + extractor budget ≥ 20 s after #0 | Extractor is the only role still timing out live | ops + code |
| 11 | **R7** consume proposer (wait ≥ p90 or drop the role) | 27/27 completions all arrive after the 600 ms wait — the role is pure cost today | code / FinOps |
| 12 | **R11** tokens/queue/transport in `agent_run_event.details_json` | FinOps + DDoS budget the user asked for; the numbers already exist in-memory | code |
| 13 | **R13** non-instructive, real-model certificate (this A–J set) | Certificates that never touch a socket certified N1–N3 as green | test |

### Why the remaining gap is a *harness* gap, not a model gap
Every failing scenario has a point in the trace where the correct answer
already exists: the model emits `Rockwell Emulate3D` and a full
`material_unknowns` list (cut at token 320); the repair returns `where winds
meet` (never called); the abstention shadow names `pragmata` (never consumed);
Steam returns PRAGMATA's requirements in 1.15 s (never asked); nine Agisoft
claims are held in the ledger (narrated as absent). qwen3:14b is not the
bottleneck — the seams between its calls are. That is also why the ≤ 8B
BYO-model goal is still reachable: fix the seams, then shrink the model.
