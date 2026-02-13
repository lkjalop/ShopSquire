"""rule domains + tenant config overrides + fusion score persistence

Revision ID: a8c1d2e3f4b5
Revises: c4bda3ab2d11
Create Date: 2026-02-09 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a8c1d2e3f4b5"
down_revision = "c4bda3ab2d11"
branch_labels = None
depends_on = None


def _dialect_name() -> str:
    bind = op.get_bind()
    return str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return bool(insp.has_table(name))


def _has_column(table: str, col_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = insp.get_columns(table)
    except Exception:
        return False
    return any(c.get("name") == col_name for c in cols or [])


def upgrade() -> None:
    # 1) rule_definitions.domain (so rules can be scoped to capabilities/domains)
    if _has_table("rule_definitions") and not _has_column("rule_definitions", "domain"):
        op.add_column("rule_definitions", sa.Column("domain", sa.Text(), nullable=True))
        try:
            op.execute(sa.text("UPDATE rule_definitions SET domain = 'recommend' WHERE domain IS NULL"))
        except Exception:
            pass
        try:
            op.create_index("ix_rule_definitions_domain", "rule_definitions", ["domain"])
        except Exception:
            pass

    # 2) tenant_config_overrides (tenant-scoped config packs)
    if not _has_table("tenant_config_overrides"):
        op.create_table(
            "tenant_config_overrides",
            sa.Column("tenant_id", sa.Text(), primary_key=True),
            sa.Column("config_key", sa.Text(), primary_key=True),
            sa.Column("value_json", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        try:
            op.create_index("ix_tenant_config_overrides_key", "tenant_config_overrides", ["config_key"])
        except Exception:
            pass

    # 3) fusion_scores (Phase 2: signal fusion persistence)
    if not _has_table("fusion_scores"):
        op.create_table(
            "fusion_scores",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=True),
            sa.Column("case_id", sa.Text(), nullable=True),
            sa.Column("source", sa.Text(), nullable=True, server_default="returns"),
            sa.Column("features_json", sa.Text(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("model_version", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        try:
            op.create_index("ix_fusion_scores_case_id", "fusion_scores", ["case_id"])
            op.create_index("ix_fusion_scores_tenant_id", "fusion_scores", ["tenant_id"])
        except Exception:
            pass


def downgrade() -> None:
    # Non-destructive
    pass

