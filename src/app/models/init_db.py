from src.app.models.db import engine
from src.app.models.orm import Base


def ensure_metadata() -> None:
    # Alembic is the source of truth for non-SQLite databases. Keep `create_all`
    # as a lightweight bootstrap for SQLite-only test/dev environments.
    try:
        if getattr(engine, "dialect", None) is not None and engine.dialect.name != "sqlite":
            return
    except Exception:
        # If dialect detection fails, fall back to best-effort below.
        pass
    try:
        Base.metadata.create_all(engine)
    except Exception:
        # Best-effort for SQLite-only environments.
        pass
    try:
        from src.app.models.db import _ensure_minimal_sqlite_tables

        _ensure_minimal_sqlite_tables(engine)
    except Exception:
        pass
    try:
        # Ensure vectors table exists for pgvector-backed embeddings
        from src.app.services.vector_store import ensure_vectors_table

        ensure_vectors_table()
    except Exception:
        pass
