from sqlalchemy import create_engine, text

from src.app.services.agent_run_event_store import SqlAgentRunEventLedger
from src.app.services.model_execution_gateway import (
    ModelDeployment,
    ModelExecutionRequest,
    sha256_text,
)


def _schema(engine):
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE agent_run_sequence (
              tenant_id TEXT NOT NULL, run_id TEXT NOT NULL,
              next_sequence INTEGER NOT NULL,
              PRIMARY KEY (tenant_id, run_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE agent_run_event (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, run_id TEXT NOT NULL,
              sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
              occurred_at_ms BIGINT NOT NULL, deployment_id TEXT NOT NULL,
              model_artifact_id TEXT NOT NULL, prompt_id TEXT NOT NULL,
              prompt_version TEXT NOT NULL, prompt_hash TEXT NOT NULL,
              context_hash TEXT NOT NULL, policy_version TEXT NOT NULL,
              details_json TEXT NOT NULL, commercial_authority BOOLEAN NOT NULL DEFAULT 0
            )
        """))


def test_agent_events_survive_ledger_recreation_and_never_store_raw_pii(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'events.db'}")
    _schema(engine)
    deployment = ModelDeployment(
        deployment_id="local-qwen", provider="ollama",
        endpoint="http://127.0.0.1:11434/api/generate",
        endpoint_identity="127.0.0.1", model_artifact_id="qwen3:14b@sha256:a",
        model_artifact_digest="a" * 64, artifact_verification_status="verified",
        jurisdiction="local", locality="loopback", allowed_roles={"query_planner"},
        allowed_data_classes={"buyer_workload"}, retention_policy="none",
        training_policy="disabled", policy_version="v1",
    )
    request = ModelExecutionRequest(
        run_id="run-1", tenant_id="tenant-a", purpose="query_planning",
        role="query_planner", deployment_id="local-qwen",
        model_artifact_id=deployment.model_artifact_id,
        prompt_id="open-world-query", prompt_version="v1",
        prompt_hash=sha256_text("private prompt"), context_hash=sha256_text("case"),
        data_classes={"buyer_workload"},
    )
    first = SqlAgentRunEventLedger(engine)
    first.append(
        request, deployment, "accepted", prompt="private prompt",
        nested={"buyer_address": "1 Secret St", "email": "buyer@example.com"},
    )
    second = SqlAgentRunEventLedger(engine)
    events = second.events_for("run-1", tenant_id="tenant-a")

    assert len(events) == 1 and events[0].sequence == 1
    assert "prompt" not in events[0].details
    assert "buyer_address" not in events[0].details["nested"]
    assert "buyer@example.com" not in str(events[0].details)
    with engine.connect() as connection:
        raw = str(connection.execute(text(
            "SELECT details_json FROM agent_run_event"
        )).scalar_one())
    assert "private prompt" not in raw and "1 Secret St" not in raw
