"""add faq_vectors table for semantic faq search

Revision ID: 20260325_add_faq_vectors
Revises: 20260325_pgvector_hnsw
Create Date: 2026-03-25
"""

from alembic import op


revision = "20260325_add_faq_vectors"
down_revision = "20260325_pgvector_hnsw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if "postgres" in dialect:
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:
            pass
        try:
            op.execute(
                """
                CREATE TABLE IF NOT EXISTS faq_vectors (
                    id TEXT PRIMARY KEY,
                    embedding vector(1536),
                    payload JSONB
                )
                """
            )
        except Exception:
            op.execute(
                """
                CREATE TABLE IF NOT EXISTS faq_vectors (
                    id TEXT PRIMARY KEY,
                    embedding TEXT,
                    payload JSONB
                )
                """
            )
        try:
            op.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_faq_vectors_hnsw
                ON faq_vectors
                USING hnsw (embedding vector_cosine_ops)
                """
            )
        except Exception:
            pass
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
    try:
        op.execute("DROP INDEX IF EXISTS idx_faq_vectors_hnsw")
    except Exception:
        pass
    op.execute("DROP TABLE IF EXISTS faq_vectors")
