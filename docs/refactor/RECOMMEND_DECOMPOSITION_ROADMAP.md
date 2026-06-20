# recommend.py Decomposition Roadmap

**Status**: Living document — updated as passes land.  
**Last updated**: 2026-06-20  
**Branch**: `wip/docker-real-env-20260213`  
**Monolith size**: 12,160 lines (down from ~13,500 at sprint start)

---

## TL;DR

Three workstreams, in order of ROI:

1. **NQE pipeline deduplication** (~1 day) — kill ~150 lines of duplicated wiring in `suggest()` by routing both early-return and post-retrieval paths through a single orchestrator.
2. **Phase 2A: profile-back the 4 P0/P1 ADAPTER slots** — without `persona_patterns` + `brand_sql_patterns` + `ranking_rules` + `persona_prompt_templates`, no non-electronics vertical actually works.
3. **`suggest()` leaf extraction** — three independent phases (~2,200 lines) are extractable now without touching the `constraints` dict; do these before deciding on the harder `constraints → SuggestContext` migration.

---

## 1. NQE Wiring & Question Decomposition

### Issues

| # | Issue | Location | Severity |
|---|---|---|---|
| NQE-1 | Filter chain duplicated between early-return path and stage module | `recommend.py` L7591–L7694 vs `recommend_nqe_stage.py` L400–L450 | High — single bug lands in one path only |
| NQE-2 | `prioritize_domain_refinement_questions` called 4× to recover from filter reordering | `recommend_nqe_stage.py` L400–L450 | Medium — symptom of stages stripping priority |
| NQE-3 | `fatigue_filter` and `dedupe_for_render` are conceptually one stage (suppress repeats) split by predicate (id vs slot) | `recommend_nqe_helpers.py` | Low — cosmetic |
| NQE-4 | Persistence (`nqe_asked_ids` save) is inside stage after `[:2]` cap; reordering breaks fatigue | `recommend_nqe_stage.py` L421 | Low — needs comment, not refactor |

### Fix: extract `recommend_nqe_pipeline.py`

A ~80-line orchestrator that wraps the entire filter chain in one function callable from both paths.

```python
# pseudocode
def run_nqe_filter_chain(
    *, seeds, missing_fields, query, constraints, recent_asked,
    turn, persona, persona_conf, intent, sentiment, contradicted,
) -> tuple[list[dict], dict]:
    qs = filter_nqe_questions_by_missing_fields(seeds, missing_fields, query, constraints)
    qs = apply_intent_specific_question_bank(qs, query=query, constraints=constraints)
    qs = adapt_nqe_questions_for_sentiment(qs, sentiment=sentiment)
    qs, blocked = question_fatigue_filter(qs, recent_asked=recent_asked,
                                           current_turn=turn, window_turns=3,
                                           contradicted_slots_set=contradicted)
    qs = apply_nqe_confidence_gating(qs, intent_confidence=intent.confidence)
    qs = apply_persona_confidence_fallback(qs, persona=persona, persona_confidence=persona_conf)
    qs = inject_grounding_residual_question(qs, constraints)
    qs = dedupe_next_questions_for_render(qs)
    return qs[:2], {"blocked": blocked, ...trace_fields}
```

**Cost**: 1 day. **Wins**: ~150 lines off `suggest()`, single source of truth, no more divergent bugs.

### Pipeline order today

