from typing import List, Dict, Any
import os
import json
import re
from sqlalchemy import text
from src.app.models.db import get_engine
import logging


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(name: str, *, default: str = "vectors") -> str:
    cand = str(name or "").strip()
    if not _IDENT_RE.match(cand):
        return default
    return cand


class PgVectorStore:
    """Lightweight pgvector adapter scaffold.

    Expects a `vectors` table with columns: id TEXT PRIMARY KEY, embedding VECTOR, payload JSONB
    This is a scaffold: if pgvector isn't available, methods return safe placeholders.
    """

    def __init__(self, table_name: str = "vectors"):
        self.table_name = _safe_identifier(table_name, default="vectors")
        self.engine = None
        try:
            self.engine = get_engine()
        except Exception:
            self.engine = None

    def index(self, id: str, embedding: List[float], payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if self.engine is None:
            return {"ok": False, "reason": "no_engine"}
        try:
            with self.engine.begin() as conn:
                # Best-effort: use parameterized SQL and cast to vector if available
                try:
                    conn.execute(
                        text(
                            f"INSERT INTO {self.table_name} (id, embedding, payload) "
                            "VALUES (:id, :embedding, :payload) "
                            "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, payload = EXCLUDED.payload"
                        ),
                        {"id": id, "embedding": embedding, "payload": json.dumps(payload or {})},
                    )
                except Exception:
                    # Fallback: store embedding as JSON text in payload
                    conn.execute(
                        text(
                            f"INSERT INTO {self.table_name} (id, embedding, payload) "
                            "VALUES (:id, :embedding_text, :payload) "
                            "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, payload = EXCLUDED.payload"
                        ),
                        {"id": id, "embedding_text": json.dumps(embedding), "payload": json.dumps(payload or {})},
                    )
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def query(self, embedding: List[float], top_k: int = 5) -> Dict[str, Any]:
        if self.engine is None:
            return {"ok": False, "reason": "no_engine", "results": []}
        try:
            with self.engine.connect() as conn:
                # Try pgvector similarity SQL (fallback to naive payload scan if unavailable)
                try:
                    sql = f"SELECT id, payload, embedding <-> :vec AS distance FROM {self.table_name} ORDER BY distance ASC LIMIT :k"
                    rows = conn.execute(text(sql), {"vec": embedding, "k": top_k}).fetchall()
                    out = []
                    for r in rows:
                        try:
                            payload = json.loads(r[1]) if isinstance(r[1], (str, bytes)) else r[1]
                        except Exception:
                            payload = r[1]
                        out.append({"id": r[0], "payload": payload, "distance": float(r[2]) if r[2] is not None else None})
                    return {"ok": True, "results": out}
                except Exception:
                    # Fallback: return empty or simple scan
                    rows = conn.execute(
                        text(f"SELECT id, payload FROM {self.table_name} LIMIT :k"),
                        {"k": top_k},
                    ).fetchall()
                    out = []
                    for r in rows:
                        try:
                            payload = json.loads(r[1]) if isinstance(r[1], (str, bytes)) else r[1]
                        except Exception:
                            payload = r[1]
                        out.append({"id": r[0], "payload": payload, "distance": None})
                    return {"ok": True, "results": out}
        except Exception as e:
            return {"ok": False, "reason": str(e), "results": []}


def get_default_vector_store() -> PgVectorStore:
    return PgVectorStore()


def ensure_vectors_table():
    """Best-effort ensure the `vectors` table exists.

    Creates a pgvector-backed table when running against Postgres and a
    simple fallback table for SQLite dev environments.
    """
    try:
        from src.app.models.db import get_engine

        eng = get_engine()
        if eng is None:
            return
        dialect = getattr(getattr(eng, "dialect", None), "name", "") or ""
        with eng.begin() as conn:
            if "postgres" in dialect:
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                except Exception:
                    logging.getLogger("shopsquire.db").warning("pgvector extension creation failed")
                # default dimension 1536 (best-effort); migrations should customize
                try:
                    conn.execute(
                        text("CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, embedding vector(1536), payload JSONB)")
                    )
                except Exception:
                    # fallback: store embedding as JSONB text
                    try:
                        conn.execute(
                            text("CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, embedding TEXT, payload JSONB)")
                        )
                    except Exception:
                        logging.getLogger("shopsquire.db").warning("vectors table creation fallback failed")
            else:
                # SQLite fallback
                try:
                    conn.execute(
                        text("CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, embedding TEXT, payload TEXT)")
                    )
                except Exception:
                    logging.getLogger("shopsquire.db").warning("vectors table creation failed (sqlite)")
    except Exception as e:
        logging.getLogger("shopsquire.db").warning("ensure_vectors_table failed: %s", str(e))
