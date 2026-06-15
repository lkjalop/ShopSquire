"""Service tables completion — tables that were runtime-created but missing from Alembic

Revision ID: 20260608_svc_tables
Revises: 20260608_prod_schema
Create Date: 2026-06-08

Why: Several service modules create their own tables at runtime via CREATE TABLE IF NOT EXISTS.
This works but means:
  - Schema drift is untracked (no migration history)
  - Parallel worker startup races on first boot
  - Downgrade is impossible

Tables added here:
  1. threat_intel_cache      — threat_intel_url.py URL verdict cache
  2. threat_intel_events     — threat_intel_url.py event log
  3. email_security_policy_pack_releases — policy_pack_release.py audit trail
  4. trusted_supplier_domains — supplier_domain_guard.py BEC validation
  5. qr_redirect_cache       — support_complaints.py QR dedup cache
  6. risk_register_snapshots — admin_grc.py risk register history
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260608_svc_tables"
down_revision = "20260608_prod_schema"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return bool(insp.has_table(name))


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return any(i.get("name") == name for i in insp.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    # ── 1. threat_intel_cache ────────────────────────────────────────────────
    if not _has_table("threat_intel_cache"):
        op.create_table(
            "threat_intel_cache",
            sa.Column("url_hash", sa.Text(), primary_key=True),
            sa.Column("url_prefix", sa.Text(), nullable=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("queried_at", sa.BigInteger(), nullable=False),
            sa.Column("expires_at", sa.BigInteger(), nullable=False),
        )
        op.create_index("ix_threat_intel_cache_expires_at", "threat_intel_cache", ["expires_at"])

    # ── 2. threat_intel_events ───────────────────────────────────────────────
    if not _has_table("threat_intel_events"):
        op.create_table(
            "threat_intel_events",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("url_prefix", sa.Text(), nullable=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("malicious", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("detail_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
        )
        op.create_index("ix_threat_intel_events_created_at", "threat_intel_events", ["created_at"])
        op.create_index("ix_threat_intel_events_malicious", "threat_intel_events", ["malicious"])

    # ── 3. email_security_policy_pack_releases ───────────────────────────────
    if not _has_table("email_security_policy_pack_releases"):
        op.create_table(
            "email_security_policy_pack_releases",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("version", sa.Text(), nullable=False),
            sa.Column("manifest_hash", sa.Text(), nullable=False),
            sa.Column("manifest_json", sa.Text(), nullable=False),
            sa.Column("release_notes_json", sa.Text(), nullable=False),
            sa.Column("signature_json", sa.Text(), nullable=False),
            sa.Column("signer", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index(
            "ix_email_security_policy_pack_releases_version",
            "email_security_policy_pack_releases",
            ["version"],
        )

    # ── 4. trusted_supplier_domains ─────────────────────────────────────────
    if not _has_table("trusted_supplier_domains"):
        op.create_table(
            "trusted_supplier_domains",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("domain", sa.Text(), nullable=False),
            sa.Column("supplier_id", sa.Text(), nullable=True),
            sa.Column("added_by", sa.Text(), nullable=True),
            sa.Column("added_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("active", sa.Integer(), nullable=True, server_default="1"),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_trusted_supplier_domains_domain", "trusted_supplier_domains", ["domain"], unique=True)
        op.create_index("ix_trusted_supplier_domains_active", "trusted_supplier_domains", ["active"])

    # ── 5. qr_redirect_cache ─────────────────────────────────────────────────
    if not _has_table("qr_redirect_cache"):
        op.create_table(
            "qr_redirect_cache",
            sa.Column("url_hash", sa.Text(), primary_key=True),
            sa.Column("url_prefix", sa.Text(), nullable=True),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.Integer(), nullable=False),
        )
        op.create_index("ix_qr_redirect_cache_expires_at", "qr_redirect_cache", ["expires_at"])

    # ── 6. risk_register_snapshots ───────────────────────────────────────────
    if not _has_table("risk_register_snapshots"):
        op.create_table(
            "risk_register_snapshots",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("domain", sa.Text(), nullable=False),
            sa.Column("risk_score", sa.Float(), nullable=False),
            sa.Column("risk_band", sa.Text(), nullable=False),
            sa.Column("snapshot_date", sa.Text(), nullable=False),
            sa.Column("risk_owner", sa.Text(), nullable=True),
            sa.Column("mitigation_strategy", sa.Text(), nullable=True),
            sa.Column("mitigation_deadline", sa.Text(), nullable=True),
            sa.Column("residual_risk_score", sa.Float(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="open"),
            sa.Column("signals_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_risk_register_snapshots_domain", "risk_register_snapshots", ["domain"])
        op.create_index("ix_risk_register_snapshots_snapshot_date", "risk_register_snapshots", ["snapshot_date"])
        op.create_index("ix_risk_register_snapshots_status", "risk_register_snapshots", ["status"])


def downgrade() -> None:
    for tbl in [
        "risk_register_snapshots",
        "qr_redirect_cache",
        "trusted_supplier_domains",
        "email_security_policy_pack_releases",
        "threat_intel_events",
        "threat_intel_cache",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
