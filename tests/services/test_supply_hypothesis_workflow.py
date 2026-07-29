from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.models.db import get_db
from src.app.models.db import set_engine
from src.app.routers.supply_risk import router
from src.app.services.currency_authority import FxAuthority, record_fx_authority
from src.app.services.product_identity import (
    register_uom,
    register_uom_conversion,
)
from src.app.services.qualified_alternative_workflow import (
    propose_qualified_alternatives,
)
from src.app.services.supply_graph_repository import (
    put_edge_revision,
    put_node_revision,
)
from src.app.services.supply_hypothesis_workflow import (
    create_grounded_hypothesis,
    get_grounded_hypothesis,
    record_supplier_hypothesis_observation,
    reevaluate_grounded_hypothesis,
)


def _migrate(engine) -> None:
    root = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    for filename in (
        "20260813_canonical_business_semantics.py",
        "20260817_supply_intelligence.py",
        "20260820_inventory_projection.py",
        "20260821_supply_graph_ops.py",
        "20260823_supply_hypothesis_workflow.py",
    ):
        spec = importlib.util.spec_from_file_location(filename, root / filename)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            original = module.op
            module.op = Operations(MigrationContext.configure(connection))
            try:
                module.upgrade()
            finally:
                module.op = original
    set_engine(engine)


def _graph(db: Session, tenant: str) -> tuple[str, str]:
    component = put_node_revision(
        db,
        tenant_id=tenant,
        logical_key="component:ram",
        node_type="component",
        label="Memory component",
        source_system="approved-bom",
        source_record_id=f"{tenant}-component",
        provenance={"document": "bom-v1"},
        valid_from="2026-01-01T00:00:00Z",
        recorded_at="2026-01-02T00:00:00Z",
    )["id"]
    variant = put_node_revision(
        db,
        tenant_id=tenant,
        logical_key="variant:laptop-1",
        node_type="variant",
        label="Laptop variant",
        source_system="catalog",
        source_record_id=f"{tenant}-variant",
        provenance={"catalog_version": "v1"},
        valid_from="2026-01-01T00:00:00Z",
        attributes={"variant_id": "laptop-1"},
        recorded_at="2026-01-02T00:00:00Z",
    )["id"]
    put_edge_revision(
        db,
        tenant_id=tenant,
        logical_key="ram-in-laptop",
        from_node_id=component,
        to_node_id=variant,
        relationship_type="composed_of",
        source_system="approved-bom",
        source_record_id=f"{tenant}-edge",
        provenance={"document": "bom-v1"},
        valid_from="2026-01-01T00:00:00Z",
        confidence=0.9,
        properties={
            "cost_share_low": 0.15,
            "cost_share_high": 0.25,
            "pass_through_low": 0.5,
            "pass_through_high": 0.8,
        },
        recorded_at="2026-01-02T00:00:00Z",
    )
    return component, variant


def _signal(
    db: Session,
    *,
    tenant: str,
    subject: str,
    signal_id: str,
    available_at: str = "2026-02-01T00:00:00Z",
    expires_at: str | None = "2026-12-31T00:00:00Z",
    comparable: bool = True,
) -> None:
    magnitude = (
        {"low_pct": 10, "high_pct": 20}
        if comparable else {"value": 1200, "status": "observed_value"}
    )
    measurement = (
        {"unit": "percent"} if comparable else {"unit": "USD_per_tonne"}
    )
    db.execute(
        text(
            """
            INSERT INTO supply_signal_observation
            (id,tenant_id,subject_node_id,signal_type,direction,magnitude_json,
             measurement_json,effective_from,effective_to,published_at,available_at,
             source_system,source_record_id,source_policy_json,provenance_json,
             confidence,status,simulation_only,comparison_scope_json,expires_at)
            VALUES
            (:id,:tenant,:subject,'component_price','up',:magnitude,:measurement,
             '2026-01-01T00:00:00Z',NULL,'2026-02-01T00:00:00Z',:available,
             'official-index',:record,:policy,:provenance,0.8,'observed',0,
             :scope,:expires)
            """
        ),
        {
            "id": signal_id,
            "tenant": tenant,
            "subject": subject,
            "magnitude": json.dumps(magnitude),
            "measurement": json.dumps(measurement),
            "available": available_at,
            "record": signal_id,
            "policy": json.dumps({"licence": "approved"}),
            "provenance": json.dumps(["official-index", signal_id]),
            "scope": json.dumps({"geography": "global"}),
            "expires": expires_at,
        },
    )
    db.commit()


