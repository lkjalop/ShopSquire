# N7 — In-process chat→suggest: comprehensive design

**Date:** 2026-07-07 · **Status:** design (not yet built) · **Author note:** grounded in code, not sketch.
**Goal:** eliminate the loopback HTTP hop `chat.query → GET /recommend/suggest`, killing its latency,
its double-work, and the 502-class failure — without a 7,000-line rewrite.

---

## 0. What the code actually says (and why my first framing was wrong)

I originally said "extract suggest()'s 7,000-line body into a Depends-free core." Reading the code
changed the plan materially:

| Claim (earlier) | Reality in code | Consequence |
|---|---|---|
| `suggest()` reads raw `request.query_params` for `turn_intent`, `image_security_mode`, `budget_widen_*` | **It does NOT.** `grep query_params` inside 4291–11441 = **zero hits.** `turn_intent` is *recomputed* internally via `_classify_turn_intent` (recommend.py:~5937). The extras chat passes as query-string are **ignored.** | We do NOT need to reconstruct a query string. The real inputs are the **typed params**. |
| Must extract the body to call it Depends-free | `suggest()` is a plain **sync `def`** with `redis/role/db = Depends(...)`. A sync def is directly callable if you pass those explicitly. | We can **call `suggest()` as a function** — no extraction of the body at all. |
| Need a synthetic Request | `request` is used for IP, headers, TLS-fp, `emit_security_event(request=...)`. **Chat already holds a real Request** (its own incoming one). | Pass **chat's own request** → the IP/headers/TLS reflect the ACTUAL buyer, which is *more* correct than the loopback's client. |

**Net:** the work is an **adapter that calls `suggest()` in-process**, not a body extraction. Effort drops
from ~half a day + high risk to **~2–3 hours + low risk**, behind a flag with the loopback as fallback.

---

## 1. The seams (every coupling point, mapped)

Inside `suggest()` (recommend.py 4291–11441):

- **`request`** (~20 uses): `request.client.host` (source IP), `request.headers[...]` (x-api-key, X-Tenant-Id,
  x-device-fingerprint, X-Retention-Consent, X-NQE-Template-Variant/Version), `extract_tls_fingerprints_from_request(request)`,
  `emit_security_event(..., request=request)`. → **Satisfied by passing chat's own request.**
- **`response`** (3 uses, ~line 5630): sets `X-Rate-Limit-*` headers on the `Response`. → Pass a fresh
  `Response()`; optionally copy those headers back onto chat's response (nice-to-have, not required).
- **`redis`** (Depends): `Memory(redis)`, `TokenBudget(redis)`, `TenantQuotaGuard(redis)`, `cb_is_open(redis,...)`.
  → Resolve via `from src.app.deps import get_redis; get_redis()`.
- **`db`** (Depends): `RecommendationService(session=db)`, `get_cached_catalog_profile_with_meta(db,...)`,
  `_ctx.deps = {"db": db, ...}`. → Resolve via `get_db_for_request(request)` (models/db.py:1209 —
  takes a request, returns a session).
- **`role`** (Depends): passed to `recommend_action(..., role=role)` and read for member checks.
  → Resolve via `get_role_from_key(api_key)` (security/auth.py — the same resolver `require_role` uses).

There are **no other hidden couplings** — no `query_params`, no request.state writes that suggest depends on
beyond what middleware already populated on chat's request.

---

## 2. Two options

### Option A — In-process ADAPTER (recommended: low risk, ships this week)
Keep `suggest()` byte-for-byte. Add a chat-side adapter that resolves the deps and calls it directly.
The HTTP loopback stays as the fallback. Flag-gated default-OFF until proven.

