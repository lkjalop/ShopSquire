"""Add append-only governed Party redirect execution events.

Revision ID: 20260822_party_redirect_execution
Revises: 20260821_supply_graph_ops
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_party_redirect_execution"
down_revision = "20260821_supply_graph_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "identity_resolution_decision" in tables:
        # Repair rows written by the former double-prefix defect. This changes
        # only the malformed discriminator; proposal evidence and audit fields
        # remain untouched.
        op.execute(
            """
            UPDATE identity_resolution_decision
            SET decision_type='merge_proposal'
            WHERE decision_type='link:merge_proposal'
            """
        )
        op.execute(
            """
            UPDATE identity_resolution_decision
            SET decision_type='split_proposal'
            WHERE decision_type='link:split_proposal'
            """
        )
        op.execute(
            """
            UPDATE identity_resolution_decision
            SET decision_type=SUBSTR(decision_type, 6)
            WHERE decision_type LIKE 'link:link:%'
            """
        )
    if "party_redirect_event" in tables:
        return
    op.create_table(
        "party_redirect_event",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source_party_id", sa.Text(), nullable=False),
        sa.Column("target_party_id", sa.Text(), nullable=False),
        sa.Column("supersedes_event_id", sa.String(64)),
        sa.Column("graph_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("executed_by", sa.Text(), nullable=False),
        sa.Column("execution_note", sa.Text(), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["identity_resolution_decision.id"]),
        sa.ForeignKeyConstraint(["source_party_id"], ["party.id"]),
        sa.ForeignKeyConstraint(["target_party_id"], ["party.id"]),
        sa.ForeignKeyConstraint(["supersedes_event_id"], ["party_redirect_event.id"]),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key",
            name="uq_party_redirect_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_id", "graph_version",
            name="uq_party_redirect_graph_version",
        ),
    )
    op.create_index(
        "ix_party_redirect_source",
        "party_redirect_event",
        ["tenant_id", "source_party_id", "graph_version"],
    )
    op.create_index(
        "ix_party_redirect_target",
        "party_redirect_event",
        ["tenant_id", "target_party_id", "graph_version"],
    )
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_party_redirect_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'party_redirect_event_is_append_only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_party_redirect_no_update
            BEFORE UPDATE OR DELETE ON party_redirect_event
            FOR EACH ROW EXECUTE FUNCTION reject_party_redirect_mutation()
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_party_redirect_no_update
            BEFORE UPDATE ON party_redirect_event
            BEGIN
              SELECT RAISE(ABORT, 'party_redirect_event_is_append_only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_party_redirect_no_delete
            BEFORE DELETE ON party_redirect_event
            BEGIN
              SELECT RAISE(ABORT, 'party_redirect_event_is_append_only');
            END
            """
        )


def downgrade() -> None:
    # Identity executions are audit evidence and must not be erased.
    return
