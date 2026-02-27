from typing import List, Sequence
from sqlalchemy import text

# Minimal repository for pgvector-backed product embeddings
# Uses raw SQL to avoid extra dependencies. For SQLite, calls are no-ops.

_UPSERT_EMBED_SQL = text(
    """
    INSERT INTO product_embeddings (product_id, embedding, updated_at)
    VALUES (:pid, CAST(:vec AS vector), now())
    ON CONFLICT (product_id)
    DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = EXCLUDED.updated_at
    """
)

_SEARCH_EMBED_SQL = text(
    """
    SELECT p.id as product_id, (pe.embedding <=> CAST(:vec AS vector)) AS distance
    FROM products p
    JOIN product_embeddings pe ON pe.product_id = p.id
    ORDER BY distance ASC
    LIMIT :k
    """
)


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
    vec = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
    session.execute(_UPSERT_EMBED_SQL, {"pid": product_id, "vec": vec})
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
    rows = session.execute(_SEARCH_EMBED_SQL, {"vec": vec, "k": top_k}).mappings().all()
    return [dict(r) for r in rows]
