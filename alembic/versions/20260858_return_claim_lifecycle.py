"""Add tenant-scoped return claims, encrypted evidence custody and lifecycle events.

Revision ID: 20260858_return_claims
Revises: 20260857_cache_eviction
"""

from alembic import op
import sqlalchemy as sa


revision = "20260858_return_claims"
down_revision = "20260857_cache_eviction"
branch_labels = None
depends_on = None


_CLAIM_STATES = (
    "'received','evidence_pending','needs_info','under_review','approved',"
    "'repair_authorized','in_transit','received_at_facility','repair_in_progress',"
    "'repaired','replacement_sent','refund_pending','refunded','rejected','closed'"
)


def upgrade() -> None:
    op.create_table(
        "return_claim",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("claimant_id", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text()),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("status_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description_sanitized", sa.Text()),
        sa.Column("order_verification_status", sa.Text(), nullable=False),
        sa.Column("abuse_status", sa.Text(), nullable=False, server_default="allowed"),
        sa.Column("abuse_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(f"status IN ({_CLAIM_STATES})", name="ck_return_claim_status"),
        sa.CheckConstraint(
            "order_verification_status IN ('found','not_found','source_unavailable')",
            name="ck_return_claim_order_verification",
        ),
        sa.CheckConstraint(
            "abuse_status IN ('allowed','review_required')",
            name="ck_return_claim_abuse_status",
        ),
        sa.UniqueConstraint(
            "tenant_id", "claimant_id", "idempotency_key",
            name="uq_return_claim_intake_idempotency",
        ),
    )
    op.create_index(
        "ix_return_claim_owner",
        "return_claim",
        ["tenant_id", "claimant_id", "updated_at"],
    )
    op.create_table(
        "return_claim_event",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text()),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.Text()),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["return_claim.id"]),
        sa.UniqueConstraint("tenant_id", "claim_id", "sequence", name="uq_return_claim_event_seq"),
    )
    op.create_index(
        "ix_return_claim_event_timeline",
        "return_claim_event",
        ["tenant_id", "claim_id", "sequence"],
    )
    op.create_table(
        "return_evidence_object",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text()),
        sa.Column("original_name_sanitized", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("cipher", sa.Text(), nullable=False),
        sa.Column("encryption_key_id", sa.Text(), nullable=False),
        sa.Column("retention_until", sa.Text(), nullable=False),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["return_claim.id"]),
        sa.UniqueConstraint("tenant_id", "object_key", name="uq_return_evidence_object_key"),
    )
    op.create_index(
        "ix_return_evidence_retention",
        "return_evidence_object",
        ["tenant_id", "legal_hold", "retention_until"],
    )
    op.create_table(
        "return_evidence_observation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column("observation_type", sa.Text(), nullable=False),
        sa.Column("sanitized_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["return_claim.id"]),
        # Deliberately no FK to the raw object: sanitized observations may outlive
        # raw evidence after its retention period, subject to tenant policy.
    )
    op.create_table(
        "return_evidence_job",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("security_status", sa.Text(), nullable=False),
        sa.Column("visual_status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()),
        sa.Column("finished_at", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.ForeignKeyConstraint(["claim_id"], ["return_claim.id"]),
        sa.UniqueConstraint("tenant_id", "claim_id", name="uq_return_evidence_job_claim"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','degraded','quarantined','failed')",
            name="ck_return_evidence_job_status",
        ),
    )
    op.create_table(
        "return_evidence_access_audit",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Text()),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("return_evidence_access_audit")
    op.drop_table("return_evidence_job")
    op.drop_table("return_evidence_observation")
    op.drop_index("ix_return_evidence_retention", table_name="return_evidence_object")
    op.drop_table("return_evidence_object")
    op.drop_index("ix_return_claim_event_timeline", table_name="return_claim_event")
    op.drop_table("return_claim_event")
    op.drop_index("ix_return_claim_owner", table_name="return_claim")
    op.drop_table("return_claim")
