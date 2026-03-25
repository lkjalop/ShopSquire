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


def _emb_to_pg(embedding: List[float]) -> str:
    """Format a Python float list as a pgvector literal: '[1.0,2.0,...]'."""
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


class PgVectorStore:
    """pgvector-backed vector store.

    Expects a `vectors` table: id TEXT PRIMARY KEY, embedding VECTOR(N), payload JSONB.
    Run the alembic migration (20260325_pgvector_hnsw_indexes) before using in production.
    If the engine is unavailable the methods return {"ok": False, "reason": ...}.
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
                conn.execute(
                    text(
                        f"INSERT INTO {self.table_name} (id, embedding, payload) "
                        "VALUES (:id, :emb::vector, :payload) "
                        "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, payload = EXCLUDED.payload"
                    ),
                    {"id": id, "emb": _emb_to_pg(embedding), "payload": json.dumps(payload or {})},
                )
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def query(self, embedding: List[float], top_k: int = 5) -> Dict[str, Any]:
        if self.engine is None:
            return {"ok": False, "reason": "no_engine", "results": []}
        try:
            with self.engine.connect() as conn:
                sql = (
                    f"SELECT id, payload, embedding <-> :vec::vector AS distance "
                    f"FROM {self.table_name} ORDER BY distance ASC LIMIT :k"
                )
                rows = conn.execute(text(sql), {"vec": _emb_to_pg(embedding), "k": top_k}).fetchall()
                out = []
                for r in rows:
                    try:
                        payload = json.loads(r[1]) if isinstance(r[1], (str, bytes)) else r[1]
                    except Exception:
                        payload = r[1]
                    out.append({"id": r[0], "payload": payload, "distance": float(r[2]) if r[2] is not None else None})
                return {"ok": True, "results": out}
        except Exception as e:
            return {"ok": False, "reason": str(e), "results": []}

    def batch_index(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        if self.engine is None:
            return {"ok": False, "reason": "no_engine", "indexed": 0}
        indexed = 0
        errors = 0
        with self.engine.begin() as conn:
            for item in items or []:
                item_id = str(item.get("id") or "").strip()
                embedding = item.get("embedding")
                payload = item.get("payload") or {}
                if not item_id or not isinstance(embedding, list):
                    continue
                try:
                    conn.execute(
                        text(
                            f"INSERT INTO {self.table_name} (id, embedding, payload) "
                            "VALUES (:id, :emb::vector, :payload) "
                            "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, payload = EXCLUDED.payload"
                        ),
                        {"id": item_id, "emb": _emb_to_pg(embedding), "payload": json.dumps(payload)},
                    )
                    indexed += 1
                except Exception:
                    errors += 1
                    continue
        result: Dict[str, Any] = {"ok": True, "indexed": indexed}
        if errors:
            result["errors"] = errors
        return result

    def query_with_filter(
        self,
        embedding: List[float],
        *,
        top_k: int = 5,
        payload_filter: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        base = self.query(embedding, top_k=max(top_k * 4, top_k))
        if not base.get("ok"):
            return base
        filt = payload_filter or {}
        if not filt:
            base["results"] = (base.get("results") or [])[:top_k]
            return base
        out = []
        for row in base.get("results") or []:
            payload = row.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            matched = True
            for key, value in filt.items():
                if payload.get(key) != value:
                    matched = False
                    break
            if matched:
                out.append(row)
            if len(out) >= top_k:
                break
        return {"ok": True, "results": out}


def get_default_vector_store() -> PgVectorStore:
    return PgVectorStore()


def ensure_vector_table(table_name: str, *, dim: int = 1536) -> None:
    """Best-effort ensure a named vector table exists.

    Intended for non-critical startup/indexing paths where we want stable behavior
    across Postgres and SQLite test environments.
    """
    table = _safe_identifier(table_name, default="vectors")
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
                try:
                    conn.execute(
                        text(
                            f"CREATE TABLE IF NOT EXISTS {table} "
                            f"(id TEXT PRIMARY KEY, embedding vector({int(dim)}), payload JSONB)"
                        )
                    )
                except Exception:
                    try:
                        conn.execute(
                            text(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, embedding TEXT, payload JSONB)")
                        )
                    except Exception:
                        logging.getLogger("shopsquire.db").warning("vector table creation fallback failed: %s", table)
            else:
                try:
                    conn.execute(
                        text(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, embedding TEXT, payload TEXT)")
                    )
                except Exception:
                    logging.getLogger("shopsquire.db").warning("vector table creation failed (sqlite): %s", table)
    except Exception as e:
        logging.getLogger("shopsquire.db").warning("ensure_vector_table failed for %s: %s", table_name, str(e))


def ensure_vectors_table():
    """Best-effort ensure the `vectors` table exists.

    Creates a pgvector-backed table when running against Postgres and a
    simple fallback table for SQLite dev environments.
    """
    ensure_vector_table("vectors")
