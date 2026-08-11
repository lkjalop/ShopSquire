# ShopSquire — CacheRAG Reimplementation Assessment + Temporal Layer Correction (2026-08-02)

*Three corrections to my own prior claims, a corrected impact analysis, and a build-or-discard
verdict with exact wiring.*

---

## 0. Corrections — I was wrong three times, and the method was the problem

| My claim | Reality |
|---|---|
| "CacheRAG doesn't exist" | ❌ **Wrong.** `tests/test_memory_cacherag.py` (Jan 21), commits `188cabcf` + `859ef80a`, 10+ docs. It was a narration-text cache in `recommend.py`. |
| "TemporalRAG doesn't exist" | ❌ **Wrong.** See §1 — bitemporal store + as-of query + time-decayed graph retrieval. |
| "Deleting it cost you latency" | ⚠️ **Overstated.** Narration is now **async off the critical path** (§2.2). It's a *cost* regression, not a latency one. |

**The method error:** I grepped for **marketing names** (`cacherag`, `temporalrag`) instead of
**mechanisms** (`valid_from`, `system_from`, `age_days`, `decay`). A system that implements a
pattern well usually doesn't name its files after the pattern. Corrected approach used below.

---

## 1. TemporalRAG — you have one, and it's more rigorous than most things sold as one

### 1.1 Bitemporal store (not just timestamps)
`services/decision_log.py:107-189` — every decision row carries **four** time columns:

```
valid_from   valid_to      ← VALID time    : when the fact was true in the world
system_from  system_to     ← SYSTEM time   : when we recorded/believed it
```

That's the textbook bitemporal model. It answers two different questions: *"what was true then?"* and
*"what did we believe then?"* — which is what makes an audit reconstructable after a correction.

### 1.2 As-of retrieval
`routers/decision_time_travel.py:7`
```python
@router.get("/asof")
def decision_as_of(decision_id: str = Query(...), timestamp: str = Query(...)):
    """Return decision state as-of a timestamp using bitemporal columns."""
    rows = decisions_as_of(timestamp=timestamp, decision_id=decision_id, limit=1)
```
As-of reconstruction is *the* defining operation of a temporal store. You have it as an endpoint.

### 1.3 Time-decayed graph retrieval — this is the RAG half
`services/hippograph.py`:
```python
max_edge_age_days: int = 90                                     # :103
age_days = (cutoff - observed).total_seconds() / 86400.0        # :180
freshness = max(0.0, 1.0 - age_days / max_edge_age_days)        # :181  ← linear recency decay
decay: float = 0.5                                              # :284
contrib = act * w * (decay ** hop)                              # :297  ← per-hop spreading decay
```
**Edges age out of relevance; activation decays per hop.** That is temporally-weighted retrieval —
recency is in the *ranking function*, not just a filter.

### 1.4 Temporal evidence governance
`market_facts` carries `observed_at` · `ingested_at` · `valid_from` · `valid_to` ·
`freshness_policy`; `market_evidence_policy` resolves contradictions by
`trust_tier_then_freshness_then_confidence`; `currency_authority` refuses on
`fx_authority_stale_or_future`.

### 1.5 Verdict
```
bitemporal fact store  +  as-of reconstruction  +  time-decayed graph ranking
+  freshness-based contradiction resolution  +  staleness refusal
= a TemporalRAG in everything but the filename
```
**Call it what it does:** *"time-aware retrieval over a bitemporal decision store, where evidence
ages out of authority rather than silently persisting."* That sentence is more impressive than the
acronym and it survives someone reading the code.

**The one genuine gap:** temporal *invalidation* — when a newer fact supersedes an older one, the
older edge decays but is never explicitly retracted. That's the "recency-weight → invalidation"
roadmap item from your own notes, and it is the real next step.

---

## 2. CacheRAG — what it was, and what actually happened

### 2.1 What it did
From commit `859ef80a` (2026-06-30), which is unusually honest about its own limits:

> *"caches LLM narration TEXT only (not the full payload) — procurement fields are computed fresh per
> request, NOT lost on cache hit… Real (smaller) issue: the cache fingerprint omits `order_quantity`,
> so a bulk query can reuse a non-bulk query's narration prose (prose↔card mismatch, not data loss).
> CAG/dynamic-context flags are orphaned (defined, never read)."*

**Design was right:** cache the prose, never the commercial payload. A cache hit could never return a
stale price, stock level or margin. **Execution had one real bug:** an incomplete fingerprint.

### 2.2 ⚠️ Corrected impact — narration moved off the critical path

I told you this was a latency regression. That was wrong, because narration is now **asynchronous**:

| File | Line | What |
|---|---:|---|
| `services/recommendation_postflight.py` | **174** | `_enqueue_narration(redis, envelope, core, executor)` |
| `services/recommend_narration_jobs.py` | **99** | `put_narration(redis, job_id, status, message, meta)` |
| `services/recommend_narration_jobs.py` | **114** | `get_narration(redis, job_id)` |
| `services/recommendation_compatibility.py` | **144** | `_apply_narration_compatibility(payload, redis)` |

