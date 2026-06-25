"""S3 human-correction learning — the human-in-the-loop signal becomes a signed graph prior.

A human's judgement (approval, rejection, NQE correction, escalation, return) tips an entity's recall
prior: positive lifts it, negative suppresses it, so a rejected/returned product ranks LOWER next time
while an approved one ranks higher. Plus idempotent envelope + batch derivation from existing tables.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import human_feedback as hf
from src.app.services.hippograph import HippoGraph, project_human_feedback, recall
from src.app.services.hippograph_db import _DEFAULT_SKU_PATTERN  # the pattern build_from_db passes through


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


# ── envelope ─────────────────────────────────────────────────────────────────
def test_polarity_defaults_by_type():
    assert hf.normalize("approval", entity_ref="A").signed > 0      # approval lifts
    assert hf.normalize("return", entity_ref="A").signed < 0        # return suppresses
    assert hf.normalize("escalation", entity_ref="A").signed < 0    # escalation suppresses
    assert hf.normalize("nqe_correction", entity_ref="A").signed > 0  # correction reinforces


def test_normalize_requires_type_and_a_target():
    assert hf.normalize("", entity_ref="A") is None         # no type
    assert hf.normalize("approval") is None                 # no subject AND no entity


def test_record_and_dedup(db):
    assert hf.record_feedback(db, "rejection", entity_ref="SKU-1", subject_hash="u1") is True
    assert hf.record_feedback(db, "rejection", entity_ref="SKU-1", subject_hash="u1") is False  # idempotent
    rows = hf.load_recent(db)
    assert len(rows) == 1 and rows[0]["feedback_type"] == "rejection" and rows[0]["polarity"] == -1.0


def test_record_is_tenant_scoped(db):
    hf.record_feedback(db, "approval", entity_ref="SKU-1", tenant_id="t-a")
    hf.record_feedback(db, "approval", entity_ref="SKU-1", tenant_id="t-b")  # same payload, diff tenant
    assert len(hf.load_recent(db, tenant_id="t-a")) == 1
    assert len(hf.load_recent(db, tenant_id="t-b")) == 1


# ── projection: the sign tips the recall prior ───────────────────────────────
def test_rejection_drops_below_approval_in_recall():
    g = HippoGraph()
    rows = [  # SKU-like ids (digit/hyphen) resolve to themselves, not to `name:` nodes
        {"feedback_type": "approval", "subject_hash": "u1", "entity_ref": "GOOD-1", "polarity": 1.0, "weight": 1.0},
        {"feedback_type": "return", "subject_hash": "u1", "entity_ref": "BAD-1", "polarity": -1.0, "weight": 1.0},
    ]
    project_human_feedback(g, rows, sku_pattern=_DEFAULT_SKU_PATTERN)
    # both reachable from the user; the approved entity must out-rank the returned one
    ranked = dict(recall(g, ["u1"], top_k=10))
    assert ranked.get("GOOD-1", 0) > ranked.get("BAD-1", 0)
    assert g.nodes["GOOD-1"].weight > 0 and g.nodes["BAD-1"].weight < 0  # the sign lives in the prior


def test_connectivity_edges_are_positive_even_for_negative_feedback():
    g = HippoGraph()
    project_human_feedback(g, [{"feedback_type": "return", "subject_hash": "u1", "entity_ref": "BAD-1",
                                "polarity": -1.0, "weight": 1.0}], sku_pattern=_DEFAULT_SKU_PATTERN)
    # the subject→entity relatedness edge is positive (magnitude), so spreading activation stays sound
    assert g.adjacency["u1"]["BAD-1"] > 0


# ── typed entities (Finding 8): non-product ids must NOT become product nodes ─
def test_non_product_feedback_does_not_create_product_nodes():
    g = HippoGraph()
    project_human_feedback(g, [
        {"feedback_type": "approval", "subject_hash": "u1", "entity_ref": "appr-123",
         "entity_type": "decision", "polarity": 1.0, "weight": 1.0},
        {"feedback_type": "escalation", "subject_hash": "u1", "entity_ref": "inc-9",
         "entity_type": "incident", "polarity": -1.0, "weight": 1.0},
        {"feedback_type": "nqe_correction", "subject_hash": "u1", "entity_ref": "use_case",
         "entity_type": "attribute", "polarity": 1.0, "weight": 1.0},
    ], sku_pattern=_DEFAULT_SKU_PATTERN)
    # typed nodes, NOT products
    assert g.nodes["decision:appr-123"].kind == "decision"
    assert g.nodes["incident:inc-9"].kind == "incident"
    assert g.nodes["attribute:use_case"].kind == "attribute"
    assert not any(n.kind == "product" for n in g.nodes.values())  # no fake products


def test_product_feedback_still_resolves_to_product():
    g = HippoGraph()
    project_human_feedback(g, [{"feedback_type": "recommendation_accepted", "subject_hash": "u1",
                                "entity_ref": "SKU-7", "entity_type": "product", "polarity": 1.0, "weight": 1.0}],
                           sku_pattern=_DEFAULT_SKU_PATTERN)
    assert g.nodes["SKU-7"].kind == "product" and g.nodes["SKU-7"].weight > 0


def test_entity_type_roundtrips_through_envelope(db):
    hf.record_feedback(db, "approval", subject_hash="u1", entity_ref="appr-1", entity_type="decision")
    row = hf.load_recent(db)[0]
    assert row["entity_type"] == "decision" and row["entity_ref"] == "appr-1"


# ── batch derivation from existing tables ────────────────────────────────────
def test_backfill_returns_and_corrections(db):
    db.execute(text("CREATE TABLE orders (id TEXT, status TEXT)"))
    db.execute(text("INSERT INTO orders VALUES ('O1','refunded')"))
    from src.app.services import attribution
    attribution.ensure_tables(db)
    db.execute(text("INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, "
                    "attributed_skus_json, value_cents, converted_at) "
                    "VALUES ('c1','d1','O1','u1','[\"SKU-9\"]',1000,'2026-06-25')"))
    from src.app.services.market_analysis import MarketFinding, correct_finding, persist_findings
    persist_findings(db, [MarketFinding("demand_shift", "SKU-7", "warn", 0.6, "x", {}, "daily")])
    fid = db.execute(text("SELECT id FROM market_finding WHERE status='active'")).scalar()
    correct_finding(db, fid, note="false positive")
    db.commit()

    counts = hf.backfill_from_db(db)
    assert counts["returns"] == 1 and counts["finding_corrections"] == 1
    rows = {r["feedback_type"]: r for r in hf.load_recent(db)}
    assert rows["return"]["entity_ref"] == "SKU-9" and rows["return"]["polarity"] == -1.0
    assert rows["finding_correction"]["entity_ref"] == "SKU-7"
    # idempotent re-run
    assert hf.backfill_from_db(db) == {"returns": 0, "finding_corrections": 0}


def test_backfill_safe_on_missing_tables(db):
    assert hf.backfill_from_db(db) == {"returns": 0, "finding_corrections": 0}
    assert hf.backfill_from_db(None) == {}


def test_task_registered_and_default_off():
    from src.app.workers.celery_app import celery_app
    from src.app.tasks.human_feedback_tasks import human_feedback_backfill, _enabled
    assert "src.app.tasks.human_feedback_tasks" in (celery_app.conf.imports or ())
    assert _enabled() is False
    assert human_feedback_backfill.run() == {"skipped": "disabled"}


# ── event-site capture hook (gated, default-OFF) ─────────────────────────────
def test_capture_feedback_is_inert_by_default(db, monkeypatch):
    monkeypatch.delenv("HUMAN_FEEDBACK_CAPTURE_ENABLED", raising=False)
    assert hf.capture_enabled() is False
    assert hf.capture_feedback(db, "approval", entity_ref="P1", subject_hash="u1") is False  # no-op
    assert hf.load_recent(db) == []  # nothing written when capture is off


def test_capture_feedback_writes_when_enabled(db, monkeypatch):
    monkeypatch.setenv("HUMAN_FEEDBACK_CAPTURE_ENABLED", "1")
    assert hf.capture_enabled() is True
    assert hf.capture_feedback(db, "nqe_correction", entity_ref="use_case", subject_hash="u1",
                               source="nqe", dedup_fields={"uid": "u1", "field": "use_case"}) is True
    rows = hf.load_recent(db)
    assert len(rows) == 1 and rows[0]["feedback_type"] == "nqe_correction" and rows[0]["polarity"] > 0


def test_capture_feedback_never_raises(monkeypatch):
    monkeypatch.setenv("HUMAN_FEEDBACK_CAPTURE_ENABLED", "1")
    assert hf.capture_feedback(None, "approval", entity_ref="P1") is False  # bad db → False, no raise
