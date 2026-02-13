"""Tests for tenant_id persistence in decision_logs for proposals and execution.

These tests create a local decision_logs table including tenant_id and verify
both log_decision() and Orchestrator.execute_or_escalate() write tenant info.
"""

import json
import uuid
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.decision_log import log_decision
from src.app.services.orchestrator import Orchestrator
from src.app.services.memory import Memory
from src.app.security.firewall import TransactionFirewall


def _ensure_decision_logs_with_tenant():
    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS decision_logs (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT,
                  actor_id TEXT,
                  actor_role TEXT,
                  event_type TEXT,
                  agent_name TEXT,
                  valid_from TEXT,
                  valid_to TEXT,
                  system_from TEXT,
                  system_to TEXT,
                  input_data TEXT,
                  retrieved_context TEXT,
                  agent_reasoning TEXT,
                  proposed_action TEXT,
                  policy_version TEXT,
                  approval_required INTEGER,
                  execution_status TEXT
                )
                """
            )
        )
        db.commit()


def test_log_decision_persists_tenant_id(tmp_path):
    _ensure_decision_logs_with_tenant()
    tid = "tenant-xyz"
    dec_id = log_decision(
        agent_name="orchestrator.proposal",
        input_data={"payload": {"sku": "XPS13PLUS"}},
        retrieved_context={"memory": {}, "live": {"tenant_id": tid}},
        proposed_action={"model_choice": {"text_tier": "T1"}},
        agent_reasoning="tier_decision:T1",
        tenant_id=tid,
        event_type="DecisionProposed",
    )
    assert dec_id
    with db_session() as db:
        row = db.execute(text("SELECT tenant_id FROM decision_logs WHERE id = :id"), {"id": dec_id}).fetchone()
        assert row is not None
        assert row[0] == tid


def test_execute_or_escalate_persists_tenant_id(tmp_path):
    _ensure_decision_logs_with_tenant()
    mem = Memory(None)
    fw = TransactionFirewall({})
    orch = Orchestrator(mem, fw, {"DECISION_LOG_WRITES_ENABLED": True})

    tenant = "tenant-abc"
    rc = {"memory": {"tenant_id": tenant}, "live": {"cart_total_cents": 15000, "sku": "XPS13PLUS"}}
    proposal = {"proposal_id": str(uuid.uuid4()), "cart_total_cents": 15000, "discount_percent": 10, "reason": "test"}
    policy = {"approval_required": False}

    executed = orch.execute_or_escalate(uid="u123", proposal=proposal, policy=policy, retrieved_context=rc, simulate_only=True)
    assert executed is False  # simulate_only True forces False

    with db_session() as db:
        row = db.execute(text("SELECT tenant_id FROM decision_logs ORDER BY valid_from DESC LIMIT 1")).fetchone()
        assert row is not None
        assert row[0] == tenant
