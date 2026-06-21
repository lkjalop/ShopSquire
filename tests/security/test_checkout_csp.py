"""B3 — payment-page CSP + script inventory + tamper reporting (PCI DSS 6.4.3 / 11.6.1).

The server-rendered /ui/checkout page must ship a STRICT Content-Security-Policy that authorizes
exactly self + Stripe (the only scripts on the page), nonce its inline bootstrap, and report
violations to the CSP-report sink so an injected skimmer is blocked AND detected.
"""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from src.app.main import app
from src.app.security.headers import PAYMENT_PAGE_SCRIPT_INVENTORY, payment_page_csp

client = TestClient(app)


# ── payment_page_csp helper ──
def test_payment_csp_authorizes_only_self_and_stripe():
    csp = payment_page_csp("abc123")
    script = next(p for p in csp.split(";") if p.strip().startswith("script-src"))
    assert "'self'" in script and "'nonce-abc123'" in script and "https://js.stripe.com" in script
    assert "'unsafe-inline'" not in script  # no unsafe-inline for scripts (e-skimming control)
    assert "*" not in script                # no wildcard origins
    assert "report-uri /api/v1/security/csp-report" in csp
    assert "frame-src https://js.stripe.com" in csp


def test_script_inventory_documents_stripe_and_inline():
    srcs = [s["src"] for s in PAYMENT_PAGE_SCRIPT_INVENTORY]
    assert any("js.stripe.com" in s for s in srcs)
    assert any("inline" in s for s in srcs)
    # Stripe entry documents WHY it has no SRI.
    stripe = next(s for s in PAYMENT_PAGE_SCRIPT_INVENTORY if "stripe" in s["src"])
    assert "SRI" in stripe["integrity"] or "origin-pinned" in stripe["integrity"]


# ── live checkout page ──
def test_checkout_sets_strict_csp_header_and_nonced_inline_script():
    r = client.get("/ui/checkout")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy") or ""
    assert "https://js.stripe.com" in csp
    script_dir = next((p for p in csp.split(";") if p.strip().startswith("script-src")), "")
    assert "'unsafe-inline'" not in script_dir  # the global default would allow none; payment page locks to nonce+stripe
    m = re.search(r"'nonce-([A-Za-z0-9_-]+)'", csp)
    assert m, f"no nonce in CSP: {csp}"
    nonce = m.group(1)
    # The inline bootstrap script must carry the SAME nonce (else the browser blocks it).
    assert f"<script nonce='{nonce}'>" in r.text


def test_checkout_nonce_is_per_response():
    a = client.get("/ui/checkout").headers.get("content-security-policy") or ""
    b = client.get("/ui/checkout").headers.get("content-security-policy") or ""
    na = re.search(r"'nonce-([A-Za-z0-9_-]+)'", a).group(1)
    nb = re.search(r"'nonce-([A-Za-z0-9_-]+)'", b).group(1)
    assert na != nb  # fresh nonce each render (no replayable inline-script allowance)


# ── CSP-report tamper sink (11.6.1) ──
def test_csp_report_endpoint_accepts_violation_and_returns_204():
    report = {"csp-report": {
        "document-uri": "https://shop.example.com/ui/checkout",
        "violated-directive": "script-src",
        "blocked-uri": "https://evil-skimmer.example.com/x.js",
    }}
    r = client.post("/api/v1/security/csp-report", json=report)
    assert r.status_code == 204  # accepted (unauthenticated, by design)


def test_csp_report_tolerates_garbage():
    assert client.post("/api/v1/security/csp-report", content=b"not json").status_code == 204
