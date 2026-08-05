from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


def test_material_questions_precede_generic_procurement_discovery():
    from src.app.services.recommendation_compatibility import (
        _append_generic_procurement_question,
    )

    questions = _append_generic_procurement_question([
        {"id": "budget_scope", "label": "Per item or total?"},
    ])

    assert [question["id"] for question in questions] == [
        "budget_scope",
        "ask_b2b_procurement",
    ]


def test_compatibility_route_is_deprecated_and_v2_backed(monkeypatch):
    from src.app.routers import recommend_compat

    captured = {}

    def _serve(**kwargs):
        captured.update(kwargs)
        return {"trace_id": "trace-v2", "products": [], "results": []}

    monkeypatch.setattr(recommend_compat, "serve_v2_compatibility", _serve)
    response = TestClient(create_app(), headers=default_headers()).get(
        "/api/v1/recommend/suggest",
        params={"uid": "compat-user", "query": "a laptop"},
    )

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == "Wed, 30 Sep 2026 00:00:00 GMT"
    assert response.headers["X-Recommendation-Engine"] == "v2-compatibility"
    assert captured["params"]["uid"] == "compat-user"
    assert captured["params"]["query"] == "a laptop"


def test_compatibility_route_is_marked_deprecated_in_openapi():
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/recommend/suggest"]["get"]
    assert operation["deprecated"] is True