Narration is enqueued in postflight and fetched by job id. **The turn does not block on it.** So:

- **Latency benefit of a narration cache today: ≈ 0.** The async move already captured it.
- **Cost benefit: real but unmeasured.** Repeated/similar turns re-run a generation that was
  previously served from cache. On self-hosted GPU that's occupancy; on a hosted endpoint it's tokens.

**This materially weakens the case for rebuilding it**, and I should have checked before flagging it.

---

## 3. Build or discard? — **mostly discard, one narrow rebuild**

### The honest verdict

| Option | Verdict |
|---|---|
| **Rebuild the full narration CacheRAG** | ❌ **No.** The latency argument is gone; the cost argument is unmeasured; the fingerprint is the hard part and it's what broke last time; and every cache you add must be enumerable by the DSR erasure sweep or right-to-delete becomes unprovable. |
| **Rebuild a narrow job-level dedupe** | ✅ **Yes, if measurement justifies it.** Prevent re-enqueueing an identical narration job for an identical decision fingerprint. Small, composes with existing primitives. |
| **Do nothing** | ✅ **Also defensible.** Measure first. |

### Measure before building — the gate
```
1. Instrument: narration jobs enqueued/hour, and the % whose decision fingerprint
   was already seen within the TTL window.
2. If duplicate-fingerprint rate < 15% → DISCARD. Write it down and move on.
3. If ≥ 15% → build §4. The number is the justification.
```
**This is the discipline you already apply everywhere else.** Rebuilding on a hunch would contradict
the `no measured trigger → don't add the component` rule you used to reject Kafka, Mongo and TiDB.

---

## 4. If you build it — the exact wiring

### 4.1 You already have the primitive
`services/semantic_cache.py` (319 ln) is better than I credited:

| Method | Line | Relevance |
|---|---:|---|
| `SemanticCache.get/set/delete` | 130/155/190 | base |
| **`set_safe` / `get_safe`** (`source_id`, `trust_score`, `min_trust=0.3`) | 201/225 | **trust-aware caching already exists** |
| **`set_versioned` / `get_versioned`** | 237/277 | **near-exactly the primitive needed** |
| `CacheContract` | 58 | contract type |
| `stable_citation_id` | 36 | stable hashing helper |

**Build on `get_versioned`/`set_versioned`. Do not write a new cache.**

### 4.2 The fingerprint — the part that broke last time
```python
FINGERPRINT_V2 = (
    tenant_id,          # tenant isolation — non-negotiable
    lane,               # SEARCH ≠ PROCUREMENT prose
    node_handle,        # taxonomy grounding
    tuple(sorted(requirements.items())),
    budget_min, budget_max,
    order_quantity,     # ← THE BUG. bulk prose must never serve a non-bulk turn
    currency,           # ← AUD prose must never serve a USD turn
    model_version, prompt_version, policy_version,   # ← invalidate on model change
)
```
`model/prompt/policy_version` are already carried on results (`agentic_rag_pipeline.py:242-251`) —
**including them makes model change control automatic**, which is one of the five enterprise gating
items you already clear.

### 4.3 GDPR constraint — the hard requirement
`routers/privacy.py:326` performs **DSR erasure across all user-linked Redis keys** and
`:335` raises `action_required: "redis_or_cache_erasure_incomplete"` on partial success.

> **Any narration cache MUST be keyed under an enumerable, uid-scoped namespace** —
> `narration:{tenant}:{uid_hash}:{fingerprint}` — so the erasure sweep can find and delete it.
> A cache the sweep cannot enumerate turns right-to-delete from provable into aspirational.

This is the single most important design constraint and it's the one a naive rebuild would miss.

### 4.4 TDD plan — red first, in this order

| # | Test | Red assertion |
|---|---|---|
| 1 | `test_fingerprint_includes_order_quantity` | same query, qty 1 vs qty 15 → **different** keys (the 2026-06 regression, pinned) |
| 2 | `test_fingerprint_includes_currency` | AUD vs USD → different keys |
| 3 | `test_fingerprint_includes_model_version` | model version bump → cache miss |
| 4 | `test_cache_never_stores_commercial_payload` | stored value contains **no** price/stock/margin fields — assert on the serialized blob |
| 5 | `test_cache_hit_recomputes_commercial_fields` | prose from cache, payload fresh (the original design invariant) |
| 6 | **`test_dsr_erasure_removes_narration_cache`** | `delete_user_data(uid)` → key gone; **and** an unenumerable key raises `redis_or_cache_erasure_incomplete` |
| 7 | `test_tenant_isolation` | tenant A never serves tenant B's prose |
| 8 | `test_cache_miss_on_stale_evidence` | evidence beyond `freshness_policy` → miss, not stale prose |
| 9 | `test_dedupe_prevents_duplicate_enqueue` | identical fingerprint within TTL → **one** job, not two |

**Test 6 is the one that must not be skipped.** It's the difference between a cache and a compliance
incident.

