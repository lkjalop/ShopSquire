"""PCI DSS 6.4.3 drift guard — the strict payment-page CSP and the documented script inventory must
stay coherent. If a script origin is added to one without the other, an authorized-script gap opens
(skimmer can't be told apart from a legit addition). This test fails the build on that drift.

Also asserts 11.6.1 hooks: the CSP is strict (no 'unsafe-inline' in script-src), nonce-bound, and
reports violations to the tamper-detection sink.
"""
from __future__ import annotations

import re

from src.app.security.headers import payment_page_csp, PAYMENT_PAGE_SCRIPT_INVENTORY


def _https_origins(text: str) -> set[str]:
    return {m.group(0).rstrip("/") for m in re.finditer(r"https://[^\s;']+", text)}


def _origin(url: str) -> str | None:
    m = re.match(r"(https://[^/]+)", str(url or ""))
    return m.group(1) if m else None


def _script_src(csp: str) -> str:
    m = re.search(r"script-src ([^;]+)", csp)
    assert m, f"payment CSP has no script-src directive: {csp}"
    return m.group(1)


def test_payment_csp_script_origins_match_inventory():
    csp = payment_page_csp("test-nonce")
    csp_origins = _https_origins(_script_src(csp))
    inv_origins = {
        _origin(item.get("src", ""))
        for item in PAYMENT_PAGE_SCRIPT_INVENTORY
        if str(item.get("src", "")).startswith("https://")
    }
    inv_origins.discard(None)
    assert csp_origins == inv_origins, (
        f"PCI 6.4.3 drift: payment CSP script-src origins {sorted(csp_origins)} != documented "
        f"inventory origins {sorted(inv_origins)}. Update BOTH headers.payment_page_csp AND "
        f"PAYMENT_PAGE_SCRIPT_INVENTORY together when a payment-page script changes."
    )


def test_payment_csp_is_strict_and_reports():
    csp = payment_page_csp("n0nce")
    src = _script_src(csp)
    assert "'unsafe-inline'" not in src, "payment CSP script-src must not allow unsafe-inline"
    assert "*" not in src, "payment CSP script-src must not use a wildcard"
    assert "'nonce-n0nce'" in src, "payment CSP must bind the inline bootstrap to a per-response nonce"
    assert "report-uri /api/v1/security/csp-report" in csp, "payment CSP must report to the 11.6.1 tamper sink"


def test_inventory_documents_every_external_script():
    # Every non-'self' script origin the CSP authorizes must have an inventory entry with a purpose.
    for item in PAYMENT_PAGE_SCRIPT_INVENTORY:
        assert str(item.get("purpose") or "").strip(), f"inventory entry missing purpose: {item}"
        assert str(item.get("owner") or "").strip(), f"inventory entry missing owner: {item}"