### Option B — Extract `suggest_core` (higher long-term value, higher risk, post-demo)
Rename the body to `suggest_core(*, uid, query, typed..., http_ctx: HttpCtx, redis, db, role) -> tuple[dict, Headers]`
where `HttpCtx` is a small dataclass of the request-derived values (source_ip, api_key_id, tenant_id,
device_fp, retention_consent, tls_fp, nqe_template_variant/version). The route becomes a 10-line shim that
builds `HttpCtx` from `request` and calls the core; chat builds `HttpCtx` from its own request. This removes
the last `request` coupling and makes the core unit-testable without a Request at all — but it touches the
7,000-line body (every `request.X` → `http_ctx.X`) and wants its own PR + full battery. **Do this later.**

**Recommendation: ship A now, schedule B as a follow-up refactor.** A delivers 100% of the runtime win
(no loopback, no double rate-limit, no 502) with ~5% of the risk. B is a code-cleanliness/testability win.

---

## 3. Option A — the adapter, concretely

### 3.1 Deps resolution (chat side)
```python
def _resolve_suggest_deps(request):
    from src.app.deps import get_redis
    from src.app.models.db import get_db_for_request
    from src.app.security.auth import get_role_from_key
    api_key = request.headers.get("x-api-key") if request else None
    redis = get_redis()
    # get_db_for_request is a GENERATOR (yields the session, closes on exhaustion) — NOT a plain
    # return. Drive it manually and CLOSE it in a finally after suggest() returns.
    db_gen = get_db_for_request(request)
    db = next(db_gen)
    role = get_role_from_key(api_key) or "merchant"   # chat already auth'd; forward the same key
    return redis, db, db_gen, role
# usage:
#   redis, db, db_gen, role = _resolve_suggest_deps(request)
#   try:      data = await asyncio.to_thread(suggest, ..., db=db, ...)
#   finally:  db_gen.close()      # runs the generator's teardown (session.close())
```

### 3.2 Typed-param mapping (chat's `params` dict → suggest kwargs)
Chat currently builds a `params: dict[str,str]`. Map ONLY the params `suggest()` actually accepts (typed),
converting types; ignore the rest (turn_intent etc. are recomputed / ignored):
```python
def _suggest_kwargs_from_params(p: dict) -> dict:
    def _i(k):  # int|None
        try: return int(p[k]) if p.get(k) is not None else None
        except (TypeError, ValueError): return None
    def _b(k):  # bool|None
        v = p.get(k); return None if v is None else str(v).lower() in ("1","true","yes")
    return {
        "budget_max": _i("budget_max"), "budget_min": _i("budget_min"),
        "nqe_question_id": p.get("nqe_question_id"), "nqe_option_id": p.get("nqe_option_id"),
        "nqe_option_label": p.get("nqe_option_label"), "nqe_option_value": p.get("nqe_option_value"),
        "image_labels": p.get("image_labels"), "image_ocr_text": p.get("image_ocr_text"),
        "image_hash": p.get("image_hash"), "image_intent": p.get("image_intent"),
        "image_product_identity": p.get("image_product_identity"), "image_cv_signals": p.get("image_cv_signals"),
        "fast_path": _b("fast_path"), "include_summary": _b("include_summary"),
        "external_research_consent": _b("external_research_consent"),
        "copywriting_enabled": _b("copywriting_enabled"), "copywriting_profile": p.get("copywriting_profile"),
    }
```

### 3.3 The call — CRITICAL: off the event loop
`chat_query` is `async def`; `suggest()` is **sync** and runs the whole recommendation pipeline (seconds).
Calling it directly would **block the event loop** (uvicorn currently offloads the loopback route to a
threadpool for exactly this reason). MUST wrap in `asyncio.to_thread`:
```python
from fastapi import Response as _Resp
async def _call_suggest_inprocess(request, uid, q, params) -> dict:
    redis, db, role = _resolve_suggest_deps(request)
    from src.app.routers.recommend import suggest
    kwargs = _suggest_kwargs_from_params(params)
    # Depends defaults are Depends OBJECTS — every dep MUST be passed explicitly.
    return await asyncio.to_thread(
        suggest, request=request, uid=uid, query=q, response=_Resp(),
        redis=redis, role=role, db=db, **kwargs,
    )
```

