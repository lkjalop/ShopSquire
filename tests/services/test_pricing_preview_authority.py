"""A pricing suggestion is not a receipt for a commercial mutation."""
import uuid

import pytest
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.firewall import TransactionFirewall
from src.app.services.memory import Memory
from src.app.services.orchestrator import Orchestrator


@pytest.mark.parametrize("writes", [False, True])
@pytest.mark.parametrize("simulate", [False, True])
@pytest.mark.parametrize("approval", [False, True])
def test_recording_a_proposal_never_reports_an_unperformed_price_change(writes, simulate, approval):
    uid = "owned-price-preview-" + uuid.uuid4().hex
    orch = Orchestrator(Memory(None), TransactionFirewall({}), {
        "DECISION_LOG_WRITES_ENABLED": writes, "POLICY_VERSION": "v1",
    })
    proposal = {"proposal_id": uuid.uuid4().hex, "cart_total_cents": 49_00,
                "discount_percent": 0, "reason": "read-only preview"}
    executed = orch.execute_or_escalate(
        uid, proposal, {"allowed": True, "approval_required": approval},
        retrieved_context={"live": {"tenant_id": "default"}}, simulate_only=simulate,
    )
    assert executed is False
    if writes:
        with db_session() as db:
            # Subjects are hashed in durable evidence; the proposal ID gives a
            # stable, non-sensitive correlation for this owned test record.
            rows = db.execute(text(
                "SELECT execution_status FROM decision_logs WHERE proposed_action LIKE :proposal"
            ), {"proposal": "%" + proposal["proposal_id"] + "%"}).all()
        assert rows
        assert all(row[0] in {"planned", "pending", "review_required"} for row in rows)