def _alternative(
    db: Session,
    *,
    tenant: str,
    target: str,
    key: str,
    certified_until: str | None = None,
) -> tuple[str, str]:
    candidate = put_node_revision(
        db,
        tenant_id=tenant,
        logical_key=f"variant:{key}",
        node_type="variant",
        label=f"Alternative {key}",
        source_system="approved-catalog",
        source_record_id=f"{tenant}-{key}-candidate",
        provenance={"qualification_file": f"{key}-v1"},
        valid_from="2026-01-01T00:00:00Z",
        recorded_at="2026-01-02T00:00:00Z",
    )["id"]
    supplier = put_node_revision(
        db,
        tenant_id=tenant,
        logical_key=f"supplier:{key}",
        node_type="supplier",
        label=f"Supplier {key}",
        source_system="approved-suppliers",
        source_record_id=f"{tenant}-{key}-supplier",
        provenance={"onboarding": f"{key}-approved"},
        valid_from="2026-01-01T00:00:00Z",
        attributes={"contact_email": f"{key}@supplier.test"},
        recorded_at="2026-01-02T00:00:00Z",
    )["id"]
    for relationship in (
        "qualified_substitute_for",
        "compatible_with",
        "certified_for",
    ):
        edge = put_edge_revision(
            db,
            tenant_id=tenant,
            logical_key=f"{key}:{relationship}",
            from_node_id=candidate,
            to_node_id=target,
            relationship_type=relationship,
            source_system="qualification-register",
            source_record_id=f"{tenant}-{key}-{relationship}",
            provenance={"certificate": f"{key}-cert"},
            valid_from="2026-01-01T00:00:00Z",
            confidence=0.95,
            recorded_at="2026-01-02T00:00:00Z",
        )
        if relationship == "certified_for" and certified_until:
            db.execute(
                text(
                    "UPDATE supply_dependency_edge SET valid_to=:until WHERE id=:id"
                ),
                {"until": certified_until, "id": edge["id"]},
            )
            db.commit()
    put_edge_revision(
        db,
        tenant_id=tenant,
        logical_key=f"{key}:supplier",
        from_node_id=candidate,
        to_node_id=supplier,
        relationship_type="supplied_by",
        source_system="approved-suppliers",
        source_record_id=f"{tenant}-{key}-supplied-by",
        provenance={"agreement": f"{key}-supply"},
        valid_from="2026-01-01T00:00:00Z",
        confidence=0.9,
        recorded_at="2026-01-02T00:00:00Z",
    )
    return candidate, supplier


def test_no_current_evidence_and_no_path_fail_closed(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'no-path.sqlite'}", future=True
    )
    _migrate(engine)
    with Session(engine) as db:
        component, target = _graph(db, "tenant-a")
        none = create_grounded_hypothesis(
            db,
            tenant_id="tenant-a",
            target_node_id=target,
            decision_time="2026-03-01T00:00:00Z",
            created_by="operator",
        )
        assert none["hypothesis"]["reason"] == "no_current_comparable_evidence"
        assert none["procurement_options"]["status"] == "not_proposed"
        _signal(
            db, tenant="tenant-a", subject=component,
            signal_id="signal-after-graph-break",
        )
        db.execute(
            text(
                "UPDATE supply_dependency_edge SET valid_to='2026-02-15T00:00:00Z'"
            )
        )
        db.commit()
        no_path = create_grounded_hypothesis(
            db,
            tenant_id="tenant-a",
            target_node_id=target,
            decision_time="2026-03-02T00:00:00Z",
            created_by="operator",
        )
        assert no_path["hypothesis"]["reason"] == "no_time_valid_dependency_path"
        assert no_path["execution_allowed"] is False


