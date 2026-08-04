from typing import Any, Dict, List, Optional, Sequence
from sqlalchemy import text, bindparam

# Minimal repository for pgvector-backed product and session embeddings.
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

_UPSERT_EMBED_MANY_SQL = text(
    """
    INSERT INTO product_embeddings (product_id, embedding, updated_at)
    VALUES (:pid, CAST(:vec AS vector), now())
    ON CONFLICT (product_id)
    DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = EXCLUDED.updated_at
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
    # Enforce the vector(1536) contract: a wrong-length vector would fail the
    # pgvector insert (and historically aborted a whole batch). Skip + log loudly
    # instead of silently corrupting / crashing the index.
    try:
        from src.app.services.embeddings import embedding_dim
        _exp = embedding_dim()
    except Exception:
        _exp = 1536
    if len(embedding) != _exp:
        import logging
        logging.getLogger("shopsquire.embeddings").warning(
            "product_embedding dim mismatch for %s: got %d, expected %d — skipped",
            product_id, len(embedding), _exp,
        )
        try:
            from src.app.observability.metrics import record_retrieval_source
            record_retrieval_source("product_embedding", "dim_mismatch")
        except Exception:
            pass
        return False
    vec = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
    session.execute(_UPSERT_EMBED_SQL, {"pid": product_id, "vec": vec})
    session.commit()
    return True


def upsert_product_embeddings(session, items: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Batch insert/update product embeddings keyed by canonical product_id."""
    try:
        dialect = str(getattr(session.bind, "dialect", None).name).lower()
    except Exception:
        dialect = ""
    if "postgres" not in dialect:
        return {"indexed": 0, "errors": len(list(items or []))}
    indexed = 0
    errors = 0
    for item in items or []:
        product_id = str((item or {}).get("product_id") or "").strip()
        embedding = (item or {}).get("embedding")
        if not product_id or not isinstance(embedding, (list, tuple)) or not embedding:
            errors += 1
            continue
        try:
            vec = "[" + ",".join(f"{float(x):.8f}" for x in embedding) + "]"
            session.execute(_UPSERT_EMBED_MANY_SQL, {"pid": product_id, "vec": vec})
            indexed += 1
        except Exception:
            errors += 1
    session.commit()
    out = {"indexed": indexed}
    if errors:
        out["errors"] = errors
    return out


_UPSERT_SESSION_SQL = text(
    """
    INSERT INTO session_embeddings (session_id, embedding, payload, updated_at)
    VALUES (:sid, CAST(:vec AS vector), CAST(:payload AS jsonb), now())
    ON CONFLICT (session_id)
    DO UPDATE SET embedding = EXCLUDED.embedding,
                  payload = EXCLUDED.payload,
                  updated_at = EXCLUDED.updated_at
    """
)

_SEARCH_SESSION_SQL = text(
    """
    SELECT session_id, (embedding <=> CAST(:vec AS vector)) AS distance, payload
    FROM session_embeddings
    ORDER BY distance ASC
    LIMIT :k
    """
)


def upsert_session_embedding(
    session,
    session_id: str,
    embedding: Sequence[float],
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    """Insert or update a session embedding with optional JSON payload.

    Stores a dense vector summary of the session's query history for
    session-based similarity lookup and cold-start personalisation.
    No-op on SQLite — returns False.
    """
    try:
        dialect = str(getattr(session.bind, "dialect", None).name).lower()
    except Exception:
        dialect = ""
    if "postgres" not in dialect:
        return False
    import json as _json
    vec = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
    payload_str = _json.dumps(payload or {})
    session.execute(_UPSERT_SESSION_SQL, {"sid": session_id, "vec": vec, "payload": payload_str})
    session.commit()
    return True


def search_sessions_by_embedding(
    session,
    query_embedding: Sequence[float],
    top_k: int = 5,
) -> List[dict]:
    """Return top_k similar sessions by cosine distance.

    Returns list of dicts with keys: session_id, distance, payload.
    Empty list on SQLite.
    """
    try:
        dialect = str(getattr(session.bind, "dialect", None).name).lower()
    except Exception:
        dialect = ""
    if "postgres" not in dialect:
        return []
    vec = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"
    rows = session.execute(_SEARCH_SESSION_SQL, {"vec": vec, "k": top_k}).mappings().all()
    return [dict(r) for r in rows]


def search_products_by_embedding(
    session,
    query_embedding: Sequence[float],
    top_k: int = 5,
    *,
    allowed_product_ids: Sequence[str] | None = None,
) -> List[dict]:
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
    if allowed_product_ids:
        rows = session.execute(
            text(
                """
                SELECT p.id as product_id, (pe.embedding <=> CAST(:vec AS vector)) AS distance
                FROM products p
                JOIN product_embeddings pe ON pe.product_id = CAST(p.id AS TEXT)
                WHERE CAST(p.id AS TEXT) IN :ids
                ORDER BY distance ASC
                LIMIT :k
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"vec": vec, "k": top_k, "ids": [str(x) for x in allowed_product_ids if str(x).strip()]},
        ).mappings().all()
    else:
        rows = session.execute(_SEARCH_EMBED_SQL, {"vec": vec, "k": top_k}).mappings().all()
    return [dict(r) for r in rows]
