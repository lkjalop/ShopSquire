from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.disruption_intelligence import (
    draft_disruption_buyer_reviews,
    disruption_workbench_projection,
    project_disruption_impact,
    record_disruption_observation,
)
from src.app.services.supply_graph_repository import put_edge_revision, put_node_revision


ROOT = Path(__file__).resolve().parents[2]


def _migrate(connection, filename: str) -> None:
    path = ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    with engine.begin() as connection:
        _migrate(connection, "20260817_supply_intelligence.py")
        _migrate(connection, "20260821_supply_graph_ops.py")
        _migrate(connection, "20260848_disruption_observation.py")
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _node(db, tenant: str, key: str, kind: str):
    return put_node_revision(
        db, tenant_id=tenant, logical_key=key, node_type=kind, label=key,
        source_system="tenant_mapping", source_record_id=f"{tenant}:{key}",
        provenance={"mapping_version": "v1", "approved_by": "owner"},
        valid_from="2026-01-01T00:00:00Z",
    )


def _observation(db, node_id: str, **overrides):
    values = {
        "tenant_id": "tenant-a", "disruption_type": "customs_system_outage",
        "affected_node_ids": [node_id], "geography": "AU-SYD",
        "effective_from": "2026-08-03T00:00:00Z",
        "observed_at": "2026-08-03T00:01:00Z",
        "retrieved_at": "2026-08-03T00:02:00Z",
        "published_at": "2026-08-03T00:00:30Z",
        "fresh_until": "2026-08-03T04:00:00Z",
        "source_id": "official-customs", "source_record_id": "incident-42",
        "source_revision": "r3", "source_licence": "official-open-data-v1",
        "evidence_ref": "sha256:evidence-42", "severity": "high",
        "probability_range": (0.7, 0.9), "delay_range_days": (3, 8),
        "cost_impact_range_minor": (10000, 30000), "currency": "AUD",
        "claim_status": "supported", "contradiction_status": "unchallenged",
        "contradiction_group": "sydney-customs-20260803",
    }
    values.update(overrides)
    return record_disruption_observation(db, **values)


def _baseline():
    return {
        "quantity": 10,
        "currency": "AUD",
        "unit_sell_price_minor": 200_000,
        "unit_landed_cost_minor": 150_000,
        "eta_days": (7, 12),
        "freight_cost_minor": (50_000, 70_000),
        "payment_authorization_minor": 2_000_000,
    }


def test_migration_preserves_advisory_authority_and_source_revision(db):
    assert {
        "supply_disruption_observation", "supply_disruption_impact_projection",
    } <= set(inspect(db.bind).get_table_names())
    lane = _node(db, "tenant-a", "lane:cn-syd", "logistics_lane")
    first = _observation(db, lane["id"])
    replay = _observation(db, lane["id"])
    assert replay["id"] == first["id"]
    assert replay["idempotent_replay"] is True
    row = db.execute(text(
        "SELECT authority,source_revision,source_licence,effective_from,observed_at,"
        "retrieved_at,contradiction_group,claim_status FROM supply_disruption_observation"
    )).mappings().one()
    assert row["authority"] == "advisory_only"
    assert row["source_revision"] == "r3"
    assert row["source_licence"] == "official-open-data-v1"
    assert row["effective_from"] != row["observed_at"] != row["retrieved_at"]
    assert row["contradiction_group"] == "sydney-customs-20260803"
    assert row["claim_status"] == "supported"


def test_new_source_revision_supersedes_without_rewriting_prior_observation(db):
    lane = _node(db, "tenant-a", "lane:cn-syd", "logistics_lane")
    target = _node(db, "tenant-a", "variant:rgam-7", "variant")
    first = _observation(db, lane["id"])
    correction = _observation(
        db, lane["id"], source_revision="r4", claim_status="retracted",
    )
    assert correction["supersedes_id"] == first["id"]
    prior = db.execute(text(
        "SELECT claim_status,recorded_to FROM supply_disruption_observation WHERE id=:id"
    ), {"id": first["id"]}).mappings().one()
    assert prior["claim_status"] == "supported"
    assert prior["recorded_to"] is not None
    result = project_disruption_impact(
        db, tenant_id="tenant-a", observation_id=first["id"],
        target_node_id=target["id"], baseline_version="allocation-v7",
        baseline=_baseline(), decision_time="2026-08-03T00:30:00Z",
    )
    assert result["reason"] == "observation_superseded"
    assert result["impact"] is None


