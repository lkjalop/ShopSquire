"""Swap-rate battery (2026-07-09) — the live regression guard for "does model prose reach the buyer".

Froze after two mute failures this project: the 7 code layers (bb4cd0a) and the 8th operational
layer (DummyRedis silently dropped async jobs → poll pending forever, 07c98f4). This asserts the
brain is ON end-to-end: hard queries produce a narration job whose async result SWAPS IN with
guarded prose, and the correct-by-design no-job queries stay deterministic. Skips when :8080 is
down. Requires the model warm (a cold load times out the first swap)."""
from __future__ import annotations

import time

import pytest


def _backend_up() -> bool:
    try:
        import httpx
        return httpx.get("http://127.0.0.1:8080/healthz", timeout=3).status_code == 200
    except Exception:
        return False


live = pytest.mark.skipif(not _backend_up(), reason="backend :8080 not running")


def _chat(q: str, uid: str) -> dict:
    import httpx
    from tests.utils import default_headers
    H = {**default_headers(), "Content-Type": "application/json"}
    return httpx.Client(timeout=90).post("http://127.0.0.1:8080/api/v1/chat/query",
                                         headers=H, json={"uid": uid, "query": q}).json()


def _swap_outcome(b: dict) -> tuple:
    """(outcome, storage_backend, prose) — polls the async job to a terminal state."""
    import httpx
    from tests.utils import default_headers
    H = default_headers()
    job = b.get("llm_summary_job_id")
    if not job:
        return "no_job", None, ""
    c = httpx.Client(timeout=90)
    for _ in range(28):
        time.sleep(1.25)
        nd = c.get(f"http://127.0.0.1:8080/api/v1/recommend/narration/{job}", headers=H).json()
        if nd.get("status") in ("done", "error"):
            if nd.get("assistant_message"):
                return "prose_swap", nd.get("storage_backend"), nd.get("assistant_message") or ""
            if nd.get("guard") == "rejected":
                return "guard_rejected", nd.get("storage_backend"), ""
            if nd.get("guard") == "error":
                return "guard_error", nd.get("storage_backend"), ""
            return nd.get("status"), nd.get("storage_backend"), ""
    return "pending_timeout", None, ""


# PX0 (GPT-5.5 #1/#4, 2026-07-10): the swap-rate battery checked OUTCOME but never CONTENT — it
# passed prose that talked about "Hand Sanitiser / Paracetamol" and leaked raw "[1]" labels. Any
# prose that reaches the buyer must be free of foreign-category noise AND catalog-label leakage.
_CONTAMINANTS = ("hand saniti", "paracetamol", "sanitiser", "wi-fi extend", "wifi extend",
                 "laptop bag", "folio", "[1]", "[2]", "[3]")


def _assert_clean_prose(prose: str, name: str) -> None:
    low = (prose or "").lower()
    hits = [t for t in _CONTAMINANTS if t in low]
    assert not hits, f"{name}: prose leaked {hits} — narration snapshot not final/dereferenced"


# Queries that have real products and MUST reach the buyer with guarded model prose.
_PROSE_QUERIES = [
    ("fit_conflict", "i need something for training llm models, is 3500 enough? if i go higher what then?"),
    ("knowledge", "what's the real difference between an 8gb and 16gb gpu for AI work?"),
    ("game_fit", "gaming laptop for valorant under 1900"),
    ("payment", "i want to spend around 25000 on machines for my team — do you offer payment plans?"),
    ("budget_yn", "is 1800 enough for gaming?"),
]

# Queries that MUST stay deterministic (correct-by-design: honesty / suppression / ACL).
# ai_honesty: the fine-tune query has ZERO in-catalog products meeting AI floors after cleanup,
# so the honest outcome is the deterministic no-match — NOT prose narrated over dropped items
# (the GPT-5.5 #1 bug: it used to swap prose about pharmacy products).
_NO_JOB_QUERIES = [
    ("off_catalog", "i need 5 rack-mount GPU servers with A100s, budget 80k"),
    ("contradiction", "i need 12 dell laptops and a monitor and 2 headsets under 1500 total"),
    ("ai_honesty", "i want to fine tune a 7b model locally under 2500"),
]


@live
@pytest.mark.parametrize("name,q", _PROSE_QUERIES)
def test_hard_query_reaches_buyer_with_prose(name, q):
    outcome, backend, prose = _swap_outcome(_chat(q, f"swaprate-{name}"))
    # never the silent-mute failure modes:
    assert outcome != "pending_timeout", "async job never resolved — job store broken (8th mute layer)"
    assert outcome != "guard_error", "guard crashed (must fail-closed, not error)"
    # the brain must actually speak on these:
    assert outcome == "prose_swap", f"{name}: expected guarded prose to reach the buyer, got {outcome}"
    assert backend in ("memory", "redis"), f"missing storage_backend telemetry ({backend})"
    _assert_clean_prose(prose, name)  # PX0: content, not just outcome


@live
@pytest.mark.parametrize("name,q", _NO_JOB_QUERIES)
def test_correct_by_design_stays_deterministic(name, q):
    outcome, _, prose = _swap_outcome(_chat(q, f"swaprate-{name}"))
    # no prose reaches the buyer: no_job (suppressed), guard_rejected, or done-empty (summarizer
    # returned nothing over 0 final products) — the deterministic honest answer always stands.
    assert outcome in ("no_job", "guard_rejected", "done"), \
        f"{name}: must stay deterministic (honesty/suppression), got {outcome}"
    _assert_clean_prose(prose, name)


@live
def test_off_catalog_returns_no_laptops():
    b = _chat("i need 5 rack-mount GPU servers with A100s, budget 80k", "swaprate-a100")
    assert not (b.get("products") or []), "off-catalog must not sell laptops"


@live
def test_ai_query_returns_no_accessory_noise():
    # the fine-tune query must NOT return a Wi-Fi extender / laptop bag (accessory bleed)
    b = _chat("i want to fine tune a 7b model locally under 2500", "swaprate-noacc")
    names = " ".join((p.get("name") or "") for p in (b.get("products") or [])).lower()
    assert "wi-fi" not in names and "extender" not in names and "folio" not in names and "brief" not in names
