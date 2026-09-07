# ShopSquire External Search — Re-verification #3 (2026-09-04)

**Scope.** Independent re-run after the *uncommitted* round-#5 delta that answers
my 09-03 findings N1–N8. Measured on the live stack restored after a machine
bugcheck (profile `demo_v2`, `USE_MOCK_LLM=0`, `RECOMMEND_CORE_MODE=primary`,
qwen3:14b for every role, SearXNG :8888, `ROUTER_NUM_PREDICT=768`), fresh `uid`
per scenario, polling the same `Idempotency-Key` exactly like `App.tsx:2226-2416`.

**Tree state.** HEAD `be3382b9` (2026-09-03 10:17). On top of it: **44 dirty
files, +1,337 / −136 across 39 tracked files, plus 4 new modules** — all
uncommitted. Nothing in this document was committed by me.

Predecessors: `..._2026-09-03.md` (N1–N8), `..._2026-09-02.md` (R1–R13),
`..._INTELLIGENCE_GAP_2026-09-02.md` (S0–S8), `..._REPAIR_ROADMAP_2026-08-31.md`
(R1–R11).

---

## 0. One-paragraph verdict

**The evidence spine now works end-to-end for the first time in this arc.** A
buyer can name a title the 14B has never heard of and the platform resolves it
against an enrolled structured provider, compiles *verified_official* claims with
a real source URL, projects them to the top-level contract, and narrates the
result truthfully — including refusing to judge a budget for an unreleased title.
That is a genuine capability change, not a plumbing change, and it is the thing
every prior round failed to deliver. **But the buyer still sees zero products on
every research turn**, because a second, stale authority (`semantic_resolution`)
still reports `unresolved_material_concept` for the very concept the structured
provider just resolved, and `catalog_authority` is `blocked` as a result. Round #5
fixed the acquisition of evidence; it did not reconcile the two authorities that
decide whether evidence may touch the catalog. Separately, two of the three
scenarios that fail do so for **span hygiene**, not coverage: the connector
resolves `where winds meet` in 0 ms and returns `None` for the span the router
actually emits.

---

## 1. What round #5 actually fixed (verified in code AND live)

| # | 09-03 finding | Status | Evidence |
|---|---|---|---|
| N1 | `localhost` → IPv6 tax ~2 s/call | ✅ code | New `src/app/services/ollama_endpoint.py::normalize_ollama_url` rewrites `localhost`→`127.0.0.1`; wired into `llm_provider`, `local_model_roles`, `model_transports` (pooled `Session`), `ollama_artifact_verification`. `.env:80` still says `localhost` (user-owned) but the code no longer honours it |
| N2 | `ROUTER_NUM_PREDICT=320` truncation, no `done_reason` | ✅ code+ops | Default now **768**; `RouterOutputTruncated` typed exception; `done_reason == "length"` → `failure_code: router_output_truncated`, never `model_unavailable`. `start_recording_stack.ps1` now exports `ROUTER_NUM_PREDICT=768` |
| N3 | Repairs pollute the router p90 | ✅ code | Repair now ledgered as `prompt_id="recommend-router-entity-repair-v1"` (`turn_router.py:1858`); router deadline still derives from `recommend-router-v2` only |
| N4 | `"$3000 laptop"` → quantity 3000 | ⚠️ **half** | Budget-span overlap + currency-prefix guard added. `"$3000 laptop"` → `qty=None` ✅. **`"on a 2500 laptop"` → `qty=2500 unit=laptop` ❌** (no currency symbol, no budget span to overlap) |
| N5 | Steam shortest-name → "The Witcher 3 REDkit" | ✅ live | New `select_live_store_item` prefers exact normalised name and rejects `_AUXILIARY_TITLE_MARKERS` (redkit/sdk/demo/soundtrack…). G no longer returns REDkit — **the confident wrong answer is gone** |
| N6 | Repair regex-gated | ✅ widened | Gate is now `role_hint ∈ {...} OR has_material_semantic_unknown OR identity_probe_requested` |
| N7 | Coverage abstention never consumed | ✅ **live** | New `workload_grounding.resolve_unresolved_concepts` (structured-provider-first ladder), consumed at `shopping_case_open_world_research.py:323,328`. **This is what makes PRAGMATA and TARAE work** |
| N8 | Narration names the wrong culprit | ⚠️ **inverted** | New `terminal_research_narration.py` keyed on `failure_code` — but see §3.1, it now over-claims failure |
| R3 | Claims not projected; alternatives not rendered | ✅ live | `buyer_requirement_claims` = 2 at top level on J; `ArchitectureAlternativesPanel.tsx` imported and rendered at `App.tsx:3774`; `architecture_alternatives` present on J |
| R11 | No token/queue ledger | ✅ code | `model_execution_gateway` now persists `queue_ms`, `deadline_ms`, `max_output_tokens`, `done_reason`, `prompt_tokens`, `output_tokens` into the ledger event |
| R13 | Instructive certificate under mock LLM | ⚠️ better | `live-novel-title-intelligence.spec.ts` prompts are now buyer-shaped ("Could a laptop under AUD 2,500 run PRAGMATA at 1080p?") and real-model. **But all three still contain an explicit run/play/need relation**, so they cannot catch the A-T2 phrasing that has none |

