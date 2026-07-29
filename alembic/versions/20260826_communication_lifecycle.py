"""Append-only governed communication lifecycle and grounding.

Revision ID: 20260826_communication_lifecycle
Revises: 20260825_tenant_experiment_policy
"""
from alembic import op
import sqlalchemy as sa

revision = "20260826_communication_lifecycle"
down_revision = "20260825_tenant_experiment_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "communication_observation" in tables:
        columns = {
            column["name"] for column in sa.inspect(bind).get_columns("communication_observation")
        }
        with op.batch_alter_table("communication_observation") as batch:
            if "party_ref" not in columns:
                batch.add_column(sa.Column("party_ref", sa.Text()))
            if "trace_ref" not in columns:
                batch.add_column(sa.Column("trace_ref", sa.Text()))
        op.create_index(
            "ix_communication_observation_party",
            "communication_observation", ["tenant_id", "party_ref", "observed_at"],
        )
        op.create_index(
            "ix_communication_observation_trace",
            "communication_observation", ["tenant_id", "trace_ref", "observed_at"],
        )
    if "communication_grounding" not in tables:
        op.create_table(
            "communication_grounding",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("grounding_type", sa.Text(), nullable=False),
            sa.Column("source_ref", sa.Text(), nullable=False),
            sa.Column("source_version", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("approval_status", sa.Text(), nullable=False),
            sa.Column("approved_by", sa.Text()),
            sa.Column("approved_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint(
                "tenant_id", "grounding_type", "source_ref", "source_version",
                name="uq_communication_grounding_version",
            ),
        )
    if "communication_lifecycle_event" not in tables:
        op.create_table(
            "communication_lifecycle_event",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("observation_id", sa.String(64), nullable=False),
            sa.Column("sequence_no", sa.Integer(), nullable=False),
            sa.Column("state", sa.Text(), nullable=False),
            sa.Column("actor_type", sa.Text(), nullable=False),
            sa.Column("actor_id", sa.Text()),
            sa.Column("reason", sa.Text()),
            sa.Column("grounding_refs_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("idempotency_key", sa.Text(), nullable=False),
            sa.Column("commercial_effect", sa.Text(), nullable=False, server_default="none"),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "observation_id", "idempotency_key",
                name="uq_communication_lifecycle_idempotency",
            ),
            sa.UniqueConstraint(
                "tenant_id", "observation_id", "sequence_no",
                name="uq_communication_lifecycle_sequence",
            ),
        )
        op.create_index(
            "ix_communication_lifecycle_message",
            "communication_lifecycle_event",
            ["tenant_id", "observation_id", "occurred_at"],
        )


def downgrade() -> None:
    # Retained as audit/evidence records.
    return
