"""Make policy and security persistence authoritative and PostgreSQL-safe.

Revision ID: 20260828_postgres_security_schema
Revises: 20260827_party_identity_authority
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260828_postgres_security_schema"
down_revision = "20260827_party_identity_authority"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _create_index(name: str, table: str, columns: list[str]) -> None:
    op.create_index(name, table, columns, if_not_exists=True)


def upgrade() -> None:
    tables = _table_names()

    if "policy_graph_policies" not in tables:
        op.create_table(
            "policy_graph_policies",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("framework", sa.Text(), nullable=False),
            sa.Column("version", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "policy_graph_controls" not in tables:
        op.create_table(
            "policy_graph_controls",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text()),
            sa.Column("policy_id", sa.Text(), nullable=False),
            sa.Column("control_key", sa.Text(), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("severity", sa.Text(), server_default="medium"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    _create_index(
        "idx_policy_graph_controls_policy",
        "policy_graph_controls",
        ["policy_id"],
    )
    _create_index(
        "idx_policy_graph_controls_tenant_enabled",
        "policy_graph_controls",
        ["tenant_id", "enabled"],
    )

    if "policy_graph_rules" not in tables:
        op.create_table(
            "policy_graph_rules",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("control_id", sa.Text(), nullable=False),
            sa.Column("rule", sa.Text(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        )
    _create_index(
        "idx_policy_graph_rules_control",
        "policy_graph_rules",
        ["control_id"],
    )

    if "policy_graph_evaluations" not in tables:
        op.create_table(
            "policy_graph_evaluations",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("decision_id", sa.Text(), nullable=False),
            sa.Column("control_id", sa.Text(), nullable=False),
            sa.Column("result", sa.Text(), nullable=False),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index(
        "idx_policy_graph_evals_decision",
        "policy_graph_evaluations",
        ["decision_id"],
    )

    # Preserve data from the old optional SQLite schema.  The old `pg_policies`
    # and `pg_rules` names collide with PostgreSQL system views and therefore
    # were never a portable production contract.
    if op.get_bind().dialect.name == "sqlite":
        legacy_tables = _table_names()
        if "pg_policies" in legacy_tables:
            op.execute(
                """
                INSERT OR IGNORE INTO policy_graph_policies
                    (id, tenant_id, name, framework, version, enabled, created_at)
                SELECT id, tenant_id, name, framework, version, enabled, created_at
                FROM pg_policies
                """
            )
        if "pg_controls" in legacy_tables:
            legacy_control_columns = _columns("pg_controls")
            tenant_expr = "tenant_id" if "tenant_id" in legacy_control_columns else "NULL"
            op.execute(
                f"""
                INSERT OR IGNORE INTO policy_graph_controls
                    (id, tenant_id, policy_id, control_key, description, severity, enabled)
                SELECT id, {tenant_expr}, policy_id, control_key, description, severity, enabled
                FROM pg_controls
                """
            )
        if "pg_rules" in legacy_tables:
            op.execute(
                """
                INSERT OR IGNORE INTO policy_graph_rules
                    (id, control_id, rule, priority)
                SELECT id, control_id, rule, priority FROM pg_rules
                """
            )
        if "pg_evaluations" in legacy_tables:
            op.execute(
                """
                INSERT OR IGNORE INTO policy_graph_evaluations
                    (id, decision_id, control_id, result, evaluated_at)
                SELECT id, decision_id, control_id, result, evaluated_at
                FROM pg_evaluations
                """
            )

    tables = _table_names()
    if "security_observer_timeseries" in tables and "id" not in _columns(
        "security_observer_timeseries"
    ):
        op.add_column("security_observer_timeseries", sa.Column("id", sa.Text()))

    if "security_events" in tables:
        existing = _columns("security_events")
        for name in (
            "ground_truth",
            "analyst_verdict",
            "correction_ts",
            "correction_notes",
        ):
            if name not in existing:
                op.add_column("security_events", sa.Column(name, sa.Text()))


def downgrade() -> None:
    # Policy and security evidence are intentionally retained on rollback.
    pass
