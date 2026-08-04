# Open Blockers — recommend.py Decomposition (Deep Dive #2)

**Companion to**: [RECOMMEND_DECOMPOSITION_ROADMAP.md](RECOMMEND_DECOMPOSITION_ROADMAP.md)  
**Last updated**: 2026-06-20  
**Source**: 3 parallel explorations of `suggest()` state, bulk-extraction strategies, and test/UI couplings.

---

## Executive summary

Three new classes of blockers surfaced beyond the known `constraints` dict:

1. **15+ hidden mutable shared variables** (not just `constraints`) — `timing_breakdown`, `image_context`, `kv_out`, `structured_state_out`, `fraud_summary`, etc. — each mutated across many phases.
2. **ContextVar side-channels** — `_CURRENT_QUERY_CTX` and `_KNOWLEDGE_QUERY_CTX` carry state into deeply-nested helpers without explicit parameters.
3. **Test imports of 7+ private symbols** still pinning real implementations to `recommend.py` — extraction without breaking tests requires either preserving wrappers or repointing test imports.

But also: **a faster path exists**. The single biggest ROI move is **NOT** the careful leaf-extraction we've been doing — it's a **3-step phase-as-stage extraction (~4,000 lines in three commits)** with one prerequisite (golden contract test).

---

## 1. Hidden mutable shared state (NEW blockers)

These are dicts/lists declared early in `suggest()` and mutated across many downstream phases. Each one is a `constraints`-style blocker.