### 3.4 Wiring + fallback (keep the safety net)
```python
if _inprocess_enabled():                 # CHAT_INPROCESS_SUGGEST_ENABLED, default OFF
    try:
        data = await _call_suggest_inprocess(request, uid, q, params)
    except Exception as e:
        logger.warning("inprocess suggest failed, falling back to loopback: %s", e)
        data = await _loopback_suggest(...)   # the existing httpx path, extracted to a helper
else:
    data = await _loopback_suggest(...)
```
Everything downstream (`data.get(...)`, the graceful-degrade, evidence-forward) is unchanged — `data`
has the identical shape either way.

---

## 4. Risks & mitigations (the ones that would actually bite)

1. **Event-loop block (HIGH).** Sync `suggest()` in an async handler freezes the loop. → `asyncio.to_thread`
   (mandatory). Verify concurrency doesn't regress under a 5-way parallel probe.
2. **Depends defaults (HIGH, silent).** Forgetting to pass `redis`/`db`/`role` → the param equals a
   `Depends()` object, not a value → `AttributeError` deep inside. → Pass all three explicitly; a test with
   a real request catches it.
3. **DB session lifecycle (MED).** `get_db_for_request` may be a generator/context-managed session. Confirm
   it returns a usable session and is closed after (the loopback closed it via request teardown; in-process
   we own it). → Inspect models/db.py:1209; wrap in try/finally close if needed.
4. **Double rate-limit REMOVED (positive).** Today the loopback is a *second* request that hits middleware
   rate-limiting again — the buyer is charged twice. In-process fixes this. Note it; don't be surprised when
   quota counters drop.
5. **Response headers dropped (LOW).** `X-Rate-Limit-*` set on the throwaway `Response()` won't reach the
   buyer. Acceptable; copy them onto chat's response only if the storefront reads them.
6. **Recursion (NONE, verified).** `suggest()` never calls chat; no re-entrancy.

---

## 5. Test plan
- **Contract unchanged:** `tests/integration/test_chat_recommend_integration.py` + multimodal + budget-bounds
  must pass with the flag ON and OFF (same shape).
- **New — parity:** `test_chat_inprocess_matches_loopback`: same query through both paths → assert the
  buyer-visible fields (`assistant_message` phrases, `products` count, `evidence.selected`, `decision_trace_id`
  present) match. This is also the guard for the §5-lesson (message-builder drift).
- **New — deps:** a request-bearing test that the in-process call resolves redis/db/role and returns 200
  (catches the Depends-default trap).
- **New — concurrency:** 5 parallel in-process calls complete without loop starvation (proves `to_thread`).
- **Battery + chat suites green** on the branch before merge.

---

## 6. Sequence & effort (Option A)
1. Extract the existing httpx block into `_loopback_suggest(...)` helper (pure move, no behavior change). — 20m
2. Add `_resolve_suggest_deps`, `_suggest_kwargs_from_params`, `_call_suggest_inprocess`. — 45m
3. Gate at the call site with `CHAT_INPROCESS_SUGGEST_ENABLED` + fallback. — 15m
4. Tests (parity, deps, concurrency). — 60m
5. Run battery + chat suites; flip flag ON in a scratch env; live `/chat` sweep (VRAM defense + evidence). — 30m
**Total ≈ 2.5–3 h, low risk, reversible (flag).**

---

## 7. Why bother (the payoff)
- **Latency:** removes a full HTTP round-trip + JSON serialize/deserialize per buyer turn.
- **Correctness:** the 502-class disappears at the *source* (no hop to fail); the graceful-degrade (N7 v1)
  becomes a belt-and-suspenders for genuine pipeline errors, not loopback flakiness.
- **Double-charging fixed:** one rate-limit/quota decrement per turn, not two.
- **Truer telemetry:** IP/TLS/device-fp reflect the real buyer request, not `127.0.0.1`.

Keep `_loopback_suggest` in the tree even after the flag defaults ON — it's a zero-cost fallback and the
only thing that made `/chat` testable under TestClient (which can't reach the loopback).
