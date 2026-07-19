"""enforce pgvector extension and product embedding indexes

Revision ID: 20260325_pgvector_hnsw
Revises: 20260310_order_warranty_fields
Create Date: 2026-03-25
"""

import sqlalchemy as sa
from alembic import op


revision = "20260325_pgvector_hnsw"
down_revision = "20260310_order_warranty_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if "postgres" not in dialect:
        return
    # Vector search is OFF by default (VECTOR_SEARCH_ENABLED=0). A managed Postgres (RDS/CloudSQL)
    # without pgvector must not HARD-FAIL the whole migration on this off-by-default feature. PROBE
    # the extension READ-ONLY first (a failed CREATE EXTENSION would abort the migration transaction —
    # the same pattern 20260210 already uses); skip the vector DDL if unavailable. (The compose image
    # pgvector/pgvector:pg16 always has it, so this only affects bring-your-own managed PG.)
    # pg_available_extensions tells us if CREATE EXTENSION vector WOULD succeed (read-only, no txn
    # poison) — distinguishing "available but not yet created" (compose pgvector image, fresh) from
    # "not installed on the server" (managed PG without pgvector). Only attempt CREATE when available.
    try:
        available = bool(bind.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='vector')")).scalar())
    except Exception:
        available = False
    if not available:
        import logging
        logging.getLogger("alembic.pgvector").warning(
            "pgvector not available on this Postgres — skipping product_embeddings vector table/index. "
            "Enable pgvector on the DB server before turning on VECTOR_SEARCH_ENABLED.")
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
    # 20260210 could create a TEXT fallback when pgvector was available on the
    # server but not installed in this database yet. Converge that historical
    # layout before building a vector operator-class index.
    column_type = bind.execute(sa.text(
        """
        SELECT udt_name
        FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='product_embeddings'
          AND column_name='embedding'
        """
    )).scalar()
    if str(column_type or "").lower() != "vector":
        op.execute(
            """
            ALTER TABLE product_embeddings
            ALTER COLUMN embedding TYPE vector(1536)
            USING CASE
                WHEN embedding IS NULL OR btrim(embedding::text) = '' THEN NULL
                ELSE embedding::text::vector(1536)
            END
            """
        )
    # Do not catch PostgreSQL DDL errors inside Alembic's transaction. A caught
    # error still leaves the transaction aborted, so the migration appears to
    # continue and then fails while updating alembic_version. pgvector-backed
    # deployments require this index; incompatible versions must fail loudly.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_product_embeddings_hnsw
        ON product_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if "postgres" not in dialect:
        return
    try:
        op.execute("DROP INDEX IF EXISTS idx_product_embeddings_hnsw")
    except Exception:
        pass
