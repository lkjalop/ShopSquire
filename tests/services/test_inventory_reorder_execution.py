import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services import inventory_reorder_execution as boundary
from src.app.services.inventory_agent import InventoryAgent, ReorderRecommendation


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    db = Session(engine)
    db.execute(text("""
        CREATE TABLE inventory_reorder_proposal (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, sku TEXT NOT NULL,
            supplier_id TEXT NOT NULL, quantity INTEGER NOT NULL,
            landed_unit_cost_cents INTEGER NOT NULL, total_cost_cents INTEGER NOT NULL,
            currency TEXT NOT NULL, lead_time_days REAL NOT NULL,
            source_record_id TEXT NOT NULL, proposal_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL, status TEXT NOT NULL, approval_id TEXT,
            executed_po_id TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, executed_at TEXT, execution_started_at TEXT,
            UNIQUE (tenant_id, proposal_hash)
        )
    """))
    db.execute(text("""
        CREATE TABLE supplier_offer (
            tenant_id TEXT NOT NULL, supplier_id TEXT NOT NULL, sku TEXT NOT NULL,
            landed_unit_cost_cents INTEGER NOT NULL, currency TEXT NOT NULL,
            cost_kind TEXT NOT NULL, source_record_id TEXT NOT NULL,
            provenance_json TEXT NOT NULL, confidence REAL NOT NULL,
            simulation_only INTEGER NOT NULL, status TEXT NOT NULL,
            effective_from TEXT NOT NULL, effective_to TEXT
        )
    """))
    db.execute(text("""
        CREATE TABLE approvals (
            id TEXT PRIMARY KEY, capability TEXT, payload TEXT, status TEXT,
            approved_by TEXT, approved_at TEXT
        )
    """))
    db.execute(text("""
        CREATE TABLE purchase_orders (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
            reorder_proposal_id TEXT, supplier_id TEXT, sku TEXT,
            quantity INTEGER, unit_cost REAL, status TEXT
        )
    """))
    db.commit()
    return db


def _seed_offer(db: Session, *, cents: int = 1200) -> None:
    db.execute(text("""
        INSERT INTO supplier_offer (
            tenant_id, supplier_id, sku, landed_unit_cost_cents, currency,
            cost_kind, source_record_id, provenance_json, confidence,
            simulation_only, status, effective_from, effective_to
        ) VALUES (
            'tenant-a', 'SUP-1', 'SKU-1', :cents, 'AUD',
            'validated_landed_quote', 'offer-1', '["supplier_offer/offer-1"]',
            0.95, 0, 'active', '2026-01-01T00:00:00+00:00', NULL
        )
    """), {"cents": cents})
    db.commit()


def _projection() -> dict:
    return {
        "available": True,
        "currency": "AUD",
        "cost_source_record_id": "offer-1",
        "action_proposals": {
            "replenishment": {
                "authorized": True,
                "shortfall": 10,
                "lead_time_days": 5,
                "reasons": [],
            }
        },
    }


def _approve(db: Session, proposal: dict) -> None:
    approval_id = "approval-1"
    db.execute(text("""
        INSERT INTO approvals (id, capability, payload, status, approved_by, approved_at)
        VALUES (:id, 'commercial_replenishment', :payload, 'approved', 'owner-1', :approved_at)
    """), {
        "id": approval_id,
        "payload": json.dumps({
            "tenant_id": "tenant-a",
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
        }),
        "approved_at": datetime.now(timezone.utc).isoformat(),
    })
    db.commit()
    boundary.bind_approval(
        db,
        tenant_id="tenant-a",
        proposal_id=proposal["proposal_id"],
        approval_id=approval_id,
    )


def test_execution_uses_immutable_server_derived_economics(monkeypatch):
    db = _db()
    _seed_offer(db)
    monkeypatch.setattr(
        "src.app.services.market_projection.operator_product_projection",
        lambda *a, **k: _projection(),
    )
    proposal = boundary.create_reorder_proposal(
        db, tenant_id="tenant-a", sku="SKU-1", actor_id="owner-1")
    assert proposal["total_cost_cents"] == 12_000
    _approve(db, proposal)

    monkeypatch.setattr(
        "src.app.security.authorization_engine.authorize_action",
        lambda *a, **k: SimpleNamespace(allowed=True, to_dict=lambda: {"decision": "allow"}),
    )
    captured = {}

    def _execute(self, recommendation, approval=None, *, governed_approval=False):
        captured.update({
            "recommendation": recommendation,
            "approval": approval,
            "governed_approval": governed_approval,
            "tenant_id": self.tenant_id,
        })
        return {"status": "po_created", "po_number": "PO-1"}

    monkeypatch.setattr(InventoryAgent, "execute_reorder", _execute)
    result = boundary.execute_approved_reorder(
        db,
        tenant_id="tenant-a",
        proposal_id=proposal["proposal_id"],
        actor_id="owner",
    )
    rec = captured["recommendation"]
    assert result["status"] == "po_created"
    assert rec.estimated_cost == 120.0
    assert rec.quantity == 10
    assert rec.supplier_id == "SUP-1"
    assert rec.proposal_id == proposal["proposal_id"]
    assert captured["governed_approval"] is True
    assert captured["tenant_id"] == "tenant-a"

    replay = boundary.execute_approved_reorder(
        db,
        tenant_id="tenant-a",
        proposal_id=proposal["proposal_id"],
        actor_id="owner",
    )
    assert replay == {
        "status": "po_created",
        "po_number": "PO-1",
        "proposal_id": proposal["proposal_id"],
        "deduped": True,
    }