def test_stale_and_noncomparable_signals_are_sealed_as_exclusions(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'excluded.sqlite'}", future=True
    )
    _migrate(engine)
    with Session(engine) as db:
        component, target = _graph(db, "tenant-a")
        _signal(
            db, tenant="tenant-a", subject=component, signal_id="stale",
            expires_at="2026-02-15T00:00:00Z",
        )
        _signal(
            db, tenant="tenant-a", subject=component,
            signal_id="wrong-dimension", comparable=False,
        )
        result = create_grounded_hypothesis(
            db,
            tenant_id="tenant-a",
            target_node_id=target,
            decision_time="2026-03-01T00:00:00Z",
            created_by="operator",
        )
        stored = get_grounded_hypothesis(
            db, tenant_id="tenant-a", hypothesis_id=result["hypothesis_id"]
        )
        reasons = {
            item["reason"]
            for item in stored["evidence_bundle"]["excluded_signals"]
        }
        assert reasons == {"stale", "magnitude_not_comparable"}
        assert stored["hypothesis"]["status"] == "no_verified_exposure"


def test_supplier_reply_is_observation_and_reevaluation_supersedes_immutably(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'supersede.sqlite'}", future=True
    )
    _migrate(engine)
    with Session(engine) as db:
        component, target = _graph(db, "tenant-a")
        _signal(db, tenant="tenant-a", subject=component, signal_id="price-up")
        original = create_grounded_hypothesis(
            db,
            tenant_id="tenant-a",
            target_node_id=target,
            decision_time="2026-03-01T00:00:00Z",
            created_by="analyst",
            known_exposure={
                "open_commitments": {
                    "value": 20,
                    "uom": "EA",
                    "provenance": {"po_snapshot": "po-run-1"},
                }
            },
        )
        assert original["hypothesis"]["status"] == "supported_hypothesis"
        assert original["procurement_options"]["authority"] == "proposal_only"
        reply = record_supplier_hypothesis_observation(
            db,
            tenant_id="tenant-a",
            hypothesis_id=original["hypothesis_id"],
            observation_type="contradiction",
            supplier_ref="supplier-1",
            source_message_id="message-1",
            observation={"claim": "No allocation applies to this contract."},
            provenance={"inbound_inbox_id": "inbox-1", "evidence_hash": "abc"},
            observed_at="2026-03-02T00:00:00Z",
            recorded_by="operator",
        )
        assert reply["authority"] == "supplier_observation_only"
        assert reply["can_authorize_execution"] is False
        revised = reevaluate_grounded_hypothesis(
            db,
            tenant_id="tenant-a",
            hypothesis_id=original["hypothesis_id"],
            decision_time="2026-03-03T00:00:00Z",
            created_by="analyst",
        )
        assert revised["hypothesis_id"] != original["hypothesis_id"]
        assert (
            revised["hypothesis"]["supersedes_hypothesis_id"]
            == original["hypothesis_id"]
        )
        assert revised["hypothesis"]["status"] == "contested_hypothesis"
        unchanged = get_grounded_hypothesis(
            db,
            tenant_id="tenant-a",
            hypothesis_id=original["hypothesis_id"],
        )
        assert unchanged["hypothesis"]["status"] == "supported_hypothesis"
        with pytest.raises(Exception, match="append_only"):
            db.execute(
                text(
                    "UPDATE causal_impact_hypothesis SET status='mutated' WHERE id=:id"
                ),
                {"id": original["hypothesis_id"]},
            )


def test_tenant_isolation_rejects_cross_tenant_targets_and_hypotheses(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'tenant.sqlite'}", future=True
    )
    _migrate(engine)
    with Session(engine) as db:
        _, target = _graph(db, "tenant-a")
        with pytest.raises(ValueError, match="target_not_in_tenant"):
            create_grounded_hypothesis(
                db,
                tenant_id="tenant-b",
                target_node_id=target,
                decision_time="2026-03-01T00:00:00Z",
                created_by="operator",
            )
        own = create_grounded_hypothesis(
            db,
            tenant_id="tenant-a",
            target_node_id=target,
            decision_time="2026-03-01T00:00:00Z",
            created_by="operator",
        )
        with pytest.raises(ValueError, match="hypothesis_not_in_tenant"):
            get_grounded_hypothesis(
                db,
                tenant_id="tenant-b",
                hypothesis_id=own["hypothesis_id"],
            )