@pytest.mark.parametrize(
    ("changes", "expected_reason"),
    [
        ({"fresh_until": "2026-08-03T00:03:00Z"}, "observation_stale_or_inactive"),
        ({"claim_status": "reported", "source_revision": "r4"}, "claim_not_corroborated"),
        ({"contradiction_status": "contested", "source_revision": "r5"}, "evidence_contested"),
    ],
)
def test_stale_uncorroborated_or_contested_observation_changes_nothing(
    db, changes, expected_reason,
):
    lane = _node(db, "tenant-a", "lane:cn-syd", "logistics_lane")
    target = _node(db, "tenant-a", "variant:rgam-7", "variant")
    observation = _observation(db, lane["id"], **changes)
    result = project_disruption_impact(
        db, tenant_id="tenant-a", observation_id=observation["id"],
        target_node_id=target["id"], baseline_version="allocation-v7",
        baseline=_baseline(), decision_time="2026-08-03T00:30:00Z",
    )
    assert result["status"] == "no_commercial_change"
    assert result["reason"] == expected_reason
    assert result["impact"] is None
    assert result["external_action"] == "none"
    assert db.execute(text("SELECT COUNT(*) FROM supply_disruption_impact_projection")).scalar() == 0


def test_unrelated_or_cross_tenant_event_without_dependency_path_changes_nothing(db):
    lane = _node(db, "tenant-a", "lane:unrelated", "logistics_lane")
    target = _node(db, "tenant-a", "variant:rgam-7", "variant")
    observation = _observation(db, lane["id"])
    result = project_disruption_impact(
        db, tenant_id="tenant-a", observation_id=observation["id"],
        target_node_id=target["id"], baseline_version="allocation-v7",
        baseline=_baseline(), decision_time="2026-08-03T00:30:00Z",
    )
    assert result["reason"] == "no_time_valid_dependency_path"
    assert result["proposals"] == []
    other_target = _node(db, "tenant-b", "variant:rgam-7", "variant")
    cross_tenant = project_disruption_impact(
        db, tenant_id="tenant-a", observation_id=observation["id"],
        target_node_id=other_target["id"], baseline_version="allocation-v7",
        baseline=_baseline(), decision_time="2026-08-03T00:30:00Z",
    )
    assert cross_tenant["reason"] == "no_time_valid_dependency_path"


