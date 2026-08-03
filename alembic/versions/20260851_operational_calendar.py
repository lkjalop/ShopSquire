"""Add provider-neutral operational calendars and promise calculations.

Revision ID: 20260851_operational_calendar
Revises: 20260850_temporal_cache_binding
"""

from alembic import op
import sqlalchemy as sa


revision = "20260851_operational_calendar"
down_revision = "20260850_temporal_cache_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_calendar",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_ref", sa.Text(), nullable=False),
        sa.Column("timezone_name", sa.Text(), nullable=False),
        sa.Column("calendar_version", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "owner_type", "owner_ref", "calendar_version",
            name="uq_operational_calendar_version",
        ),
        sa.CheckConstraint(
            "owner_type IN ('supplier','supplier_facility','warehouse','carrier','operator_team')",
            name="ck_operational_calendar_owner_type",
        ),
        sa.CheckConstraint("status IN ('active','superseded')", name="ck_operational_calendar_status"),
    )
    op.create_index(
        "ix_operational_calendar_owner",
        "operational_calendar", ["tenant_id", "owner_type", "owner_ref", "status"],
    )
    op.create_table(
        "operational_calendar_interval",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("calendar_id", sa.Text(), sa.ForeignKey("operational_calendar.id"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_local", sa.Text(), nullable=False),
        sa.Column("end_local", sa.Text(), nullable=False),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_operational_interval_weekday"),
        sa.UniqueConstraint(
            "calendar_id", "weekday", "start_local", "end_local",
            name="uq_operational_calendar_interval",
        ),
    )
    op.create_table(
        "operational_calendar_exception",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("calendar_id", sa.Text(), sa.ForeignKey("operational_calendar.id"), nullable=False),
        sa.Column("local_date", sa.Text(), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("intervals_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("calendar_id", "local_date", name="uq_operational_calendar_exception"),
    )
    op.create_table(
        "supplier_response_policy",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("supplier_id", sa.Text(), nullable=False),
        sa.Column("supplier_facility_id", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("calendar_id", sa.Text(), sa.ForeignKey("operational_calendar.id"), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("acknowledgement_business_seconds", sa.Integer(), nullable=False),
        sa.Column("quote_business_seconds", sa.Integer(), nullable=False),
        sa.Column("human_decision_business_seconds", sa.Integer(), nullable=False),
        sa.Column("transmit_outside_hours", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("effective_from", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "supplier_id", "supplier_facility_id", "channel", "policy_version",
            name="uq_supplier_response_policy_version",
        ),
        sa.CheckConstraint(
            "acknowledgement_business_seconds > 0 AND quote_business_seconds > 0 "
            "AND human_decision_business_seconds > 0",
            name="ck_supplier_response_policy_positive",
        ),
        sa.CheckConstraint("status IN ('active','superseded')", name="ck_supplier_response_policy_status"),
    )
    op.create_index(
        "ix_supplier_response_policy_scope", "supplier_response_policy",
        ["tenant_id", "supplier_id", "supplier_facility_id", "channel", "status"],
    )
    op.create_table(
        "temporal_expectation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=True),
        sa.Column("calendar_version", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.Text(), nullable=False),
        sa.Column("calendar_state", sa.Text(), nullable=False),
        sa.Column("sla_clock", sa.Text(), nullable=False),
        sa.Column("transmission_state", sa.Text(), nullable=False),
        sa.Column("next_open_at", sa.Text(), nullable=True),
        sa.Column("acknowledgement_due_at", sa.Text(), nullable=True),
        sa.Column("quote_due_at", sa.Text(), nullable=True),
        sa.Column("human_decision_due_at", sa.Text(), nullable=True),
        sa.Column("dependencies_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("calculated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "subject_type", "subject_id", "policy_version", "submitted_at",
            name="uq_temporal_expectation_generation",
        ),
    )
    op.create_index(
        "ix_temporal_expectation_subject", "temporal_expectation",
        ["tenant_id", "subject_type", "subject_id", "status"],
    )
    op.create_table(
        "promise_calculation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("option_id", sa.Text(), nullable=False),
        sa.Column("calculation_version", sa.Text(), nullable=False),
        sa.Column("requested_quantity", sa.Integer(), nullable=False),
        sa.Column("requested_arrival_at", sa.Text(), nullable=False),
        sa.Column("feasibility", sa.Text(), nullable=False),
        sa.Column("confirmed_quantity", sa.Integer(), nullable=False),
        sa.Column("unknown_quantity", sa.Integer(), nullable=False),
        sa.Column("quantity_by_deadline", sa.Integer(), nullable=False),
        sa.Column("latest_viable_response_at", sa.Text(), nullable=True),
        sa.Column("earliest_arrival_at", sa.Text(), nullable=True),
        sa.Column("latest_arrival_at", sa.Text(), nullable=True),
        sa.Column("carrier_cutoff_at", sa.Text(), nullable=True),
        sa.Column("dispatch_ready_at", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.Text(), nullable=False),
        sa.Column("response_expectation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column("dependencies_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("calculated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "case_id", "option_id", "calculation_version",
            name="uq_promise_calculation_version",
        ),
        sa.CheckConstraint("feasibility IN ('met','missed','unknown')", name="ck_promise_feasibility"),
        sa.CheckConstraint("status IN ('active','superseded')", name="ck_promise_calculation_status"),
    )
    op.create_index(
        "ix_promise_calculation_case", "promise_calculation",
        ["tenant_id", "case_id", "status"],
    )
    op.create_table(
        "promise_dependency",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("promise_calculation_id", sa.Text(), sa.ForeignKey("promise_calculation.id"), nullable=False),
        sa.Column("dependency_type", sa.Text(), nullable=False),
        sa.Column("dependency_id", sa.Text(), nullable=False),
        sa.Column("dependency_version", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=True),
        sa.Column("effective_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "promise_calculation_id", "dependency_type", "dependency_id", "dependency_version",
            name="uq_promise_dependency_version",
        ),
    )
    op.create_index(
        "ix_promise_dependency_source", "promise_dependency",
        ["dependency_type", "dependency_id", "dependency_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_promise_dependency_source", table_name="promise_dependency")
    op.drop_table("promise_dependency")
    op.drop_index("ix_promise_calculation_case", table_name="promise_calculation")
    op.drop_table("promise_calculation")
    op.drop_index("ix_temporal_expectation_subject", table_name="temporal_expectation")
    op.drop_table("temporal_expectation")
    op.drop_index("ix_supplier_response_policy_scope", table_name="supplier_response_policy")
    op.drop_table("supplier_response_policy")
    op.drop_table("operational_calendar_exception")
    op.drop_table("operational_calendar_interval")
    op.drop_index("ix_operational_calendar_owner", table_name="operational_calendar")
    op.drop_table("operational_calendar")