Unit tests for the delta: **88 pass** across the seven changed test files.

**Correction to my own 09-03 doc:** I wrote that Rockwell "and 7 others" were
`independent_policy_human_signoff_pending`. Wrong — of 20 sources, **19 have no
`independent_review` block at all** and exactly **one** (Rockwell) carries the
pending status. R12 is a one-field decision, not an eight-source backlog.

---

## 2. Live results (restored stack, 2026-09-04)

| ID | Prompt | ms | Products | Identity resolved | Claims | Verdict |
|---|---|---:|---:|---|---|---|
| **J** | "is 3000 enough for pragmata?" | 6,236 | **0** | ✅ PRAGMATA · CAPCOM · app 3357650 · released 16 Apr 2026 | parsed 2 / **accepted 2** · completeness **complete** | 🟡 **evidence ✅ / shelf ❌** |
| **E** | "tarae recommended specs, is 3500 enough" | 11,339 | 0 | ✅ TARAE: The Unbound · KRAFTON · app 4604540 · **unreleased / TBA** | identity_only | ✅ **honest refusal — correct answer** |
| **G** | "can my kid play bloodwalker the new witcher on a 2500 laptop" | 15,221 | 0 | ❌ none (Steam `no_authoritative_result`) | — | 🟡 no longer *wrong*, still no clarify |
| **I** | "will a $3000 laptop run where winds meet?" | 15,238 | 2 | ❌ **research never ran** (`discovery: not_attempted`) | — | ❌ generic gaming answer |
| **A-T1** | "gaming laptop under 3000" | 3,527 | 2 | n/a | — | ✅ |
| **A-T2** | "what about for where winds meet is 3000 ok?" | 11,691 | 0 | ❌ concept span = `"where winds meet is 3000 ok"` | — | ❌ dirty span |

### The headline comparison

| Scenario | 2026-09-02 | 2026-09-03 | **2026-09-04** |
|---|---|---|---|
| tarae (E) | 10 office laptops, "$3,500 is ample for general" | 10 general laptops, total miss | **"I resolved TARAE: The Unbound… release state is unreleased… I cannot judge the budget or qualify products yet."** |
| pragmata (J) | — | `canonical_identity_not_resolved`, 0 products | **identity + 2 verified_official claims + top-level projection** |
| bloodwalker (G) | identity → wrong expansion | **"The Witcher 3 REDkit" narrated as verified** | refuses, no false claim |

E is the user's own acceptance example and it is now answered correctly.

---

## 3. New findings

### 3.1 · The N8 fix is inverted — a *successful* research turn can be narrated as a model failure