def test_execution_rejects_tenant_mismatch_and_changed_offer(monkeypatch):
    db = _db()
    _seed_offer(db)
    monkeypatch.setattr(
        "src.app.services.market_projection.operator_product_projection",
        lambda *a, **k: _projection(),
    )
    proposal = boundary.create_reorder_proposal(
        db, tenant_id="tenant-a", sku="SKU-1", actor_id="owner-1")
    _approve(db, proposal)

    with pytest.raises(boundary.ReorderBoundaryError) as wrong_tenant:
        boundary.execute_approved_reorder(
            db,
            tenant_id="tenant-b",
            proposal_id=proposal["proposal_id"],
            actor_id="owner",
        )
    assert wrong_tenant.value.code == "reorder_proposal_not_found"

    db.execute(text(
        "UPDATE supplier_offer SET landed_unit_cost_cents=1300 WHERE source_record_id='offer-1'"))
    db.commit()
    with pytest.raises(boundary.ReorderBoundaryError) as changed:
        boundary.execute_approved_reorder(
            db,
            tenant_id="tenant-a",
            proposal_id=proposal["proposal_id"],
            actor_id="owner",
        )
    assert changed.value.code == "reorder_supplier_offer_changed"


def test_execution_rejects_tampered_or_expired_proposal(monkeypatch):
    db = _db()
    _seed_offer(db)
    monkeypatch.setattr(
        "src.app.services.market_projection.operator_product_projection",
        lambda *a, **k: _projection(),
    )
    proposal = boundary.create_reorder_proposal(
        db, tenant_id="tenant-a", sku="SKU-1", actor_id="owner-1")
    _approve(db, proposal)
    db.execute(text("""
        UPDATE inventory_reorder_proposal
        SET payload_json=:payload
        WHERE id=:id
    """), {"payload": '{"tampered":true}', "id": proposal["proposal_id"]})
    db.commit()
    with pytest.raises(boundary.ReorderBoundaryError) as tampered:
        boundary.execute_approved_reorder(
            db,
            tenant_id="tenant-a",
            proposal_id=proposal["proposal_id"],
            actor_id="owner",
        )
    assert tampered.value.code == "reorder_proposal_hash_mismatch"

    db.execute(text("""
        UPDATE inventory_reorder_proposal
        SET payload_json=:payload, expires_at=:expires
        WHERE id=:id
    """), {
        "payload": json.dumps({
            **_projection(),
        }),
        "expires": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "id": proposal["proposal_id"],
    })
    db.commit()
    with pytest.raises(boundary.ReorderBoundaryError) as expired:
        boundary.execute_approved_reorder(
            db,
            tenant_id="tenant-a",
            proposal_id=proposal["proposal_id"],
            actor_id="owner",
        )
    assert expired.value.code == "reorder_proposal_expired"


def test_inventory_agent_readiness_errors_fail_closed(monkeypatch):
    monkeypatch.setenv("INVENTORY_DATA_READINESS_REQUIRED", "1")
    monkeypatch.setattr(
        "src.app.data_readiness.report.compute_inventory_readiness",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    rec = ReorderRecommendation(
        sku="SKU-1",
        supplier_id="SUP-1",
        quantity=1,
        estimated_cost=10.0,
        lead_time_days=5,
        urgency="normal",
        supplier_trust_score=0.95,
        supplier_trust_band="high",
    )
    result = InventoryAgent(tenant_id="tenant-a").execute_reorder(rec)
    assert result["status"] == "data_readiness_unavailable"
    assert result["reason"] == "readiness_check_failed:RuntimeError"


def test_execution_recovers_po_persisted_before_proposal_finalization(monkeypatch):
    db = _db()
    _seed_offer(db)
    monkeypatch.setattr(
        "src.app.services.market_projection.operator_product_projection",
        lambda *a, **k: _projection(),
    )
    proposal = boundary.create_reorder_proposal(
        db, tenant_id="tenant-a", sku="SKU-1", actor_id="owner-1")
    _approve(db, proposal)
    db.execute(text("""
        UPDATE inventory_reorder_proposal
        SET status='executing', execution_started_at=:started
        WHERE id=:proposal
    """), {
        "started": datetime.now(timezone.utc).isoformat(),
        "proposal": proposal["proposal_id"],
    })
    db.execute(text("""
        INSERT INTO purchase_orders (
            id, tenant_id, reorder_proposal_id, supplier_id, sku,
            quantity, unit_cost, status
        ) VALUES (
            'PO-RECOVERED', 'tenant-a', :proposal, 'SUP-1', 'SKU-1',
            10, 12.0, 'created'
        )
    """), {"proposal": proposal["proposal_id"]})
    db.commit()

    result = boundary.execute_approved_reorder(
        db,
        tenant_id="tenant-a",
        proposal_id=proposal["proposal_id"],
        actor_id="owner",
    )
    assert result["po_number"] == "PO-RECOVERED"
    assert result["deduped"] is True
    assert result["recovered"] is True
    status = db.execute(text("""
        SELECT status FROM inventory_reorder_proposal WHERE id=:proposal
    """), {"proposal": proposal["proposal_id"]}).scalar()
    assert status == "executed"
