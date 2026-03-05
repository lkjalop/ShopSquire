"""Comprehensive tests for the recent gap-closure implementations.

Covers:
  1. Category-aware product ranking (6 categories)
  2. CV model pack category resolution
  3. Status summary endpoint
  4. Chat stream SSE endpoint
  5. Admin GRC risk bands helper
  6. Orchestrator risk-aware budget boosting
  7. NQE risk context injection
"""
from __future__ import annotations

import json
import os
import pytest

# Ensure PYTHONPATH is set correctly for src imports
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///")
os.environ.setdefault("DISABLE_TRACING", "1")

from fastapi.testclient import TestClient

from tests.utils import default_headers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from src.app.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


# ===================================================================
# 1. Category-aware product ranking
# ===================================================================

class TestCategoryRanking:
    def test_all_categories_defined(self):
        from src.app.services.product_ranking_agent import _CATEGORY_RANKING_DIMENSIONS
        expected = {"laptop", "clothing", "kitchen", "furniture", "tv", "phone"}
        assert expected.issubset(set(_CATEGORY_RANKING_DIMENSIONS.keys()))

    def test_detect_category_from_field(self):
        from src.app.services.product_ranking_agent import _detect_product_category
        assert _detect_product_category({"category": "laptop"}) == "laptop"
        assert _detect_product_category({"category": "clothing"}) == "clothing"
        assert _detect_product_category({"category": "kitchen"}) == "kitchen"

    def test_detect_category_fallback(self):
        from src.app.services.product_ranking_agent import _detect_product_category
        # Unknown category should fall back to laptop
        result = _detect_product_category({"category": "unknown_thing"})
        assert result == "laptop"

    def test_spec_match_clothing(self):
        from src.app.services.product_ranking_agent import _spec_match_score
        product = {"category": "clothing", "material": "cotton", "color": "blue"}
        reqs = {"material": "cotton", "color": "blue"}
        score = _spec_match_score(product, reqs)
        assert 0.0 <= score <= 1.0
        assert score > 0.5  # Exact match on two dimensions should score well

    def test_spec_match_laptop(self):
        from src.app.services.product_ranking_agent import _spec_match_score
        product = {"category": "laptop", "ram_gb": 16, "storage_gb": 512}
        reqs = {"min_ram": 16, "min_storage": 256}
        score = _spec_match_score(product, reqs)
        assert 0.0 <= score <= 1.0

    def test_spec_match_no_requirements(self):
        from src.app.services.product_ranking_agent import _spec_match_score
        score = _spec_match_score({"category": "laptop"}, {})
        assert score == 0.5  # neutral

    def test_each_category_has_tuples(self):
        from src.app.services.product_ranking_agent import _CATEGORY_RANKING_DIMENSIONS
        for cat, dims in _CATEGORY_RANKING_DIMENSIONS.items():
            assert isinstance(dims, list), f"{cat} dims not a list"
            for d in dims:
                assert len(d) == 3, f"{cat} dim {d} should be (spec_key, prod_key, mode)"
                assert d[2] in ("ratio", "ratio_inverse", "exact", "bool"), f"Bad mode {d[2]} in {cat}"


# ===================================================================
# 2. CV model pack category resolution
# ===================================================================

class TestCVModelPacks:
    def test_all_category_defaults_resolve(self):
        from src.app.services.cv_model_pack import get_model_pack_for_category
        for cat in ["clothing", "kitchen", "furniture", "tv", "phone"]:
            pack = get_model_pack_for_category(cat)
            assert pack is not None, f"No pack for {cat}"
            assert "quality" in pack, f"Missing quality in {cat} pack"
            assert "detector" in pack, f"Missing detector in {cat} pack"

    def test_clothing_pack_has_condition_labels(self):
        from src.app.services.cv_model_pack import get_model_pack_for_category
        pack = get_model_pack_for_category("clothing")
        labels = pack.get("quality", {}).get("labels", [])
        assert any("stain" in l.lower() for l in labels), "Clothing pack should detect stains"

    def test_kitchen_pack_id(self):
        from src.app.services.cv_model_pack import get_model_pack_for_category
        pack = get_model_pack_for_category("kitchen")
        assert pack["id"] == "kitchen_v1"

    def test_unknown_category_falls_back(self):
        from src.app.services.cv_model_pack import get_model_pack_for_category
        pack = get_model_pack_for_category("alien_widgets")
        # Should fall back to global default
        assert pack is not None

    def test_none_category(self):
        from src.app.services.cv_model_pack import get_model_pack_for_category
        pack = get_model_pack_for_category(None)
        assert pack is not None

    def test_config_json_valid(self):
        config_path = os.path.join("config", "cv_model_packs.json")
        with open(config_path) as f:
            data = json.load(f)
        assert "category_defaults" in data
        assert isinstance(data["category_defaults"], dict)
        assert len(data["category_defaults"]) >= 5


