"""ComplianceMiddleware body replay — the PAN scan on /api/v1/payments POSTs consumes the ASGI
receive channel; downstream MUST get the buffered body replayed. The original implementation
never replayed it, so EVERY customer payment POST with a JSON body hung at body parse until the
client timed out (found live: checkout-initiate 58s -> 400). The 422 PAN block must survive."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.app.security.compliance import ComplianceMiddleware


class _Body(BaseModel):
    amount_cents: int = 0
    note: str | None = None


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ComplianceMiddleware)

    @app.post("/api/v1/payments/echo")
    def echo(body: _Body):
        return {"echo": body.amount_cents}

    @app.post("/api/v1/other/echo")
    def other(body: _Body):
        return {"echo": body.amount_cents}

    return app


def test_clean_payment_body_is_replayed_not_swallowed():
    c = TestClient(_app())
    r = c.post("/api/v1/payments/echo", json={"amount_cents": 1000})
    assert r.status_code == 200 and r.json() == {"echo": 1000}


def test_pan_in_payment_body_still_blocked_422():
    c = TestClient(_app())
    r = c.post("/api/v1/payments/echo",
               json={"amount_cents": 1, "note": "card 4111 1111 1111 1111 cvv 123 exp 12/27"})
    assert r.status_code == 422
    assert r.json().get("detail") == "pci_data_detected"


def test_non_payment_paths_untouched():
    c = TestClient(_app())
    r = c.post("/api/v1/other/echo", json={"amount_cents": 7})
    assert r.status_code == 200 and r.json() == {"echo": 7}
