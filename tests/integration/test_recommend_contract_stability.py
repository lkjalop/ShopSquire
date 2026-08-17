"""Golden contract-stability test for `suggest()` — the safety net required by
docs/refactor/OPEN_BLOCKERS.md §8 BEFORE any phase-as-stage bulk extraction
(F1 Constraint Engine / F2 Retriever / F3 Narration).

It does NOT assert response *values* (those depend on the LLM, seed data and
ranking — flaky). It asserts the response *contract*: the stable top-level key
spine present on every turn, plus the per-shape keys the frontend consumes
(docs/refactor/OPEN_BLOCKERS.md §8 lists the 7 UI-critical fields).

If a future extraction drops, renames, or moves one of these keys, this test
goes red — which is the whole point. An *intentional* contract change updates
the expected sets below in the same PR.

Coverage today: success, zero-results, off-domain, support, open-ended/NQE.
TODO (roadmap §8): image-match and security-block shapes are not reliably
reachable via a plain GET in the test harness; see the skipped placeholders.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.recommendation_response_finalizer import finalize_core_response
from src.app.services.taxonomy_registry import (
    add_sold_node,
    ensure_tables,
    upsert_classification,
)
from tests.utils import default_headers

_CONTRACT_SKU = "V2-CONTRACT-LAP-1"
_CONTRACT_NODES = ("el-6-6", "el-6-11-2")


@pytest.fixture(autouse=True)
def _ground_v2_contract_catalog(monkeypatch):
    """Ground after the function-scoped migrated-database reset."""
    # Contract-shape certification must not silently become a live Ollama benchmark.
    # Provider latency is certified separately with explicit receipts and deadlines.
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    monkeypatch.setenv("ROUTER_MODEL_ENABLED", "0")
    monkeypatch.setenv("SKIP_OBSERVER_ENDPOINTS", "/api/v1/recommend")
    # Shape compatibility is neither a provider benchmark nor an audit-store
    # durability benchmark.  Those boundaries have their own focused suites.
    monkeypatch.setattr(
        "src.app.services.recommendation_response_finalizer.log_decision",
        lambda **_kwargs: "contract-shape-trace",
    )
    with db_session() as db:
        ensure_tables(db)
        existing_nodes = {
            node: bool(
                db.execute(
                    text(
                        "SELECT 1 FROM sold_taxonomy "
                        "WHERE tenant_id = 'default' AND node_handle = :node"
                    ),
                    {"node": node},
                ).first()
            )
            for node in _CONTRACT_NODES
        }
        for node in _CONTRACT_NODES:
            add_sold_node(db, node_handle=node, tenant_id="default")
        db.execute(
            text(
                "INSERT OR REPLACE INTO products "
                "(id, sku, name, price_cents, currency, specs, active) "
                "VALUES (:sku, :sku, 'Grounded Gaming Laptop', 149900, "
                "'AUD', :specs, 1)"
            ),
            {
                "sku": _CONTRACT_SKU,
                "specs": '{"ram_gb": 16, "storage_gb": 1024, "gaming_style": true}',
            },
        )
        db.execute(
            text(
                "INSERT OR REPLACE INTO inventory "
                "(id, product_id, stock, warehouse) "
                "VALUES (:id, :sku, 8, 'default')"
            ),
            {"id": f"inv-{_CONTRACT_SKU}", "sku": _CONTRACT_SKU},
        )
        upsert_classification(
            db,
            sku=_CONTRACT_SKU,
            node_handle="el-6-11-2",
            source="v2_contract_fixture",
            status="approved",
            tenant_id="default",
        )
        db.commit()
    yield
    with db_session() as db:
        db.execute(
            text(
                "DELETE FROM product_classification "
                "WHERE tenant_id = 'default' AND sku = :sku "
                "AND source = 'v2_contract_fixture'"
            ),
            {"sku": _CONTRACT_SKU},
        )
        db.execute(
            text("DELETE FROM inventory WHERE product_id = :sku"),
            {"sku": _CONTRACT_SKU},
        )
        db.execute(
            text("DELETE FROM products WHERE id = :sku"),
            {"sku": _CONTRACT_SKU},
        )
        for node, existed in existing_nodes.items():
            if not existed:
                db.execute(
                    text(
                        "DELETE FROM sold_taxonomy "
                        "WHERE tenant_id = 'default' AND node_handle = :node"
                    ),
                    {"node": node},
                )
        db.commit()


def _suggest(uid: str, query: str) -> dict:
    client = TestClient(create_app(), headers=default_headers())
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": query})
    assert r.status_code == 200, f"{uid}: HTTP {r.status_code} — {r.text[:300]}"
    body = r.json()
    assert isinstance(body, dict), f"{uid}: body is {type(body).__name__}, expected dict"
    return body


# The contract spine: keys present on EVERY suggest() turn regardless of shape.
# Includes 4 of the 7 frontend-critical fields (buyer_persona, decision_trace_id,
# evidence_items, memory_confidence). The other 3 are shape-specific (below).
_SPINE = frozenset(
    {
        "agent_chain",
        "ambiguity_reason",
        "buyer_persona",
        "buyer_persona_candidate",
        "buyer_persona_confidence",
        "complexity_signals",
        "confidence_band",
        "confidence_calibrated",
        "constraints_used",
        "counterfactual",
        "decision_id",
        "decision_trace_id",
        "evidence_items",
        "evidence_weighting",
        "followup_contract",
        "intent_execution_plan",
        "llm_model",
        "memory_confidence",
        "model_tier",
        "needs_disambiguation",
        "policy_version",
        "proposal",
        "question_plan",
        "referents",
        "results",
        "trace_id",
        "turn_type",
        "view_mode",
        "view_reason",
    }
)


def _assert_spine(body: dict, label: str) -> None:
    missing = _SPINE - body.keys()
    assert not missing, f"{label}: contract spine missing keys {sorted(missing)}"
    assert isinstance(body["results"], list), f"{label}: results must be a list"


def test_spine_present_on_every_shape():
    """Every reachable shape carries the full contract spine."""
    for label, query in (
        ("success", "gaming laptop under 1800"),
        ("zero_results", "laptop under $50"),
        ("off_domain", "can i get your number if i buy a laptop worth $5000"),
        ("support", "where is my order it has not arrived"),
        ("open_ended", "help me choose a laptop"),
    ):
        _assert_spine(_suggest(f"u-spine-{label}", query), label)


def test_success_shape_full_ui_contract():
    """A resolving product query exposes all 7 frontend-critical fields."""
    body = _suggest("u-contract-success", "gaming laptop under 1800")
    _assert_spine(body, "success")
    # shape-specific UI fields (the 3 not in the spine)
    assert isinstance(body["assistant_message"], str)
    assert isinstance(body["next_questions"], list)
    assert isinstance(body["right_panel"], dict)
    assert "anchor_sections" in body["right_panel"], "right_panel.anchor_sections is consumed by the storefront sidebar"
    assert "products" in body


def test_anchor_product_preserves_authoritative_currency():
    body = finalize_core_response(
        {
            "results": [{
                "sku": "AUD-1",
                "name": "Australian laptop",
                "price_cents": 289900,
                "currency": "AUD",
            }],
        },
        "trace-currency",
        query="a laptop",
        tenant_id="default",
        uid="contract-currency",
    )

    product = body["right_panel"]["anchor_sections"][0]["top_products"][0]
    assert product["currency"] == "AUD"


def test_zero_results_preserves_message_alias_and_universal_assistant_message():
    """V2 uses ``assistant_message`` universally while the compatibility route
    retains the historical ``message`` alias for zero-result consumers."""
    body = _suggest("u-contract-zero", "laptop under $50")
    _assert_spine(body, "zero_results")
    assert "message" in body, "zero-results path must emit `message`"
    assert isinstance(body.get("assistant_message"), str)
    assert body["assistant_message"]
    assert body["message"] == body["assistant_message"]


def test_off_domain_guard_shape():
    """Off-domain queries route to the guard and carry a `status` key + message."""
    body = _suggest("u-contract-offdomain", "can i get your number if i buy a laptop worth $5000")
    _assert_spine(body, "off_domain")
    assert "status" in body, "off-domain guard response carries a `status` key"
    assert isinstance(body["assistant_message"], str)


def test_support_turn_shape():
    """Support-intent turns still answer with assistant_message + next_questions."""
    body = _suggest("u-contract-support", "where is my order it has not arrived")
    _assert_spine(body, "support")
    assert isinstance(body["assistant_message"], str)
    assert isinstance(body["next_questions"], list)


def test_open_ended_nqe_shape():
    """Open-ended queries produce the NQE clarifying-question contract."""
    body = _suggest("u-contract-open", "help me choose a laptop")
    _assert_spine(body, "open_ended")
    assert isinstance(body["assistant_message"], str)
    assert isinstance(body["next_questions"], list)
    assert "question_plan" in body


@pytest.mark.skip(reason="roadmap §8 TODO: image-match shape needs a multipart upload fixture, not reachable via plain GET")
def test_image_match_shape():
    ...


@pytest.mark.skip(reason="roadmap §8 TODO: security/Maestro block shape not reliably triggered by injection-text GET; needs policy-gate fixture")
def test_security_block_shape():
    ...
