"""enforce pgvector extension and product embedding indexes

Revision ID: 20260325_pgvector_hnsw
Revises: 20260310_add_order_warranty_fields
Create Date: 2026-03-25
"""

from alembic import op


revision = "20260325_pgvector_hnsw"
down_revision = "20260310_add_order_warranty_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if "postgres" not in dialect:
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS product_embeddings (
            product_id TEXT PRIMARY KEY,
            embedding vector(1536),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    try:
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_product_embeddings_hnsw
            ON product_embeddings
            USING hnsw (embedding vector_cosine_ops)
            """
        )
    except Exception:
        # Older pgvector versions may not support HNSW yet.
        pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if "postgres" not in dialect:
        return
    try:
        op.execute("DROP INDEX IF EXISTS idx_product_embeddings_hnsw")
    except Exception:
        pass