`terminal_research_narration.py:39-40` returns a model-failure sentence
**unconditionally** whenever `execution_evidence.failure_code` is one of three
values, with no check of whether research concluded:

```python
failure_code = str(evidence.get("failure_code") or "").strip()
if failure_code in _MODEL_FAILURE_MESSAGES:
    return _MODEL_FAILURE_MESSAGES[failure_code]   # <- wins over everything
```

Captured live (pre-crash J run): a payload carrying **identity PRAGMATA, 2
accepted claims, `requirement_completeness: complete`, `discovery_status:
completed`, `research_outcome.failure_code: null`, and 3 products** was narrated as:

> "I could not complete the workload interpretation before its deadline. Research
> and product fit were not concluded; no product or commerce action was authorized."

The *router* timed out; *research* succeeded independently via the structured
provider. The composer conflates the two. Previously a harness failure was
narrated as a catalog fact; now a research success is narrated as a harness
failure. Same class, opposite sign.

**Fix:** the failure branch must yield when the terminal research outcome shows
`accepted_claim_count > 0` or `requirement_completeness == "complete"` — degrade
to "interpretation was degraded, here is what research established" instead of
claiming nothing concluded. Also "no product … was authorized" is falsified by
a payload that carries products.

### 3.2 · The last mile — two authorities disagree, and the blocking one wins

J is the clearest case in the whole arc. On one turn:

| Authority | Says |
|---|---|
| `workload_authorization` | `status: resolved`, `reason: enrolled_structured_provider_requirements`, **`next_permitted_action: catalog_qualification`** |
| `semantic_resolution` | `outcome: clarify`, **`reasons: ["unresolved_material_concept"]`**, `subject_role: UNRESOLVED` |
| Result | `catalog_authority: blocked`, `recommendation_status: held`, `product_shelves.shelves: []` |

The concept `semantic_resolution` calls unresolved is *"pragmata"* — the exact
concept the structured provider resolved on the same turn, to app_id 3357650,
with `ram_gb >= 16` and `gpu_vram_gb >= 4` marked `authority_status:
verified_official`. Nothing propagates that resolution back into
`semantic_resolution`, so the clarify gate blocks the catalog and asks *"Which
named software or standard governs this work?"* about software it just identified.

The narration then over-claims in the other direction: *"its published minimum
requirements were **applied to the catalog**"* — with `catalog_authority: blocked`
and zero shelves, they were not.

**This single reconciliation is what stands between "0 products on every research
turn" and a real shelf ranked against verified official minimums.**

### 3.3 · Where Winds Meet fails twice, for two different reasons — both span hygiene

Direct connector probe (live):

```
'where winds meet'             -> 'Where Winds Meet'  rel=14 Nov, 2025   (0 ms, cached)
'Where Winds Meet'             -> 'Where Winds Meet'  rel=14 Nov, 2025   (1140 ms)
'where winds meet is 3000 ok'  -> None                                   (1855 ms)
'for where winds meet'         -> None                                   (1539 ms)
'The Blood of Dawnwalker'      -> 'The Blood of Dawnwalker' rel=2 Sep, 2026 (1244 ms)
'bloodwalker the new witcher'  -> None                                   (2053 ms)
```

The coverage exists. The spans do not survive.

* **I-T1** — `"will a $3000 laptop run where winds meet?"` → the router emitted
  **no entity and no semantic proposal at all**; `discovery: not_attempted`. A
  recall failure on a sentence that contains an explicit `run` relation.
* **A-T2** — `"what about for where winds meet is 3000 ok?"` → concept captured
  as **`"where winds meet is 3000 ok"`**, the whole sentence tail including the
  budget. Fed verbatim to the structured provider → `None`.

This is the R3-class dirty-span bug from 08-31 and the `"for where winds meet"`
bug from 09-02, resurfacing in a **new location**: the unclamped
`semantic_proposal.concepts.query_span`, rather than `workload_entities`.