def test_supply_hypothesis_api_preserves_proposal_only_reply_boundary(
    tmp_path, monkeypatch
):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}", future=True
    )
    _migrate(engine)
    with Session(engine) as setup:
        component, target = _graph(setup, "default")
        _signal(
            setup, tenant="default", subject=component, signal_id="router-signal"
        )

    def session_override():
        with Session(engine) as session:
            yield session

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ABAC_ENABLED", "0")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = session_override
    client = TestClient(app, headers={"x-api-key": "local-owner-key"})
    created = client.post(
        "/api/v1/supply-risk/hypotheses",
        json={
            "target_node_id": target,
            "decision_time": "2026-03-01T00:00:00Z",
            "case_id": "case-1",
        },
    )
    assert created.status_code == 200
    hypothesis_id = created.json()["hypothesis_id"]
    assert created.json()["execution_allowed"] is False
    reply = client.post(
        f"/api/v1/supply-risk/hypotheses/{hypothesis_id}/supplier-observations",
        json={
            "observation_type": "narrowing",
            "supplier_ref": "supplier-1",
            "source_message_id": "inbound-1",
            "observation": {"applies_to": "one facility"},
            "provenance": {"inbox_id": "inbox-1", "evidence_hash": "hash-1"},
            "observed_at": "2026-03-02T00:00:00Z",
        },
    )
    assert reply.status_code == 200
    assert reply.json()["can_authorize_execution"] is False
    revised = client.post(
        f"/api/v1/supply-risk/hypotheses/{hypothesis_id}/reevaluate",
        json={"decision_time": "2026-03-03T00:00:00Z"},
    )
    assert revised.status_code == 200
    assert (
        revised.json()["hypothesis"]["supersedes_hypothesis_id"]
        == hypothesis_id
    )


