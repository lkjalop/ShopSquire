"""add canonical vector tables, anomaly history, and vuln scorecards

Revision ID: 20260325_prod_tasks_and_vectors
Revises: 20260325_add_faq_vectors
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_prod_tasks_and_vectors"
down_revision = "20260325_add_faq_vectors"
branch_labels = None
depends_on = None


def _create_vector_table(name: str, *, vector_enabled: bool, postgres: bool) -> None:
    payload_type = "JSONB" if postgres else "TEXT"
    if vector_enabled:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {name} (
                id TEXT PRIMARY KEY,
                embedding vector(1536),
                payload {payload_type}
            )
            """
        )
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{name}_hnsw
            ON {name}
            USING hnsw (embedding vector_cosine_ops)
            """
        )
    else:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {name} (
                id TEXT PRIMARY KEY,
                embedding TEXT,
                payload {payload_type}
            )
            """
        )


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()

    postgres = "postgres" in dialect
    vector_enabled = False
    if postgres:
        vector_enabled = bool(bind.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
        )).scalar())
    if postgres and not vector_enabled:
        try:
            with bind.begin_nested():
                bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            pass
        vector_enabled = bool(bind.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
        )).scalar())

    _create_vector_table("faq_embeddings", vector_enabled=vector_enabled, postgres=postgres)
    _create_vector_table("session_embeddings", vector_enabled=vector_enabled, postgres=postgres)

    op.execute(
        """
        INSERT INTO faq_embeddings (id, embedding, payload)
        SELECT id, embedding, payload
        FROM faq_vectors
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS anomaly_metric_history (
            metric_name TEXT NOT NULL,
            metric_value DOUBLE PRECISION NOT NULL,
            snapshot_ts TIMESTAMP NOT NULL,
            PRIMARY KEY (metric_name, snapshot_ts)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_anomaly_metric_history_name_ts
        ON anomaly_metric_history (metric_name, snapshot_ts DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_scan_scorecards (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            profile TEXT,
            target TEXT,
            risk_score DOUBLE PRECISION,
            total_findings INTEGER DEFAULT 0,
            critical_count INTEGER DEFAULT 0,
            high_count INTEGER DEFAULT 0,
            summary_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_security_scan_scorecards_tenant_created
        ON security_scan_scorecards (tenant_id, created_at DESC)
        """
    )


def downgrade() -> None:
    for stmt in (
        "DROP INDEX IF EXISTS idx_security_scan_scorecards_tenant_created",
        "DROP TABLE IF EXISTS security_scan_scorecards",
        "DROP INDEX IF EXISTS idx_anomaly_metric_history_name_ts",
        "DROP TABLE IF EXISTS anomaly_metric_history",
        "DROP INDEX IF EXISTS idx_session_embeddings_hnsw",
        "DROP TABLE IF EXISTS session_embeddings",
        "DROP INDEX IF EXISTS idx_faq_embeddings_hnsw",
        "DROP TABLE IF EXISTS faq_embeddings",
    ):
        try:
            op.execute(stmt)
        except Exception:
            pass
