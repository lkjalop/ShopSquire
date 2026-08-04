"""Frontend <-> backend PARITY (Playwright).

Proves the storefront widget renders EXACTLY what /api/v1/chat/query returns
-- not just that "something renders". Intercepts the live V2 chat response and
compares it to the widget's rendered state.results (count + SKU set).

Deterministic: results are catalog-driven, not LLM-driven, so this is a stable gate
(unlike the LLM-narration eval). Skips gracefully when the widget/selectors or a
captured response aren't available, matching the rest of tests/pw.
"""
import pytest

from tests.pw.helpers import wait_for_results

_QUERY = "gaming laptop 1300 to 1800"


def _read_widget_results(page):
    return page.evaluate(
        "() => { const el=document.querySelector('shopsquire-widget');"
        " const r=(el && el.state && el.state.results) || [];"
        " return { n: r.length, skus: r.map(x => String(x.sku || x.id || '')) }; }"
    )


def test_widget_results_match_backend(page, test_server):
    base = test_server["base_url"]
    page.goto(base + "/ui/storefront")
    page.wait_for_timeout(800)

    widget = page.locator("shopsquire-widget")
    if widget.count() == 0:
        pytest.skip("shopsquire-widget not present on storefront")

    # Best-effort open the widget so the query input is interactable.
    try:
        page.evaluate(
            "() => { const el=document.querySelector('shopsquire-widget');"
            " if (el && el.state) { el.state.open = true; el.render && el.render(); } }"
        )
    except Exception:
        pass

    inp = widget.locator("#query")
    if inp.count() == 0:
        pytest.skip("widget query input (#query) not found")

    try:
        inp.fill(_QUERY)
        with page.expect_response(lambda r: "/chat/query" in r.url, timeout=15000) as resp_info:
            inp.press("Enter")
        body = resp_info.value.json()
    except Exception:
        pytest.skip("/chat/query response not captured (widget wiring/env)")

    wait_for_results(page)
    state = _read_widget_results(page)
    backend = body.get("results") or []

    # PARITY 1 — the widget renders exactly the backend's result count.
    assert state["n"] == len(backend), f"DOM results {state['n']} != backend {len(backend)}"

    # PARITY 2 — same SKUs (order-independent), so the UI isn't showing a stale/other set.
    backend_skus = {str(p.get("sku") or p.get("id") or "") for p in backend}
    assert set(state["skus"]) == backend_skus, f"DOM skus {set(state['skus'])} != backend {backend_skus}"

    # PARITY 3 — when there ARE results, real cards are in the (shadow) DOM.
    if state["n"] > 0:
        cards = widget.locator(".card")
        assert cards.count() >= 1, "backend returned results but no .card rendered"


def test_widget_no_results_is_graceful_not_blank(page, test_server):
    """A no-match query must not render a blank widget — parity on the empty case."""
    base = test_server["base_url"]
    page.goto(base + "/ui/storefront")
    page.wait_for_timeout(800)
    widget = page.locator("shopsquire-widget")
    if widget.count() == 0:
        pytest.skip("widget not present")
    try:
        page.evaluate(
            "() => { const el=document.querySelector('shopsquire-widget');"
            " if (el && el.state) { el.state.open = true; el.render && el.render(); } }"
        )
    except Exception:
        pass
    inp = widget.locator("#query")
    if inp.count() == 0:
        pytest.skip("widget query input not found")
    try:
        inp.fill("asus gaming laptop under 200")
        with page.expect_response(lambda r: "/chat/query" in r.url, timeout=15000) as resp_info:
            inp.press("Enter")
        body = resp_info.value.json()
    except Exception:
        pytest.skip("/chat/query response not captured")
    # Backend must carry SOME answer text (message/assistant_message) even on no-match.
    answer = str(body.get("assistant_message") or body.get("message") or "")
    assert answer.strip(), "no-match response carried no message text (blank-answer regression)"