| # | Variable | Decl | Mutation sites | Why it blocks extraction |
|---|---|---|---|---|
| BLK-1 | `timing_breakdown: dict` | [L4100](../../src/app/routers/recommend.py#L4100) | 12+ sites (`guard_ms` L4274, `catalog_profile_ms` L4538, `nlp_ms` L5465, `rerank_ms` L9378) | Every phase writes its own latency key |
| BLK-2 | `image_context: dict` | [L4216](../../src/app/routers/recommend.py#L4216) | Populated L4381, structurally stripped by policy gate L4434-4443 | Security gate mutates a payload the retriever later reads |
| BLK-3 | `kv_out: dict` | [L11195](../../src/app/routers/recommend.py#L11195) | 20+ mutations L11195-L11295 | Tail-phase "mirror everything to Redis" — every extracted phase still needs to project its state back here |
| BLK-4 | `structured_state_out: dict` | near L11195 | Same as BLK-3 | Same |
| BLK-5 | `fraud_summary: dict` | early | Written by multiple security stages | Dual-write to log + Redis + local |
| BLK-6 | `nlp: dict` | mid | Strategy tags written across multiple sites e.g. L6006 | Inline merging into trace event |
| BLK-7 | `response/payload: dict` | late | Built across many sites; defensive `.get()` patterns | The 6+ `_ensure_trace_response` calls each fix missing keys |

### Pattern: every BLK-N follows the same shape

```python
foo: dict = {}                # early decl
# ... 3000 lines ...
foo["thing_a"] = compute_a()  # phase 4
# ... 2000 lines ...
foo["thing_b"] = compute_b()  # phase 7 (reads thing_a implicitly via foo)
# ... 1500 lines ...
return {..., "foo_summary": foo, ...}
```

### Implication

`SuggestContext` (already exists at [src/app/services/suggest_context.py](../../src/app/services/suggest_context.py)) needs **at minimum 8 typed slots**, not just `constraints`. Treat it as a `dataclass` with these fields:

```python
@dataclass
class SuggestContext:
    constraints: dict
    timing_breakdown: dict
    image_context: dict | None
    kv_out: dict
    structured_state_out: dict
    fraud_summary: dict
    nlp: dict
    response: dict
    trace_id: str
    # ...plus the existing fields it already has
```

---

## 2. ContextVar side-channels

These are read-without-being-passed in deep helpers:

| ContextVar | Set | Read | Risk |
|---|---|---|---|
| `_CURRENT_QUERY_CTX` | [L4092](../../src/app/routers/recommend.py#L4092) | `_extract_brand_hints`, `_apply_safety_filter` | Hidden dependency — extracted helpers may silently lose query context |
| `_KNOWLEDGE_QUERY_CTX` | [L4229](../../src/app/routers/recommend.py#L4229) | L4551 (retrieval scoping) | Same |

**Action**: when extracting a phase that calls these helpers, EITHER pass query/plan explicitly, OR keep the `ContextVar.set()` call in the orchestrator (not inside the extracted stage).

---

## 3. Cross-cutting concerns inside `suggest()`

These belong elsewhere (decorators, middleware, background tasks) and can be removed from the body entirely.

| Concern | Count | Sample lines | Proposed extraction |
|---|---|---|---|
| `log_trace_event(...)` wrapped in `try/except: pass` | 14+ | L4278, L4417, L11130, L11162 | `@trace_event("name")` decorator OR a `with trace_span(...)` context manager |
| `emit_security_event(...)` | 3 | L4345, L11438 | Move into security stage |
| `Thread(...).start()` (shadow pipeline) | 1 | L4192 | Move to `BackgroundTasks.add_task` or fire-and-forget helper |
| `record_meter_event` / `record_pipeline_v2_shadow` | 2 | L4186, L11417 | Metrics decorator |
| Policy gate enforcement | ~1 block | L4339 region | `@enforce_policy_gate(surface="suggest")` dependency |
| Model-theft rate limiting | ~1 block | early body | `Depends(enforce_model_theft_controls)` |
| Trace span setup | ~1 block | top of suggest() | `@with_trace_span("recommend.suggest")` |
| Request pseudonymization (`uid_hash`) | ~1 line | early body | `uid_hash: str = Depends(get_uid_hash)` |

**Estimated removal**: 30-40 lines plus collapsing of the 14 `try/except: pass` wrappers (~70 lines total).

---

## 4. Duplicated/shadow implementations (already-extracted logic re-implemented inline)

These exist because earlier strangler passes added the helper but didn't replace the inline copy:

| # | Inline location | Duplicates module | Risk |
|---|---|---|---|
| DUP-1 | [L6010-L6085](../../src/app/routers/recommend.py#L6010) — image brand detection + price floors | `recommend_image_hints.py` | Behaviour drift |
| DUP-2 | [L5875-L5884](../../src/app/routers/recommend.py#L5875) — persona regex scoring | `recommend_persona.py` | Behaviour drift |
| DUP-3 | [L5830-L5845](../../src/app/routers/recommend.py#L5830) — budget extraction | `recommend_budget_parsing.py` + `service.parse_constraints()` | Behaviour drift |
| DUP-4 | [L6226-L6460](../../src/app/routers/recommend.py#L6226) — NQE slot merging | `recommend_nqe_stage.py` `RecommendNQEHooks` | Confirmed by NQE deep dive |
| DUP-5 | [L7591-L7694](../../src/app/routers/recommend.py#L7591) — open-ended early-return NQE chain | `recommend_nqe_stage.py` L400-L450 | Confirmed |

**Quick win**: replace each inline block with a call to the existing module. **Estimated savings: ~500 lines**, zero new modules created.

### Verified status — 2026-06-20 (the quick win is mostly already done)

A line-by-line verification (line numbers in the table above are STALE — content shifted
~200 lines) found the Pass 9a–10 stream already resolved most of these:

| # | Verified state | Evidence |
|---|---|---|
| DUP-1 | **Data deduped** — patterns now profile-backed `_brand_label_patterns()` (recommend.py L6214). Remaining inline loop (L6226-L6260: Apple hard-lock, trace logging) has **no equivalent module function** to call; deduping it means *creating* one (contradicts "no new files"). | L6214 `_BRAND_LABEL_PATTERNS = _brand_label_patterns()  # excised → StoreProfile` |
| DUP-2 | **✅ DONE** — `_detect_buyer_persona_with_confidence` (L2320) is a one-line thin wrapper to `recommend_persona`. No inline regex remains. | L2320-L2321 |
| DUP-3 | **✅ DONE** — budget extraction is the module call `_extract_explicit_budget_override` (L5848); module imported L3788. | L5848, L3788-L3793 |
| DUP-4 | **NOT a duplicate** — L5810-L5883 is bespoke session-slot glue (merge prior-turn `nqe_answered_fields` + confirmed_slots into constraints). `RecommendNQEHooks`/`run_recommend_nqe_stage` do not do this. Nothing to call. | L5810-L5883 vs recommend_nqe_stage.py L46-L85 |
| DUP-5 | ✅ **RESOLVED (a6fab44, 2026-06-20)** — the actual drift was the duplicated NQE input-builder (fatigue-filtered asked-ids + answered-fields bridge), now ONE helper `recommend_nqe_helpers.build_nqe_asked_and_answered` shared by both paths (verified byte-identical). The two paths' control flow is kept distinct on purpose (open-ended early-return-no-products vs stage augment-full-response) — the golden contract test pins those as separate shapes, so a full control-flow merge would risk them for no gain. | L7521 + recommend_nqe_stage L259 |

**Revised estimate: the ~500-line quick win does not exist** — only DUP-5 remains as real work and it is medium-risk, not a drop-in. Treat DUP-5 as part of the NQE-pipeline-dedup workstream, protected by `tests/integration/test_recommend_contract_stability.py`.

### Agnostic-island parity gap (blocks a "low-risk" profile swap)

`category_router.py` (decision path: recommend.py L644/L1503/L9528) and `product_taxonomy.py`
(4 services) hardcode electronics flavour but are **cross-vertical in intent**. A blind
data→profile swap would REGRESS electronics because the profile taxonomies lack parity:
- `_USE_CASE_PATTERNS` (9: gaming/video_editing/programming/business/student/creative/streaming/travel/home_office) vs profile `use_case_patterns` (8, but renames business→office, student→study; **6 missing**).
- `_BRAND_PATTERNS` (14, incl. nvidia/amd/intel components) vs profile `manufacturers` (12 LAPTOP makers; **6 missing**, different purpose).

Correct sequence (a focused pass, not tail-of-turn): reconcile taxonomies → expand the profile
slots with parity → excise the module to per-request accessors → no-bleed test → full regression.
Until then these are guarded by the **pending-excision ratchet** in
`tests/test_no_flavour_in_core.py` (`_PENDING_EXCISION`: category_router=16, product_taxonomy=2,
distinct flavour tokens, shrink-only).

---

## 5. "Dual-write" pattern — fold into `emit_event(...)`

3+ sites write the same data to multiple destinations:

| Site | Targets | Lines |
|---|---|---|
| Security/Fraud stats | `log_trace_event` + local `fraud_summary` + Redis Memory | L5078 |
| NLP tags | `nlp` dict + `log_trace_event` payload | L6006 |
| Search analytics | `log_search_event` + `log_trace_event` | L10003 |

**Action**: one helper `emit_event(name, payload, *, also_log=True, also_redis=False)` collapses these.

---

## 6. The "early return graveyard"

8 return sites inside `suggest()`. Every extraction must preserve all of them (they're tested individually).

| Purpose | Count | Lines | State mutated by that point |
|---|---|---|---|
| Fast-path retrieval | 2 | L4236, L4446 | `_CURRENT_QUERY_CTX`, `_KNOWLEDGE_QUERY_CTX` |
| Inventory intercept | 1 | L4296 | `timing_breakdown["guard_ms"]` |
| Security/Maestro block | 2 | L4339, L4364 | `trace_id`, `timing_breakdown` |
| Final success | 1 | L11482 | All `kv_out`, `structured_state_out`, `timing_breakdown` |
| (others: domain rejection, ratelimit) | 2 | various | varies |

**Implication for golden contract test (see §8)**: at least 6 distinct response shapes must be snapshot-tested before phase extraction is safe.

---

## 7. Test couplings to private symbols (extraction friction)

The following tests import `_` symbols from `recommend.py` directly. Extracting them requires either keeping a thin wrapper (current pattern) or repointing the test import.

| Test file | Symbol | Real impl location |
|---|---|---|
| [tests/api/test_agent_human_enhancements.py:109](../../tests/api/test_agent_human_enhancements.py#L109) | `_adapt_nqe_questions_for_sentiment` | In recommend.py (not yet extracted) |
| [tests/test_image_lane_fill.py:35](../../tests/test_image_lane_fill.py#L35) | `_top_up_image_results` | In recommend.py |
| [tests/test_recommend_support_claim_routing.py:6](../../tests/test_recommend_support_claim_routing.py#L6) | `_classify_turn_intent` | In recommend.py |
| [tests/test_recommend.py:1173](../../tests/test_recommend.py#L1173) | `_summarize_results` | In recommend.py (~373 LoC, L3657-L4030) |
| [tests/test_recommend.py:1408](../../tests/test_recommend.py#L1408) | `_infer_use_case_from_query_text` | In recommend.py |
| [tests/test_recommend.py:902](../../tests/test_recommend.py#L902) | `_deterministic_assistant_message` | **Already thin wrapper** → `recommend_budget_advisor` |
| [tests/test_recommend_spec_blocks_and_support_cards.py:9](../../tests/test_recommend_spec_blocks_and_support_cards.py#L9) | `_parse_explicit_spec_blocks` | In recommend.py |
| [tests/test_recommend.py:1735](../../tests/test_recommend.py#L1735) | `_classify_turn_type` | In recommend.py |

### Patch targets (additional friction)

- `tests/security/test_model_theft_recommend_wiring.py` patches `enforce_model_theft_rate_limit`, `detect_systematic_probing`, `enforce_model_theft_policy_gate` AT the `recommend` module — if these are extracted, each patch needs updating.
- `tests/test_recommend.py` patches `recommend_router.httpx.Client`, `select_ollama_model`, `is_complex_query`, `complexity_explain`.

### Recommended freeze-the-surface order

1. Add `__all__` to recommend.py listing every symbol tests import — locks the surface
2. For each test-imported private symbol, extract to a dedicated services module + keep thin wrapper in recommend.py (current pattern works)
3. Once stable, do a sweep PR to repoint imports `from src.app.routers.recommend import _foo` → `from src.app.services.recommend_foo import foo`
4. Remove wrappers in a final cleanup PR

---

## 8. Frontend contract surface (cannot break)

Fields produced by `suggest()` that the UI consumes. Any phase extraction must preserve these exactly:

| Field | suggest() source | UI consumer | Already extracted? |
|---|---|---|---|
| `assistant_message` | L1317 | [shopsquire-widget.js:625](../../src/frontend/widget/shopsquire-widget.js#L625) | `recommend_response_finalizer` |
| `next_questions` | L1360 | [App.jsx:3495](../../src/frontend/storefront-react/src/App.jsx#L3495) | `recommend_nqe_stage` |
| `right_panel.anchor_sections` | L476 | Storefront sidebar | Partially in suggest() |
| `decision_trace_id` | L1329 | Admin trace link | `_with_trace` |
| `evidence_items` | via `log_trace_event` | [Decisions.tsx:165](../../src/frontend/admin-react/src/components/Decisions.tsx#L165) | `recommend_narration_stage` |
| `buyer_persona` | `intent_snapshot` | Admin persona badge | `query_understanding` |
| `memory_confidence` | `retrieved_context` | [MerchantBIPro.tsx:899](../../src/frontend/admin-react/src/components/MerchantBIPro.tsx#L899) | `Memory` service |

**Mandatory**: before any phase-as-stage extraction, write `tests/integration/test_recommend_contract_stability.py` — a golden-snapshot test asserting the exact JSON keys/structure of `suggest()` for ≥6 input cases (support query, image match, zero results, off-domain, security block, success).

---

## 9. THE FASTER PATH — Phase-as-stage bulk extraction

This is the answer to **"is there another way to excise larger chunks faster?"** — **YES**.

### Step 1: Prerequisite (1 day)

Build the golden-contract snapshot test described in §8. Run it once to lock the current behaviour. Without this, the bulk extractions below are unsafe.

### Step 2: Bulk phase extractions (~4,000 lines in 3 commits)

| # | Stage | Source lines | Target file | Removed | Risk | Notes |
|---|---|---|---|---|---|---|
| **F1** | **Constraint Engine** | [L5636-L7000](../../src/app/routers/recommend.py#L5636) (1,300 lines) | `src/app/services/recommend_constraint_engine.py` | ~1,300 | **HIGH** | Single biggest blocker — requires passing `constraints` + 5 other dicts as a context object. Best done by introducing `SuggestContext` first. |
| **F2** | **Retriever Stage** | [L7686-L9000](../../src/app/routers/recommend.py#L7686) (1,300 lines) | `src/app/services/recommend_retriever_stage.py` | ~1,300 | MED | Complex DB fallback loops (Apple/Windows paths). Depends on F1 since it reads constraints. |
| **F3** | **Narration Stage** | [L10001-L11482](../../src/app/routers/recommend.py#L10001) (1,400 lines) | `src/app/services/recommend_narration_stage.py` (extend existing) | ~1,400 | MED | Payload assembly + dual-write tracing. Can run before F1 if it only READS state. |

**Total**: ~4,000 lines off in 3 commits → suggest() drops from ~7,400 to ~3,400 body lines.

### Step 3: Cross-cut decorators (~70 lines, 1 commit)

Move policy gate / model-theft / trace-span / pseudonymization to FastAPI dependencies (see §3). Drops `suggest()` signature complexity and another ~70 lines.

### Step 4: Kill the duplicates (~500 lines, 1 commit)

Replace the 5 inline duplications (§4) with calls to existing modules. ~500 lines off, **no new files**.

### Updated plan: 5 commits, ~4,570 lines removed

| Commit | What | Lines removed | Risk |
|---|---|---|---|
| 1 | Golden contract test (added, not subtracted) | 0 | Low |
| 2 | F3 Narration Stage extraction | ~1,400 | MED |
| 3 | F1 Constraint Engine + SuggestContext wide adoption | ~1,300 | **HIGH** |
| 4 | F2 Retriever Stage | ~1,300 | MED |
| 5 | Duplicates cleanup + cross-cut decorators | ~570 | Low |

**suggest()** would land at ~2,800 lines — 4× smaller than today, and what remains is mostly the orchestrator + early-return paths.

---

## 10. Why this is faster than what we've been doing

The current pattern (Pass 9c/9d/9e) extracts ~150-600 lines per pass, requires 2-3 helpers per pass, and **does not touch the mutation-state blockers**. After 10 passes we'd still have a 7,000-line `suggest()`.

The phase-as-stage path:
- Builds the safety net once (golden test)
- Pays the SuggestContext-migration cost once
- Then each phase becomes a one-commit lift instead of a multi-commit drip

**Trade-off**: F1 (Constraint Engine) is high-risk — touches 40 mutation sites in one PR. Mitigation: keep `constraints` as a plain dict that `SuggestContext` exposes via `ctx.constraints` initially. The dataclass becomes a typed bag, not a forced rewrite of every mutation.

---

## 11. Concrete extraction recipes (core/adapter)

### Recipe template

For every helper/phase moving from `recommend.py` to a services module:

1. **Decide CORE vs ADAPTER**
   - CORE = no electronics flavour, no hardcoded brand/spec/use-case data
   - ADAPTER = contains brand lists, GPU tokens, persona patterns, etc.
2. **Create file** with the standard banner:
   ```python
   """
   ═══════════════════════════════════════════════════════════════════════════
   <module name> — <CORE | ADAPTER (electronics)>
   ═══════════════════════════════════════════════════════════════════════════
   """
   ```
3. **Move the function(s)**; keep a thin wrapper in recommend.py:
   ```python
   from src.app.services.foo import bar as _bar
   def _bar(...):  # legacy alias preserved
       return _bar(...)
   ```
4. **If CORE** and contains any flavour regex (`rtx|gtx|vivobook|...`), refactor to read from `profile_slot("slot_name", default=...)` AND add the slot to `electronics.json`.
5. **Add to `_CORE_MODULES`** in [tests/test_no_flavour_in_core.py](../../tests/test_no_flavour_in_core.py) if CORE — guard prevents flavour from creeping back.
6. **Run scoped pytest**: `python -m pytest tests/test_recommend.py tests/test_no_flavour_in_core.py -q` before committing.

### Recipe — Phase 2A slots (P0/P1)

For each slot in [the priority matrix](RECOMMEND_DECOMPOSITION_ROADMAP.md#phase-2a-sprint-plan-do-p0--p1-together):

```python
# Before (in adapter module):
PERSONA_PATTERNS = {"student": [...], "creator": [...], ...}

# After:
def _persona_patterns() -> dict:
    return profile_slot("persona_patterns",
                        default={"student": [...], "creator": [...], ...})
```

```jsonc
// config/store_profiles/electronics.json — add:
{
  "persona_patterns": {
    "student": ["student", "school", "university", "homework"],
    "creator":  ["photo", "video", "edit", "render", "design"],
    "gamer":    ["gaming", "game", "esports", "fps"],
    "...":      ["..."]
  }
}
```

```jsonc
// config/store_profiles/pharmacy.json — add:
{
  "persona_patterns": {
    "caregiver":   ["caring for", "parent", "elderly"],
    "self_treat":  ["i have", "my symptoms"],
    "preventive":  ["prevent", "supplement", "vitamin"]
  }
}
```

Test update: add `test_pharmacy_profile_has_persona_patterns` to `tests/test_taxonomy_profile_ssot.py`.

### Recipe — Replace an inline duplicate (per DUP-N in §4)

```python
# Old (inline at L6010-L6085):
for brand, patterns in IMAGE_BRAND_PATTERNS.items():
    if any(re.search(p, query) for p in patterns):
        ...

# New (replace whole block with):
from src.app.services.recommend_image_hints import extract_image_brand_hints
brand_hints = extract_image_brand_hints(query, image_context)
```

Verify by snapshot diff on the golden contract test.

---

## 12. Recommended next 2 weeks

| Day | Task | Outcome |
|---|---|---|
| 1 | Write `test_recommend_contract_stability.py` golden snapshots | Safety net |
| 2 | DUP-1 through DUP-5 cleanup commit | ~500 lines off |
| 3 | Cross-cut decorators commit (§3) | ~70 lines off |
| 4 | F3 Narration Stage commit | ~1,400 lines off |
| 5 | Phase 2A P0 slots (persona_patterns + brand_sql_patterns) | Non-electronics viable |
| 6-7 | F1 Constraint Engine + SuggestContext adoption | ~1,300 lines off (HIGH risk; expect 2 days) |
| 8 | F2 Retriever Stage | ~1,300 lines off |
| 9 | Phase 2A P1 slots (persona_prompt_templates, ranking_rules, spec_extraction_rules) | Non-electronics functional |
| 10 | Phase 2A P2/P3 slots + final cleanup | All ADAPTER constants under profile |

After day 10: `suggest()` ~2,800 lines, second vertical bootable, NQE wiring unified.

---

## 13. Pointer back to the roadmap

- [RECOMMEND_DECOMPOSITION_ROADMAP.md](RECOMMEND_DECOMPOSITION_ROADMAP.md) — has the NQE pipeline detail, Phase 2 slot priority matrix, session-completed log
- This doc — has the new blockers (BLK-1..7, DUPs, decorators, test couplings) and the FASTER bulk path

Both documents should be read together when planning the next sprint.