def test_qualified_alternatives_require_active_evidence_and_rank_landed_cost(
    tmp_path,
):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'alternatives.sqlite'}", future=True
    )
    _migrate(engine)
    register_uom(
        tenant_id="tenant-a", category="count", code="EA",
        factor_to_base=Decimal(1), is_base=True,
    )
    register_uom(
        tenant_id="tenant-a", category="count", code="CASE10",
        factor_to_base=Decimal(10),
    )
    register_uom_conversion(
        tenant_id="tenant-a",
        from_code="CASE10",
        to_code="EA",
        factor=Decimal(10),
        effective_from="2026-01-01T00:00:00Z",
        source="pack-contract",
        source_record_id="pack-v1",
        approved_by="operator",
    )
    record_fx_authority(
        tenant_id="tenant-a",
        authority=FxAuthority(
            base_currency="USD",
            quote_currency="AUD",
            rate=Decimal("1.5"),
            as_of="2026-03-01T00:00:00Z",
            source="approved-fx",
            source_record_id="fx-1",
        ),
        approved_by="operator",
    )
    with Session(engine) as db:
        component, target = _graph(db, "tenant-a")
        _signal(db, tenant="tenant-a", subject=component, signal_id="risk")
        candidate, supplier = _alternative(
            db, tenant="tenant-a", target=target, key="qualified"
        )
        _, second_supplier = _alternative(
            db, tenant="tenant-a", target=target, key="qualified-second"
        )
        # The second supplier is also explicitly linked to the first qualified
        # candidate, allowing two commercial quotes for one substitute.
        put_edge_revision(
            db,
            tenant_id="tenant-a",
            logical_key="qualified:second-supplier",
            from_node_id=candidate,
            to_node_id=second_supplier,
            relationship_type="supplied_by",
            source_system="approved-suppliers",
            source_record_id="qualified-second-supplier-link",
            provenance={"agreement": "second-supply"},
            valid_from="2026-01-01T00:00:00Z",
            confidence=0.9,
            recorded_at="2026-01-02T00:00:00Z",
        )
        expired, expired_supplier = _alternative(
            db,
            tenant="tenant-a",
            target=target,
            key="expired",
            certified_until="2026-02-01T00:00:00Z",
        )
        unqualified = put_node_revision(
            db,
            tenant_id="tenant-a",
            logical_key="variant:unqualified",
            node_type="variant",
            label="Unqualified",
            source_system="catalog",
            source_record_id="unqualified-node",
            provenance={"catalog": "v1"},
            valid_from="2026-01-01T00:00:00Z",
            recorded_at="2026-01-02T00:00:00Z",
        )["id"]
        hypothesis = create_grounded_hypothesis(
            db,
            tenant_id="tenant-a",
            target_node_id=target,
            decision_time="2026-03-01T01:00:00Z",
            created_by="analyst",
        )
        quotes = [
            {
                "quote_id": "aud-each",
                "candidate_node_id": candidate,
                "supplier_node_id": supplier,
                "quote_uom": "EA",
                "currency": "AUD",
                "purchase_unit_cost_minor": 1200,
                "freight_unit_minor": 100,
                "quantity": 10,
                "provenance": {"quote": "aud-1"},
            },
            {
                "quote_id": "usd-case",
                "candidate_node_id": candidate,
                "supplier_node_id": second_supplier,
                "quote_uom": "CASE10",
                "currency": "USD",
                "purchase_unit_cost_minor": 6000,
                "freight_unit_minor": 1000,
                "quantity": 20,
                "price_breaks": [{"min_qty": 20, "discount_pct": 10}],
                "provenance": {"quote": "usd-1"},
            },
            {
                "quote_id": "expired-certification",
                "candidate_node_id": expired,
                "supplier_node_id": expired_supplier,
                "quote_uom": "EA",
                "currency": "AUD",
                "purchase_unit_cost_minor": 500,
                "provenance": {"quote": "expired-1"},
            },
            {
                "quote_id": "unqualified",
                "candidate_node_id": unqualified,
                "supplier_node_id": supplier,
                "quote_uom": "EA",
                "currency": "AUD",
                "purchase_unit_cost_minor": 100,
                "provenance": {"quote": "unqualified-1"},
            },
            {
                "quote_id": "missing-uom",
                "candidate_node_id": candidate,
                "supplier_node_id": supplier,
                "quote_uom": "PALLET",
                "currency": "AUD",
                "purchase_unit_cost_minor": 100,
                "provenance": {"quote": "uom-1"},
            },
            {
                "quote_id": "missing-fx",
                "candidate_node_id": candidate,
                "supplier_node_id": supplier,
                "quote_uom": "EA",
                "currency": "EUR",
                "purchase_unit_cost_minor": 100,
                "provenance": {"quote": "fx-1"},
            },
        ]
        result = propose_qualified_alternatives(
            db,
            tenant_id="tenant-a",
            hypothesis_id=hypothesis["hypothesis_id"],
            target_currency="AUD",
            target_uom="EA",
            quotes=quotes,
            created_by="buyer",
        )

    ranked = result["comparison"]["ranked"]
    assert [row["quote_id"] for row in ranked] == ["usd-case", "aud-each"]
    reasons = {
        row["quote_id"]: row["reason"]
        for row in result["comparison"]["excluded"]
    }
    assert reasons["expired-certification"] == "active_certification_required"
    assert reasons["unqualified"] == "alternative_not_qualified"
    assert reasons["missing-uom"].startswith("uom_incomparable:")
    assert reasons["missing-fx"] == "approved_fx_authority_required"
    assert result["authority"] == "proposal_only"
    assert result["execution_allowed"] is False
    assert result["delivery_enqueued"] is False
    assert result["communication_drafts"]
    assert all(
        draft["status"] == "awaiting_human_approval"
        and draft["authority"] == "draft_only"
        and draft["delivery_enqueued"] is False
        for draft in result["communication_drafts"]
    )