def test_verified_path_recalculates_bounded_commercial_proposals_without_mutation(db):
    target = _node(db, "tenant-a", "variant:rgam-7", "variant")
    facility = _node(db, "tenant-a", "facility:shanghai", "facility")
    lane = _node(db, "tenant-a", "lane:cn-syd", "logistics_lane")
    put_edge_revision(
        db, tenant_id="tenant-a", logical_key="route:rgam-7:shanghai",
        from_node_id=target["id"], to_node_id=facility["id"],
        relationship_type="manufactured_at", source_system="tenant_mapping",
        source_record_id="route-v1", provenance={"approved_by": "owner"},
        valid_from="2026-01-01T00:00:00Z", confidence=1.0,
    )
    put_edge_revision(
        db, tenant_id="tenant-a", logical_key="lane:shanghai:sydney",
        from_node_id=facility["id"], to_node_id=lane["id"],
        relationship_type="transported_via", source_system="tenant_mapping",
        source_record_id="lane-v1", provenance={"approved_by": "owner"},
        valid_from="2026-01-01T00:00:00Z", confidence=1.0,
    )
    observation = _observation(db, lane["id"])
    result = project_disruption_impact(
        db, tenant_id="tenant-a", observation_id=observation["id"],
        target_node_id=target["id"], baseline_version="allocation-v7",
        baseline=_baseline(), decision_time="2026-08-03T00:30:00Z",
    )
    assert result["status"] == "bounded_recalculation_proposed"
    assert result["dependency_path"]["orientation"] == "target_to_affected"
    assert len(result["dependency_path"]["edges"]) == 2
    assert result["impact"]["eta_days"] == {
        "before": {"low": 7, "high": 12}, "proposed": {"low": 10, "high": 20},
    }
    assert result["impact"]["freight_cost_minor"]["proposed"] == {
        "low": 60_000, "high": 100_000,
    }
    assert result["impact"]["contribution_margin"]["before"] == 0.25
    assert result["impact"]["contribution_margin"]["proposed"] == {
        "low": 0.235, "high": 0.245,
    }
    assert {item["type"] for item in result["proposals"]} == {
        "buyer_promise_review", "payment_authorization_review",
        "freight_or_supplier_recovery",
    }
    payment = next(item for item in result["proposals"] if item["type"] == "payment_authorization_review")
    assert payment["proposed_capture_minor"] == 0
    assert result["authority"] == "proposal_only"
    assert result["execution_allowed"] is False
    assert result["external_action"] == "none"
    assert result["state_prevented"] == "commercial_state_mutation"
    replay = project_disruption_impact(
        db, tenant_id="tenant-a", observation_id=observation["id"],
        target_node_id=target["id"], baseline_version="allocation-v7",
        baseline=_baseline(), decision_time="2026-08-03T00:30:00Z",
    )
    assert replay["projection_id"] == result["projection_id"]
    assert replay["idempotent_replay"] is True
    assert db.execute(text("SELECT COUNT(*) FROM supply_disruption_impact_projection")).scalar() == 1
    view = disruption_workbench_projection(db, tenant_id="tenant-a", sku="rgam-7")
    assert len(view) == 1
    assert view[0]["observation_id"] == observation["id"]
    assert view[0]["disruption_type"] == "customs_system_outage"
    assert view[0]["target_logical_key"] == "variant:rgam-7"
    assert view[0]["evidence"]["source_revision"] == "r3"
    assert disruption_workbench_projection(
        db, tenant_id="tenant-b", sku="rgam-7",
    ) == []
    assert disruption_workbench_projection(
        db, tenant_id="tenant-a", sku="another-sku",
    ) == []


def test_verified_projection_drafts_case_scoped_buyer_reviews_without_sending(db, monkeypatch):
    db.execute(text(
        "CREATE TABLE demand_commitment (id TEXT,tenant_id TEXT,case_id TEXT,sku TEXT,"
        "quantity INTEGER,stage TEXT)"
    ))
    db.execute(text(
        "INSERT INTO demand_commitment VALUES "
        "('d1','tenant-a','case-1','rgam-7',40,'committed'),"
        "('d2','tenant-a','case-2','rgam-7',20,'provisional'),"
        "('d3','tenant-b','case-other','rgam-7',10,'committed')"
    ))
    target = _node(db, "tenant-a", "variant:rgam-7", "variant")
    db.execute(text(
        "INSERT INTO supply_disruption_impact_projection "
        "(id,tenant_id,observation_id,target_node_id,baseline_version,dependency_path_json,"
        "projection_json,status,authority,created_at) VALUES "
        "('p1','tenant-a','obs-1',:target,'v1','{}',:projection,"
        "'bounded_recalculation_proposed','proposal_only','2026-08-03T10:00:00Z')"
    ), {
        "target": target["id"],
        "projection": '{"impact":{"eta_days":{"proposed":{"low":10,"high":20}}},'
        '"evidence":{"source_id":"abf","source_revision":"r1"}}',
    })
    recorded = []

    monkeypatch.setattr(
        "src.app.services.communication_observations.record_message_observation",
        lambda **kwargs: recorded.append(kwargs) or {"id": "message-1", "duplicate": False},
    )

    result = draft_disruption_buyer_reviews(
        db, tenant_id="tenant-a", projection_id="p1"
    )

    assert result["status"] == "drafted_for_human_review"
    assert result["draft_count"] == 1
    assert result["auto_sent"] is False
    assert result["human_authorization_required"] is True
    assert recorded[0]["case_ref"] == "case-1"
    assert recorded[0]["sanitized_payload"]["quantity"] == 40
    assert recorded[0]["sanitized_payload"]["revised_eta_days"] == {"low": 10, "high": 20}
    assert "case-2" not in str(recorded)
