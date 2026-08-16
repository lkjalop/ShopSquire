"""Durable, sanitized AgentRunEvent persistence.

The table is append-only at the application boundary.  Prompts, outputs,
addresses and chain-of-thought are deliberately absent from the schema.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.app.services.model_execution_gateway import (
    AgentRunEvent,
    AgentRunEventType,
    ModelDeployment,
    ModelExecutionRequest,
    sanitize_agent_event_details,
)


@dataclass
class SqlAgentRunEventLedger:
    engine: Engine

    def append(
        self,
        request: ModelExecutionRequest,
        deployment: ModelDeployment,
        event_type: AgentRunEventType,
        **details: Any,
    ) -> AgentRunEvent:
        safe = sanitize_agent_event_details(details)
        occurred_at_ms = int(time.time() * 1_000)
        with self.engine.begin() as connection:
            scope = {
                "tenant_id": request.tenant_id, "run_id": request.run_id,
            }
            connection.execute(text("""
                INSERT INTO agent_run_sequence (tenant_id, run_id, next_sequence)
                VALUES (:tenant_id, :run_id, 1)
                ON CONFLICT (tenant_id, run_id) DO NOTHING
            """), scope)
            sequence = int(connection.execute(text("""
                UPDATE agent_run_sequence
                SET next_sequence = next_sequence + 1
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                RETURNING next_sequence - 1
            """), scope).scalar_one())
            event = AgentRunEvent(
                sequence=sequence, run_id=request.run_id, tenant_id=request.tenant_id,
                event_type=event_type, occurred_at_ms=occurred_at_ms,
                deployment_id=deployment.deployment_id,
                model_artifact_id=deployment.model_artifact_id,
                prompt_id=request.prompt_id, prompt_version=request.prompt_version,
                prompt_hash=request.prompt_hash, context_hash=request.context_hash,
                policy_version=deployment.policy_version,
                details=json.loads(json.dumps(safe, default=str)),
            )
            connection.execute(text("""
                INSERT INTO agent_run_event (
                  id, tenant_id, run_id, sequence, event_type, occurred_at_ms,
                  deployment_id, model_artifact_id, prompt_id, prompt_version,
                  prompt_hash, context_hash, policy_version, details_json,
                  commercial_authority
                ) VALUES (
                  :id, :tenant_id, :run_id, :sequence, :event_type, :occurred_at_ms,
                  :deployment_id, :model_artifact_id, :prompt_id, :prompt_version,
                  :prompt_hash, :context_hash, :policy_version, :details_json, 0
                )
            """), {
                "id": f"agent-event-{uuid.uuid4().hex}",
                **event.model_dump(exclude={"details", "commercial_authority"}),
                "details_json": json.dumps(event.details, sort_keys=True),
            })
        return event

    def events_for(self, run_id: str, *, tenant_id: str) -> tuple[AgentRunEvent, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT sequence, run_id, tenant_id, event_type, occurred_at_ms,
                       deployment_id, model_artifact_id, prompt_id, prompt_version,
                       prompt_hash, context_hash, policy_version, details_json,
                       commercial_authority
                FROM agent_run_event
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                ORDER BY sequence, occurred_at_ms, id
            """), {"tenant_id": tenant_id, "run_id": run_id}).mappings().all()
        events: list[AgentRunEvent] = []
        for row in rows:
            values = dict(row)
            details_json = values.pop("details_json", "{}")
            values["details"] = json.loads(str(details_json or "{}"))
            values["commercial_authority"] = False
            events.append(AgentRunEvent.model_validate(values))
        return tuple(events)


def application_agent_run_ledger() -> SqlAgentRunEventLedger:
    """Bind runtime model events to the migrated application database."""

    from src.app.models.db import get_engine

    return SqlAgentRunEventLedger(get_engine())


__all__ = ["SqlAgentRunEventLedger", "application_agent_run_ledger"]
