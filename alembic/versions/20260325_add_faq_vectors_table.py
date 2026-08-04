"""add faq_vectors table for semantic faq search

Revision ID: 20260325_add_faq_vectors
Revises: 20260325_pgvector_hnsw
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_add_faq_vectors"
down_revision = "20260325_pgvector_hnsw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if "postgres" in dialect:
        vector_enabled = bool(bind.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
        )).scalar())
        if not vector_enabled:
            # Extension installation can be unavailable or forbidden on managed
            # Postgres. Isolate that optional attempt in a savepoint so failure
            # cannot poison the surrounding Alembic transaction.
            try:
                with bind.begin_nested():
                    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception:
                pass
            vector_enabled = bool(bind.execute(sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
            )).scalar())
        if vector_enabled:
            op.execute(
                """
                CREATE TABLE IF NOT EXISTS faq_vectors (
                    id TEXT PRIMARY KEY,
                    embedding vector(1536),
                    payload JSONB
                )
                """
            )
            op.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_faq_vectors_hnsw
                ON faq_vectors
                USING hnsw (embedding vector_cosine_ops)
                """
            )
        else:
            op.execute(
                """
                CREATE TABLE IF NOT EXISTS faq_vectors (
                    id TEXT PRIMARY KEY,
                    embedding TEXT,
                    payload JSONB
                )
                """
            )
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS faq_vectors (
            id TEXT PRIMARY KEY,
            embedding TEXT,
            payload TEXT
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_faq_vectors_hnsw")
    op.execute("DROP TABLE IF EXISTS faq_vectors")