### 4.5 Files to touch
```
src/app/services/recommend_narration_jobs.py   +fingerprint_v2(), dedupe guard on put_narration
src/app/services/recommendation_postflight.py  :174  _enqueue_narration → check dedupe first
src/app/services/semantic_cache.py             (no change — use set_versioned/get_versioned)
src/app/routers/privacy.py                     :326  add narration namespace to the erasure sweep
tests/services/test_narration_cache.py         NEW — the 9 tests above
```
**Estimated: ~250 lines + 9 tests. Half a day.** But only after §3's measurement gate.

---

## 5. Frontend / UI-UX

**Do not add a panel.** Add one line to the existing Decision Trace `execution` leaf:

```
┌─ Execution ─────────────────────────────────────────────┐
│  route          6,412 ms   model qwen3:14b              │
│  retrieve         118 ms   postgres bow                 │
│  fit_check         34 ms                                │
│  narration      CACHED     fingerprint 7c21…a4  age 12m │  ← the only new row
│                            (payload recomputed fresh)    │
└─────────────────────────────────────────────────────────┘
```

Two reasons this is the right surface:
1. **It makes the cache auditable.** A reviewer can see prose was reused *and* that the commercial
   payload was not — which answers the obvious objection before it's raised.
2. **It's a trust cue, not a feature.** Consistent with the `TrustCue` layer you just shipped
   (`Human approved` / `Platform authorized` / `Freshness unknown`) — this reads as
   `Narration reused · payload fresh`.

Nothing on the shopper surface. A buyer should never know or care.

---

## 6. Brief for GPT-5.6

> **Item: narration cache (formerly "CacheRAG") — MEASURE, then decide. Do not build on assumption.**
>
> **Context.** A narration-text cache existed in `recommend.py` and was removed with it on
> 2026-07-29 (`f12ea071`). No commit records the loss. Its original design was correct — it cached
> LLM prose only and always recomputed commercial fields — but its fingerprint omitted
> `order_quantity`, so bulk prose could serve a non-bulk turn (commit `859ef80a`).
>
> **Why this is NOT urgent.** Narration is now asynchronous (`recommendation_postflight.py:174`
> `_enqueue_narration` → `recommend_narration_jobs.put_narration/get_narration`). It is off the
> blocking path, so the latency case for a cache is gone. The remaining case is **model-call cost**,
> which is currently **unmeasured**.
>
> **Step 1 (do this first, ~2h).** Instrument narration-job enqueues and the share whose decision
> fingerprint recurred inside the TTL window. **If duplicate-fingerprint rate < 15%, close the item
> and record the number.** This matches the existing "no measured trigger → no new component" rule
> used to reject Kafka/Mongo/TiDB.
>
> **Step 2 (only if ≥15%, ~0.5 day).** Build a job-level dedupe on
> `semantic_cache.set_versioned/get_versioned` (`semantic_cache.py:237/277`) — do **not** write a new
> cache. Fingerprint MUST include `order_quantity`, `currency`, `tenant_id`, and
> `model/prompt/policy_version`.
>
> **Hard constraint.** Key it under an enumerable uid-scoped namespace
> (`narration:{tenant}:{uid_hash}:{fp}`) so the DSR erasure sweep at `routers/privacy.py:326` can
> delete it. A cache invisible to that sweep breaks provable right-to-erasure under GDPR **and APP**.
> `test_dsr_erasure_removes_narration_cache` is mandatory, not optional.
>
> **UI.** One row in the Decision Trace `execution` leaf: `narration CACHED · fingerprint · age ·
> (payload recomputed fresh)`. No new panel, nothing on the shopper surface.
>
> **Separate item — temporal invalidation (higher value than the cache).** The temporal layer is
> real and strong: bitemporal `valid_from/valid_to/system_from/system_to` (`decision_log.py:107`),
> as-of reconstruction (`decision_time_travel.py:7`), time-decayed graph retrieval
> (`hippograph.py:181,297`). The gap is **explicit invalidation**: a superseded fact decays but is
> never retracted. Add supersession edges so a corrected fact demonstrably invalidates its
> predecessor rather than merely out-weighing it. **This is worth more than the cache.**

---

## 7. Business outcome — what each option actually buys

| Option | Business outcome | Honest size |
|---|---|---|
| Rebuild full narration cache | Lower GPU occupancy / token spend on repeated turns | **Unmeasured. Possibly ~0.** |
| Job-level dedupe | Prevents duplicate model work on identical turns | Small, real, cheap |
| **Temporal invalidation** | *"When a supplier corrects a price, the old one is retracted, not out-weighted"* — a demonstrable audit property | **Large.** It's the difference between "we prefer newer" and "we can prove the old one no longer applies." |
| Do nothing on cache | Zero risk, zero compliance surface | Free |

**The strategic read:** you asked about CacheRAG, but the temporal invalidation gap sitting next to
it is the higher-value item — and it strengthens the thing you actually sell. A cache saves compute;
retraction is a governance property you can put on screen.

---

*Corrections and assessment only. No code changed. HEAD `b3dca021`.*