1. **Inbound apply** ([recommend.py L5944](../../src/app/routers/recommend.py#L5944)): `_apply_nqe_selection_to_constraints()` mutates constraints from query params
2. **Open-ended early return** ([L7591–L7694](../../src/app/routers/recommend.py#L7591)): full filter chain inline (no DB hit)
3. **Post-retrieval regular path** ([L10255](../../src/app/routers/recommend.py#L10255)): calls `run_recommend_nqe_stage()` which has its own filter chain

### Question seed sources

1. **Profile-driven** (`nqe_question_packs` in StoreProfile) — primary
2. **Pattern-driven** (`_GAME_PATTERNS`, `_SOFTWARE_PATTERNS` in `nqe.py`) — electronics-specific
3. **Hardcoded fallback** (`ask_budget`, `ask_order_id`) — triggered by missing fields

---

## 2. Phase 2A — Profile-Back the Critical ADAPTER Slots

### Slot mechanism (already exists)

- Defined in [src/app/platform/store_profile.py](../../src/app/platform/store_profile.py)
- Resolution priority: explicit arg → ContextVar (middleware) → `STORE_PROFILE_ID` env → `electronics` default
- Accessor: `profile_slot(slot, default=None)`
- Existing slots: `known_brands`, `brand_price_floors_usd`, `use_case_budget_floors`, `safe_image_brands`, `category_keywords`, `price_bands_usd`, `gpu_prefixes`, `nqe_question_packs`, `spec_constraints`, `use_case_patterns`, `use_case_keyword_map`, `complexity_keywords`, `relevant_image_tokens`, `off_topic_image_tokens`, `cv_returns_pack` and ~15 others

### Migration targets — prioritized

| Priority | Slot name | Source location | LoC | Ease | Blocker for non-electronics? |
|---|---|---|---|---|---|
| **P0** | `persona_patterns` | `recommend_persona.PERSONA_PATTERNS` ([L36-84](../../src/app/services/recommend_persona.py#L36)) | ~50 | Easy | **YES** |
| **P0** | `brand_sql_patterns` | `recommend_candidate_classify.brand_sql_predicate` ([L103-134](../../src/app/services/recommend_candidate_classify.py#L103)) | ~30 | Easy | **YES** |
| **P1** | `persona_prompt_templates` | `recommend_persona.build_persona_prompt_context` ([L135-188](../../src/app/services/recommend_persona.py#L135)) | ~50 | Medium | **YES** |
| **P1** | `ranking_rules` | `recommend_ranking.use_case_rank_adjustment` ([L40-125](../../src/app/services/recommend_ranking.py#L40)) | ~85 | Medium | **YES** |
| **P1** | `spec_extraction_rules` | `recommend_utils._extract_candidate_numeric_specs` ([L112-132](../../src/app/services/recommend_utils.py#L112)) | ~20 | Easy | Yes (specs differ wildly per vertical) |
| **P2** | `techy_query_tokens` | `recommend_nqe_helpers._TECHY_QUERY_TOKENS` ([L35-56](../../src/app/services/recommend_nqe_helpers.py#L35)) | ~20 | Trivial | No |
| **P2** | `gpu_type_tokens` | `recommend_utils` ([L143-157](../../src/app/services/recommend_utils.py#L143)) | ~15 | Easy | No |
| **P2** | `price_bracket_thresholds` | `recommend_budget_parsing.BUDGET_BRACKETS` ([L30-35](../../src/app/services/recommend_budget_parsing.py#L30)) | 4 entries | Trivial | Maybe — `price_bands_usd` slot may already cover |
| **P3** | `use_case_display_labels` | `recommend_budget_advisor` ([L59-81](../../src/app/services/recommend_budget_advisor.py#L59)) | ~20 | Trivial | No |
| **P3** | `domain_entity_patterns` | `flows/nqe.py _GAME_PATTERNS` ([L93-97](../../src/app/flows/nqe.py#L93)) | ~15 | Medium | No |

### Phase 2A sprint plan (do P0 + P1 together)

1. Add slots to `electronics.json` (verbatim copies of current dicts)
2. Add empty/minimal slots to `pharmacy.json` and `fashion.json` (validates JSON schema)
3. Each adapter module reads via `profile_slot(name, default=<current hardcoded value>)` — default ensures zero-risk rollout
4. Build small rule evaluator for `ranking_rules` (~30 lines):
   ```python
   # rule shape:
   # {"when": {"use_case_in": ["student", ...]}, "then": {"score_delta": +1.1, "reason": "+portable"}}
   ```
5. Extend `test_taxonomy_profile_ssot.py` to assert non-electronics profiles don't reference electronics flavour in new slots

### Risk: `persona_prompt_templates` JSON escaping

Templates contain multi-line natural-language LLM guidance. Embedding them in JSON requires escaping that hurts readability.  
**Recommendation**: store as `config/store_profiles/electronics/persona_prompts/<persona>.md` files, referenced from the profile by path.

---

## 3. `suggest()` Decomposition

### Function spans [L4066–L11482](../../src/app/routers/recommend.py#L4066) — 7,416 lines, 11 phases

| Phase | Line range | DB? | Redis? | Mutates `constraints`? | Extractable now? |
|---|---|---|---|---|---|
| Grounding & Guardrails | 4066–4480 | – | ✓ | – | Partial |
| Security & Privacy | 4801–5120 | – | ✓ | – | **YES** |
| Fraud & KYC | 5121–5325 | – | ✓ | – | **YES** |
| Memory Sync | 5326–5475 | – | ✓ | – | Partial |
| Intent/NLP | 5476–5635 | – | – | ✓ | No (mutates) |
| **Constraint Assembly** | 5636–7000 | – | – | **✓✓✓ (40 sites)** | **NO — blocker** |
| Support Handoff | 7001–7685 | ✓ | – | – | Partial |
| Retriever & Filter | 7686–9000 | ✓ | – | – | No (depends on constraints) |
| Inventory Agent | 9001–9200 | ✓ | – | – | **YES** |
| Rank & Score | 9201–10000 | – | – | – | No (depends on constraints) |
| Narration & Trace | 10001–11482 | – | ✓ | – | **YES (prompt assembly only)** |

### The single biggest blocker

The mutable `constraints: dict` is mutated in **~40 sites across `suggest()`** ([L5636](../../src/app/routers/recommend.py#L5636), [L6051](../../src/app/routers/recommend.py#L6051), [L8351](../../src/app/routers/recommend.py#L8351) among others).

Any phase that touches `constraints` cannot be extracted into a value-returning function because its mutations are visible to later phases. Until `constraints` becomes a typed object passed explicitly, the remaining 7k lines effectively form one big procedure.

### Two paths forward

**Path A — Extract leaves now (low risk)**

| Step | New module | Lines | Risk |
|---|---|---|---|
| A.1 | `recommend_security_gate.py` (Security + Fraud + KYC phases) | ~520 | Low |
| A.2 | `recommend_nqe_pipeline.py` (NQE dedup from §1) | ~80 wrapper + kills ~150 dup | Low |
| A.3 | `recommend_narration_prompt.py` (just LLM prompt assembly, not the call) | ~400 | Medium |
| A.4 | `recommend_inventory_agent.py` (remaining inline blocks) | ~200 | Low |

Total: ~2,200 lines extractable. Brings `suggest()` under 10k.

**Path B — Migrate `constraints` → `SuggestContext` (high risk, opens the door)**

- `SuggestContext` dataclass already exists at [suggest_context.py](../../src/app/services/suggest_context.py)
- Every `constraints[k] = v` becomes `ctx.set_constraint(k, v)`
- Every `constraints.get(k)` becomes `ctx.get_constraint(k)`
- Once done: Constraint Assembly (1,364 lines), Retriever (1,314 lines), Rank (799 lines) all become extractable as pure functions over `ctx`

Cost: 1–2 weeks. Risk: high (40 mutation sites, defensive `.get()` calls, hidden coupling).

### Recommendation

Do **Path A first**, then re-evaluate. If you only need 1–2 more verticals, **Phase 2A may give you what you need without further decomposition.**

---

## Decision matrix

| If your goal is... | Do this | Cost | Outcome |
|---|---|---|---|
| Launch pharmacy/fashion vertical | Phase 2A (P0+P1 slots) | 1 week | Working second vertical |
| Stop NQE bugs landing in only one path | §1 (NQE pipeline extract) | 1 day | Single filter chain |
| Get `suggest()` under 10k lines | Path A (security + nqe + narration prompt + inventory) | 1 week | ~2,200 lines off |
| Make `suggest()` testable in isolation | Path B (constraints → SuggestContext) | 1–2 weeks | Pure-function extraction unlocked |
| All of the above | NQE → Phase 2A → Path A → Path B | 3–4 weeks | Multi-vertical, modular pipeline |

---

## Completed work (session log)

| Pass | Commit | Module(s) | Lines extracted |
|---|---|---|---|
| 5 | e126674 | `nqe_question_packs` → profile slot | – |
| 6 | de54d1b | `use_case_advisor` → profile slot | – |
| 7 | (verified) | `checkout_handoff` already extracted | – |
| 8 | (verified) | `store_vocab` already done | – |
| Supp 1 | c7b1e03 | `complexity_keywords` → profile slot | – |
| Supp 2 | c7b1e03 | CV triage relevance → profile slot | – |
| 9a | da1fbd3 | `recommend_persona.py` + `recommend_ranking.py` | ~200 |
| (demarcation) | 9844b76 | CORE/ADAPTER comments added everywhere | – |
| 9b | 16e10ad | `parse_image_inputs()` wired in | ~108 |
| 9c | 2f0d114 | `recommend_budget_parsing.py` + `recommend_nqe_helpers.py` | ~587 |
| 9d | 9a7d37d | `recommend_candidate_classify.py` | ~134 |
| 9e | 7d0e0ac | NQE selection → constraints added to helpers | ~158 |
| 10 | c7dc94c | `suggest_context.py` added to no-flavour-in-core guard | – |

**Total**: monolith 13,039 → 12,160 lines this session (879 extracted), 14 services modules now own previously-monolithic logic, **574 services tests pass** with no regressions.

**Pre-existing failure** (unchanged): `test_digital_marketing_enhancements.py::TestDeterministicAssistantMessagePersona::test_no_results_returns_none`

---

## Open issues / blockers (deep dive #2 — 2026-06-20)

See [OPEN_BLOCKERS.md](OPEN_BLOCKERS.md) for the full second-pass audit, which includes:

- **15+ hidden mutable shared dicts** beyond `constraints` (BLK-1..7)
- **2 ContextVar side-channels** carrying state into deep helpers
- **5 inline duplications** of already-extracted modules (DUP-1..5) → quick ~500-line win
- **8 cross-cutting concerns** that belong in decorators/middleware (~70 lines off)
- **7 test files** pinning private symbols to recommend.py (extraction friction map)
- **7 frontend contract fields** that must survive any phase extraction
- **The faster path**: 5-commit, ~4,570-line bulk extraction plan via golden-contract test → phase-as-stage migration
- **10-day sprint plan** to drop `suggest()` to ~2,800 lines and bootstrap a second vertical