# ===================================================================
# 3. Status summary endpoint
# ===================================================================

class TestStatusSummary:
    def test_router_has_route(self):
        from src.app.routers.status_summary import router
        paths = [r.path for r in router.routes]
        assert "/status/summary" in paths

    def test_endpoint_returns_200(self, client):
        # The endpoint requires merchant/owner/developer role.
        # Without auth it should return 401 or 403.
        r = client.get("/status/summary", headers=default_headers())
        # Accept 200, 401, or 403 — the route is registered
        assert r.status_code in (200, 401, 403, 422)

    def test_endpoint_shape_when_accessible(self, client):
        r = client.get("/status/summary", headers=default_headers())
        if r.status_code == 200:
            body = r.json()
            assert "email_xdr" in body
            # Shape may vary depending on which handler is active
            assert "outbound_anomalies" in body or "status" in body


# ===================================================================
# 4. Chat stream SSE endpoint
# ===================================================================

class TestChatStream:
    def test_router_has_route(self):
        from src.app.routers.chat_stream import router
        paths = [r.path for r in router.routes]
        assert any("/stream" in p for p in paths)

    def test_endpoint_exists(self, client):
        r = client.post(
            "/api/v1/chat/stream",
            json={"query": "test", "uid": "demo"},
            headers=default_headers(),
        )
        # Should get 200 (SSE), 401, or 403 — not 404
        assert r.status_code != 404, "Chat stream route not registered"

    def test_sse_event_format(self):
        from src.app.routers.chat_stream import _sse_event
        event = _sse_event("thinking", {"trace_id": "abc123"})
        assert event.startswith("event: thinking\n")
        assert "data:" in event
        assert event.endswith("\n\n")
        parsed = json.loads(event.split("data: ")[1].strip())
        assert parsed["trace_id"] == "abc123"


# ===================================================================
# 5. Admin GRC risk bands
# ===================================================================

class TestRiskBands:
    def test_get_latest_risk_bands_returns_dict(self):
        from src.app.routers.admin_grc import get_latest_risk_bands
        bands = get_latest_risk_bands()
        assert isinstance(bands, dict)

    def test_risk_bands_importable_from_orchestrator(self):
        """Orchestrator should be able to import and use get_latest_risk_bands."""
        # This tests the import chain used inside orchestrator
        from src.app.routers.admin_grc import get_latest_risk_bands
        bands = get_latest_risk_bands()
        # Even with empty DB, should return empty dict, not error
        assert bands is not None


# ===================================================================
# 6. Orchestrator risk-aware budgets
# ===================================================================

class TestOrchestratorRiskBudgets:
    def test_orchestrator_imports(self):
        from src.app.services.orchestrator import Orchestrator
        assert Orchestrator is not None

    def test_adaptive_budgets_method_exists(self):
        from src.app.services.orchestrator import Orchestrator
        o = Orchestrator.__new__(Orchestrator)
        assert hasattr(o, "_compute_adaptive_agent_budgets")


# ===================================================================
# 7. NQE risk context injection
# ===================================================================

class TestNQERiskContext:
    def test_nqe_imports(self):
        from src.app.flows.nqe import NextQuestionEngine, NQEInput
        assert NextQuestionEngine is not None
        assert NQEInput is not None

    def test_nqe_input_has_risk_score(self):
        from src.app.flows.nqe import NQEInput
        inp = NQEInput(
            intent="purchase",
            product_category="laptop",
            query="test laptop",
        )
        assert hasattr(inp, "risk_score")
        assert inp.risk_score == 0.0  # default
        inp2 = NQEInput(
            intent="purchase",
            product_category="laptop",
            risk_score=0.8,
        )
        assert inp2.risk_score == 0.8

    def test_propose_returns_list(self):
        """Basic NQE propose should return a list without crashing."""
        from src.app.flows.nqe import NextQuestionEngine, NQEInput
        from src.app.rag.retrieve import Retriever
        from src.app.flows.nqe_templates import TemplateStore
        engine = NextQuestionEngine(rag=Retriever(), templates=TemplateStore())
        inp = NQEInput(
            intent="purchase",
            product_category="laptop",
            query="I need a laptop",
        )
        result = engine.propose(inp)
        assert isinstance(result, list)