### 3.4 · N4 residual — a singular unit noun still becomes a count

```
'will a $3000 laptop run where winds meet?'   qty=None    OK  (fixed)
'on a 2500 laptop'                            qty=2500    BAD (still broken)
'I need 3000 laptops'                         qty=3000    OK  (genuine count)
```

The guard keys on budget-span overlap and currency prefix; `"2500 laptop"` has
neither. The discriminator that actually separates the three is **grammatical
number**: `laptops` (plural) can take a count, `laptop` (singular, article-led)
cannot. G is still asked a quantity-scope question about one kid's laptop.

### 3.5 · Ops — the live battery is bugchecking this machine

The crash mid-probe was a real bugcheck, and it is the **second in two days**:

| When | Stop code | Meaning |
|---|---|---|
| 2026-09-04 11:43:52 | `0x116` VIDEO_TDR_ERROR, p3 `0xC000009A` (STATUS_INSUFFICIENT_RESOURCES) | GPU hang, display driver failed to recover |
| 2026-09-03 19:42:31 | `0x133` DPC_WATCHDOG_VIOLATION | driver DPC overrun |

Five minidumps since 2026-08-30 (`C:\Windows\Minidump\`). GPU is an **RTX 5070 Ti
Laptop, 12,227 MiB total**, driver 592.01; qwen3:14b resides at ~9.6 GB, leaving
~2.3 GB for the desktop compositor and any second model. Today's crash happened
with **no browser running** — a pure API probe — so GPT-5.6's
`PLAYWRIGHT_DISABLE_GPU` mitigation in `playwright.config.ts`, while correct for
the 09-03 crash, would not have prevented this one. Nothing was lost (the tree is
byte-identical), but the certification runs are not currently survivable
unattended.

---

## 4. Is external search working?

**Acquisition: yes, for the first time.** Novel titles the model has never seen
resolve through an enrolled structured provider with official, cited, dated
claims, and the platform correctly refuses to judge a budget for an unreleased
title. That is the S1/S2/S3-T2 capability the last four documents said was missing.

**Delivery: no.** 0 products on 5 of 6 research turns; the two turns that
returned products returned *generic* ones from turns where research never ran.
The blockers are now few, specific, and none of them require new intelligence:
one authority reconciliation (§3.2), one span clamp (§3.3), one narration
precedence fix (§3.1), one grammatical-number guard (§3.4).

---

## 5. What to do next, in order of buyer-visible failure removed per hour

| # | Item | Why this order | Owner |
|---|---|---|---|
| 1 | **Reconcile `semantic_resolution` with structured-provider resolution** — a concept resolved by an enrolled provider must clear `unresolved_material_concept` and release `catalog_authority` | The only thing between complete verified requirements and a real shelf. Flips J from 0 → ranked products | code |
| 2 | **Clamp the concept span before any provider lookup** — strip budget/filler tails; a concept span must be the title, not the sentence | Fixes A-T2 and every future colloquial phrasing; connector already resolves the clean span in 0 ms | code |
| 3 | **Narration precedence** — a concluded research outcome outranks a router `failure_code`; never say "no product was authorized" on a payload carrying products | Truthfulness; currently can call a success a failure | code |
| 4 | **Router recall on I-phrasing** — `"will a $3000 laptop run <title>?"` must emit an entity or a material concept | I is the single most natural buyer sentence in the set and produces no research at all | code |
| 5 | **Quantity guard on grammatical number** — singular article-led unit can never be a count | G still asks a bulk-quantity question about one laptop | code |
| 6 | **Low-confidence identity → clarifying question** ("Did you mean *The Blood of Dawnwalker*?") instead of "found 0 candidate publisher source(s). Review the ranked ownership evidence" | G/A-T2 still emit the W3 sentence that points at evidence that does not exist | code |
| 7 | **R12** — sign off Rockwell (one field) or make the hold advisory | One decision unblocks every enrolled-source turn | **user (policy)** |
| 8 | **Add a non-instructive case to the certificate** — one prompt with no run/play/need verb (the A-T2 phrasing) | Current certificate cannot fail on the case that fails live | test |
| 9 | **Ops: make certification survivable** — cap resident models to one during live runs, keep `PLAYWRIGHT_DISABLE_GPU=1`, consider a smaller router for battery runs | Two BSODs in two days; runs cannot be left unattended | **user (ops)** |
| 10 | **Commit the round-#5 delta** — 1,337 lines of verified-good work is uncommitted on a dirty tree that has now survived one bugcheck by luck | Risk | **user** |

---

## 6. What needs the user's eyes (frontend), and what a browser clickthrough must assert

The API proves the contract; only the browser proves the buyer *sees* it. Three
things in this delta have **never been rendered in front of a human**:

1. **`ArchitectureAlternativesPanel`** — new component, wired at `App.tsx:3774`,
   populated on J. Never visually confirmed. Needs: does it render, is it legible,
   does it appear when `selected_class` is null and not otherwise?
2. **Top-level `buyer_requirement_claims` card** — J now projects 2 claims with
   `authority_status: verified_official` and a real Steam URL. Does the existing
   review card render them on the *chat* path, and does the Accept/Reject
   affordance behave?
3. **Decision Trace on a structured-provider turn** — does the new
   `enrolled_structured_provider_requirements` basis show, and does the
   "Verified evidence" label now appear only when claims are genuinely accepted?

### Proposed clickthrough (6 scenarios, ~10 min, non-instructive prompts)

| # | Prompt | Assert |
|---|---|---|
| 1 | `is 3000 enough for pragmata?` | identity card names PRAGMATA + CAPCOM + released 16 Apr 2026; claims card shows `ram_gb ≥ 16` / `gpu_vram_gb ≥ 4` as **verified_official** with the Steam link; **shelf non-empty after fix #1**; narration does not claim "applied to the catalog" while blocked |
| 2 | `tarae recommended specs, is 3500 enough` | "unreleased / To be announced" stated **before** any product; no office-laptop shelf; no budget verdict |
| 3 | `can my kid play bloodwalker the new witcher on a 2500 laptop` | no "The Witcher 3 REDkit" anywhere; a **clarifying question**, not "review the ranked ownership evidence"; **no quantity-scope question** |
| 4 | `what about for where winds meet is 3000 ok?` (as turn 2 after "gaming laptop under 3000") | identity resolves to Where Winds Meet (rel 14 Nov 2025); budget question actually answered; continuity kept |
| 5 | `I need a computer to do digital twin simulations` | **two shelves** (desktop + mobile workstation) via the new panel; never "These all handle…" next to Found 0 |
| 6 | `workstation for Rockwell Emulate3D under AUD 6000` | held count spoken out loud ("8 held pending review"), not "no qualified match under $6,000" |

**Run conditions that matter:** `USE_MOCK_LLM=0`, one resident model,
`PLAYWRIGHT_DISABLE_GPU=1`, and the run watched — on current evidence there is a
material chance of a third bugcheck.

---

## 7. Method

Restored the stack after the bugcheck (Docker Desktop → `shopsquire-recording-redis`
+ `shopsquire-searxng-1`; `scripts/start_recording_stack.ps1 -LiveDemo`), warmed
qwen3:14b with a 45 m keep-alive, then ran a fresh-`uid` probe that POSTs
`/api/v1/chat/query` and **polls the same `Idempotency-Key`** until the producer
completes (my first probe did not poll and read the async placeholder as an
answer — that was my bug, not the platform's). Cross-checked in code, in the
changed test suite (88 pass), by direct calls into
`steam_requirements.get_game_requirements` and `commercial_terms.parse_commercial_terms`,
and against the Windows System event log and `C:\Windows\Minidump`.
Raw payloads: `scratchpad/probe4/{A,E,G,I,J}-T*.json`. No repository file was
modified.
