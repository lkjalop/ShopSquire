"""timescale continuous aggregate for security attack trends

Revision ID: a9b7c5d3e1f0
Revises: f4a8c2d6e0b1
Create Date: 2026-02-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a9b7c5d3e1f0"
down_revision = "f4a8c2d6e0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if dialect != "postgresql":
        return

    # This migration is optional: it requires the TimescaleDB extension. The default
    # Docker stack uses plain Postgres, so skip cleanly when the extension isn't
    # available to avoid aborting the Alembic transaction.
    try:
        has_timescaledb = bool(
            bind.execute(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='timescaledb')"
                )
            ).scalar()
        )
    except Exception:
        has_timescaledb = False
    if not has_timescaledb:
        return

    # Install if available but not yet installed. Run out-of-transaction to avoid
    # breaking the Alembic migration transaction on extension DDL errors.
    try:
        is_installed = bool(
            bind.execute(
                sa.text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb')")
            ).scalar()
        )
    except Exception:
        is_installed = False
    if not is_installed:
        try:
            bind.execution_options(isolation_level="AUTOCOMMIT").execute(
                sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb")
            )
        except Exception:
            return

    insp = sa.inspect(bind)
    if not insp.has_table("security_events"):
        return

    # Ensure a lightweight index exists for raw-event fallback/time-window scans.
    try:
        op.execute("CREATE INDEX IF NOT EXISTS ix_security_events_event_time ON security_events (event_time)")
    except Exception:
        pass

    # Recreate derived aggregate view in an idempotent way.
    try:
        op.execute("DROP MATERIALIZED VIEW IF EXISTS security_attacks_hourly")
    except Exception:
        pass

    op.execute(
        """
        CREATE MATERIALIZED VIEW security_attacks_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(
                INTERVAL '1 hour',
                COALESCE(NULLIF(event_time::text, '')::timestamptz, NOW())
            ) AS bucket,
            CASE
                WHEN lower(COALESCE(details::text, '')) LIKE '%prompt_injection%' THEN 'prompt_injection'
                WHEN lower(COALESCE(details::text, '')) LIKE '%social_engineering%'
                  OR lower(COALESCE(details::text, '')) LIKE '%authority_impersonation%' THEN 'email_bec'
                WHEN lower(COALESCE(details::text, '')) LIKE '%supply_chain%'
                  OR lower(COALESCE(details::text, '')) LIKE '%training_poisoning%'
                  OR lower(COALESCE(details::text, '')) LIKE '%poisoning_attempt%' THEN 'supply_chain'
                WHEN lower(COALESCE(details::text, '')) LIKE '%identity_abuse%'
                  OR lower(COALESCE(details::text, '')) LIKE '%ip_risk%'
                  OR lower(COALESCE(details::text, '')) LIKE '%geo_country_mismatch%' THEN 'iam_compromise'
                WHEN lower(COALESCE(details::text, '')) LIKE '%data_exfiltration%'
                  OR lower(COALESCE(details::text, '')) LIKE '%"pii": true%'
                  OR lower(COALESCE(details::text, '')) LIKE '%"pci": true%' THEN 'data_exfiltration'
                WHEN lower(COALESCE(path, '')) LIKE '%email%' THEN 'email_security'
                WHEN lower(COALESCE(path, '')) LIKE '%cv%'
                  OR lower(COALESCE(path, '')) LIKE '%returns%' THEN 'cv_fraud'
                ELSE 'other'
            END AS security_type,
            CASE
                WHEN COALESCE(details::text, '') LIKE '%AML.T0043%' THEN 'AML.T0043'
                WHEN COALESCE(details::text, '') LIKE '%AML.T0048%' THEN 'AML.T0048'
                WHEN COALESCE(details::text, '') LIKE '%AML.T0020%' THEN 'AML.T0020'
                ELSE 'generic'
            END AS threat,
            CASE
                WHEN lower(COALESCE(path, '')) LIKE '%email%' THEN 'email'
                WHEN lower(COALESCE(path, '')) LIKE '%cv%'
                  OR lower(COALESCE(path, '')) LIKE '%returns%' THEN 'image_ocr'
                WHEN lower(COALESCE(path, '')) LIKE '%/admin%' THEN 'admin_api'
                WHEN lower(COALESCE(path, '')) LIKE '%/api/%' THEN 'api'
                WHEN lower(COALESCE(path, '')) LIKE '%/ui/%' THEN 'web_ui'
                WHEN lower(COALESCE(details::text, '')) LIKE '%mcp.tool.invoked%' THEN 'agent_tool'
                ELSE 'unknown'
            END AS vector,
            COUNT(*)::bigint AS count
        FROM security_events
        GROUP BY 1, 2, 3, 4
        WITH NO DATA
        """
    )

    try:
        op.execute(
            """
            SELECT add_continuous_aggregate_policy(
                'security_attacks_hourly',
                start_offset => INTERVAL '30 days',
                end_offset => INTERVAL '1 hour',
                schedule_interval => INTERVAL '15 minutes'
            )
            """
        )
    except Exception:
        pass

    try:
        op.execute(
            """
            CALL refresh_continuous_aggregate(
                'security_attacks_hourly',
                NOW() - INTERVAL '30 days',
                NOW()
            )
            """
        )
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if dialect != "postgresql":
        return
    try:
        op.execute("SELECT remove_continuous_aggregate_policy('security_attacks_hourly')")
    except Exception:
        pass
    try:
        op.execute("DROP MATERIALIZED VIEW IF EXISTS security_attacks_hourly")
    except Exception:
        pass
