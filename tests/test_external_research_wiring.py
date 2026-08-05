"""External research compatibility transport after the V2 cutover.

The deprecated endpoint carries explicit per-turn consent into V2. It no longer
owns or fabricates the retired V1 ``external_research`` result surface.
"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from src.app.main import app
from tests.utils import default_headers

# Use the owner test credential and per-test UIDs so this module's quota does not
# depend on unrelated guest requests. Older supported Starlette TestClient
# versions do not accept the newer ``client=`` constructor argument.
_headers = default_headers()
_headers["x-api-key"] = os.getenv("OWNER_API_KEY", "local-owner-key")
client = TestClient(app, headers=_headers)


def _suggest(uid, **params):
    response = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "gaming laptop under 1800", **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_disabled_by_default_no_external_field(monkeypatch):
    from src.app.routers import recommend_compat

    monkeypatch.setattr(
        recommend_compat,
        "serve_v2_compatibility",
        lambda **_: {
            "assistant_message": "V2 compatibility response",
            "results": [{"sku": "OWNED-1"}],
            "evidence_items": [],
        },
    )
    body = _suggest("u-ext-off")
    assert "external_research" not in body
    assert "external_research_status" not in body
    assert "results" in body


def test_explicit_consent_is_forwarded_without_restoring_v1_authority(monkeypatch):
    from src.app.routers import recommend_compat

    captured = {}

    def fake_v2_compatibility(*, request, params, redis, db, role):
        captured.update(params)
        return {
            "assistant_message": "V2 compatibility response",
            "results": [{"sku": "OWNED-1"}],
            "evidence_items": [],
        }

    monkeypatch.setattr(
        recommend_compat,
        "serve_v2_compatibility",
        fake_v2_compatibility,
    )
    body = _suggest("u-ext-on", external_research_consent="true")

    assert captured["external_research_consent"] is True
    assert body["results"] == [{"sku": "OWNED-1"}]
    assert body["evidence_items"] == []
    assert "external_research" not in body
    assert "external_research_status" not in body
