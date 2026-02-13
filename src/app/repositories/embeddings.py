from typing import List, Sequence
from sqlalchemy import text

# Minimal repository for pgvector-backed product embeddings
# Uses raw SQL to avoid extra dependencies. For SQLite, calls are no-ops.


def upsert_product_embedding(session, product_id: str, embedding: Sequence[float]) -> bool:
    """Insert or update a product embedding. Returns True on success.

    On Postgres with pgvector, stores the vector. On SQLite, stores nothing and returns False.
    """
    try:
        dialect = str(getattr(session.bind, "dialect", None).name).lower()
    except Exception:
        dialect = ""
    if "postgres" not in dialect:
        return False
    # Build pgvector literal: '[0.1,0.2,...]'::vector
    vec = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
    sql = (
        "INSERT INTO product_embeddings (product_id, embedding, updated_at) "
        "VALUES (:pid, " + vec + "::vector, now()) "
        "ON CONFLICT (product_id) DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = EXCLUDED.updated_at"
    )
    session.execute(text(sql), {"pid": product_id})
    session.commit()
    return True


def search_products_by_embedding(session, query_embedding: Sequence[float], top_k: int = 5) -> List[dict]:
    """Return top_k product IDs ranked by cosine distance using pgvector.

    For SQLite, returns empty list.
    """
    try:
        dialect = str(getattr(session.bind, "dialect", None).name).lower()
    except Exception:
        dialect = ""
    if "postgres" not in dialect:
        return []
    vec = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"
    # Use unqualified table names so it works with public schema (Alembic default)
    # and with environments that set search_path to oltp.
    sql = (
        "SELECT p.id as product_id, (pe.embedding <=> " + vec + "::vector) AS distance "
        "FROM products p JOIN product_embeddings pe ON pe.product_id = p.id "
        "ORDER BY distance ASC LIMIT :k"
    )
    rows = session.execute(text(sql), {"k": top_k}).mappings().all()
    return [dict(r) for r in rows]
