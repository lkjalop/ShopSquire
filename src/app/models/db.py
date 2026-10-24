
from contextlib import contextmanager
import types
import os
import re
from sqlalchemy import create_engine
import hashlib
import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text as sql_text
from sqlalchemy.sql.elements import TextClause
from fastapi import Request
import contextvars
from src.app.config import get_settings
from threading import Lock, RLock
from weakref import WeakKeyDictionary




settings = get_settings()
db_url = settings.database_url


# Helper to register a 'now()' function on SQLite engines for compatibility
def _register_sqlite_now(engine):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_register_now(dbapi_connection, connection_record):
        try:
            dbapi_connection.create_function(
                "now", 0, lambda: __import__("datetime").datetime.utcnow().isoformat()
            )
        except Exception:
            pass


def _register_postgres_failure_observer(engine):
    """Log bounded metadata for the first failing PostgreSQL statement."""
    from sqlalchemy import event

    @event.listens_for(engine, "handle_error")
    def _pg_observe_statement_failure(exception_context):
        try:
            statement = str(exception_context.statement or "")
            fingerprint = hashlib.sha256(statement.encode("utf-8")).hexdigest()[:16]
            original = exception_context.original_exception
            logging.getLogger("shopsquire.db.statement").warning(
                "postgres_statement_failed fingerprint=%s error_type=%s error=%s",
                fingerprint,
                type(original).__name__,
                str(original).splitlines()[0][:240],
            )
        except Exception:
            pass


# Create engine using configured DATABASE_URL. If SQLite is explicitly requested,
# register compatibility helpers; otherwise, defer connectivity to callers/tests.
def _create_engine_with_fallback(url: str):
    if url and url.startswith("sqlite"):
        eng = create_engine(
            url,
            pool_pre_ping=True,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        _register_sqlite_now(eng)
        # Enable WAL journal mode and a generous busy_timeout so concurrent
        # background agents don't deadlock on the same SQLite file.
        try:
            from sqlalchemy import event as _sa_event
            @_sa_event.listens_for(eng, "connect")
            def _sqlite_wal(dbapi_conn, _rec):
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
                dbapi_conn.execute("PRAGMA busy_timeout=10000")
                dbapi_conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        return eng
    # Do not fallback silently to SQLite; always honor configured URL.
    # create_engine does not connect immediately, so this is safe even if the
    # database is not yet ready. Test bootstrap ensures readiness and schema.
    eng = create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        # Production pool sizing: 10 base + 20 overflow = 30 max connections.
        # Recycle after 30 minutes to prevent stale connections across PG restarts.
        # statement_timeout kills runaway queries so they don't hold pool slots.
        pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DB_POOL_MAX_OVERFLOW", "20")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE_SEC", "1800")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT_SEC", "30")),
        connect_args={
            # P0-3: bound the CONNECT phase too — statement_timeout only caps query EXECUTION, so a
            # down/wedged Postgres would otherwise stall every new connection (and pool_pre_ping
            # reconnect) on the OS TCP timeout (~tens of seconds), fail-slow on every request.
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT_SEC", "5")),
            "options": (
                f"-c statement_timeout={os.getenv('DB_STATEMENT_TIMEOUT_MS', '30000')}"
                f" -c idle_in_transaction_session_timeout={os.getenv('DB_IDLE_TX_TIMEOUT_MS', '60000')}"
            )
        },
    )
    # For Postgres, set a default search_path so unqualified table names
    # resolve to our logical schemas in order: oltp, audit, security, public.
    try:
        from sqlalchemy import event
        if str(eng.url).startswith("postgres") or "postgres" in str(eng.url):
            @event.listens_for(eng, "connect")
            def _pg_set_search_path(dbapi_connection, connection_record):
                try:
                    cursor = dbapi_connection.cursor()
                    cursor.execute("SET search_path TO oltp, audit, security, public")
                    # Initialise new connections. Session transactions bind tenant
                    # with SET LOCAL; a connect hook alone cannot isolate pool reuse.
                    cursor.execute("SET app.current_tenant TO ''")
                    cursor.close()
                except Exception:
                    pass
    except Exception:
        pass
    _register_postgres_failure_observer(eng)
    return eng


def create_runtime_engine(url: str):
    """Create an engine with ShopSquire's canonical bounded runtime policy."""
    return _create_engine_with_fallback(url)


engine = _create_engine_with_fallback(db_url)
# Provide a module-level SessionLocal for tests that monkeypatch it
try:
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
except Exception:
    SessionLocal = None

# ContextVar to hold the current Request during a request lifecycle so
# utility code that isn't a FastAPI dependency can still access the
# request-specific app state (notably `app.state.engine`). Middleware
# sets this before calling route handlers and resets it afterwards.
CURRENT_REQUEST: contextvars.ContextVar = contextvars.ContextVar("CURRENT_REQUEST", default=None)


def set_engine(new_engine):
    """Replace the module-level engine at runtime (tests can call this).

    Also register SQLite helpers when appropriate.
    """
    global engine
    engine = new_engine
    try:
        if "sqlite" in str(engine.url.drivername).lower():
            _register_sqlite_now(engine)
    except Exception:
        pass
    # Ensure the global SessionLocal matches the current engine to avoid
    # stale sessionmakers pointing at previous engines during tests.
    try:
        globals()["SessionLocal"] = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
    except Exception:
        pass


# Weak pool ownership avoids retaining discarded engines. A disposed engine
# receives a new pool and must initialize its replacement connections again.

_SQLITE_BOOTSTRAP_GUARD = Lock()
_SQLITE_BOOTSTRAP_STATE = WeakKeyDictionary()


def _ensure_minimal_sqlite_tables(bind):
    """Initialize legacy SQLite compatibility once per live pool, not per request.

    Production schema readiness remains migration-owned. Failed compatibility
    initialization is observable and retryable; it is never cached as success.
    """
    if bind.dialect.name != "sqlite":
        return
    with _SQLITE_BOOTSTRAP_GUARD:
        state = _SQLITE_BOOTSTRAP_STATE.get(bind.pool)
        if state is None:
            state = [RLock(), False]
            _SQLITE_BOOTSTRAP_STATE[bind.pool] = state
    with state[0]:
        if not state[1]:
            state[1] = _bootstrap_minimal_sqlite_tables(bind)


def _bootstrap_minimal_sqlite_tables(bind):
    """Initialize the ordered legacy compatibility schema; never conceal failure."""
    from src.app.models.sqlite_compatibility_schema import bootstrap_schema
    errors = []
    try:
        if "sqlite" in str(bind.dialect.name).lower():
            with bind.connect() as conn:
                bootstrap_schema(conn, errors)
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    if errors:
        logging.getLogger(__name__).warning("SQLite compatibility bootstrap incomplete: %s", sorted(set(errors)))
    return not errors


@contextmanager
def db_session():
    # Prefer a request-bound engine when available (set by middleware via
    # CURRENT_REQUEST) so reads/writes during a request use the same engine
    # instance that tests configured on app.state.engine. Fall back to the
    # module-level engine otherwise.
    try:
        eng = get_engine()
    except Exception:
        eng = engine
    try:
        req = CURRENT_REQUEST.get()
        if req is not None and hasattr(req, "app") and hasattr(req.app, "state"):
            eng_req = getattr(req.app.state, "engine", None)
            if eng_req is not None:
                eng = eng_req
    except Exception:
        eng = engine
    from src.app.models.database_ownership import current_database_engine
    owned_engine = current_database_engine()
    if owned_engine is not None:
        eng = owned_engine
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng, future=True)
    session = SessionLocal()
    from src.app.platform.tenant_session import bind_session_tenant
    bind_session_tenant(session)
    # Best-effort: ensure minimal SQLite tables exist for tests that don't apply schema
    try:
        _ensure_minimal_sqlite_tables(session.bind)
    except Exception:
        pass
    # Optional debug: print which engine URL the session is bound to
    try:
        dbg = os.getenv("DB_SESSION_DEBUG", "0")
        if str(dbg).strip() in ("1", "true", "yes"):
            import sys
            sys.stderr.write(f"[db_session] bind.url={getattr(session.bind, 'url', None)}\n")
            sys.stderr.flush()
    except Exception:
        pass
    # Wrap session.execute so tests can pass plain SQL strings (coerce to text())
    orig_execute = session.execute

    def _execute(self, statement, *args, **kwargs):
        # Accept plain strings or SQLAlchemy TextClause and normalize common Postgres functions
        # Coerce plain SQL strings or TextClause into sqlalchemy.text(),
        # and normalize Postgres now() to SQLite-compatible CURRENT_TIMESTAMP.
        import time as _time
        from src.app.observability.metrics import record_db_query_latency
        s = None
        if isinstance(statement, TextClause):
            s = str(statement)
        elif isinstance(statement, str):
            s = statement

        if s is not None:
            s = re.sub(r"\bnow\s*\(\s*\)", "CURRENT_TIMESTAMP", s, flags=re.IGNORECASE)
            statement = sql_text(s)
        start = _time.perf_counter()
        result = orig_execute(statement, *args, **kwargs)
        try:
            op = None
            if s:
                op = s.strip().split()[0].lower()
            record_db_query_latency(op or "unknown", _time.perf_counter() - start)
        except Exception:
            pass

        # Wrap result to normalize boolean-like integer columns for SQLite
        try:
            sql_str = None
            try:
                sql_str = str(statement) if isinstance(statement, str) or hasattr(statement, "text") else None
            except Exception:
                sql_str = None

            class ResultWrapper:
                def __init__(self, res, sql):
                    self._res = res
                    self._sql = (sql or "").lower()

                def __iter__(self):
                    for row in self._res:
                        yield self._convert_row(row)

                def fetchone(self):
                    row = self._res.fetchone()
                    if row is None:
                        return None
                    return self._convert_row(row)

                def mappings(self):
                    mr = self._res.mappings()

                    class MappingsWrapper:
                        def __init__(self, mapping_res, sql):
                            self._mr = mapping_res
                            self._sql = sql

                        def _convert_mapping(self, row):
                            data = dict(row)
                            for key in ("escalated", "blocked"):
                                if key in data and isinstance(data[key], int):
                                    data[key] = bool(data[key])
                            return data

                        def __iter__(self):
                            for row in self._mr:
                                yield self._convert_mapping(row)

                        def all(self):
                            return [self._convert_mapping(row) for row in self._mr.all()]

                        def __getattr__(self, name):
                            return getattr(self._mr, name)

                    return MappingsWrapper(mr, self._sql)

                def __getattr__(self, name):
                    return getattr(self._res, name)

                def _convert_row(self, row):
                    try:
                        vals = tuple(row)
                    except Exception:
                        vals = (row,)
                    # Single-column selects that include boolean-like names
                    if len(vals) == 1:
                        v = vals[0]
                        if isinstance(v, int) and v in (0, 1) and ("escalat" in self._sql or "block" in self._sql):
                            return (bool(v),)
                        return vals
                    # Multi-column: try mapping by name and convert known boolean keys
                    try:
                        if hasattr(row, "_mapping"):
                            md = dict(row._mapping)
                            for k in ("escalated", "blocked"):
                                if k in md and isinstance(md[k], int):
                                    md[k] = bool(md[k])
                            return tuple(md[k] for k in md.keys())
                    except Exception:
                        pass
                    return vals

            return ResultWrapper(result, sql_str)
        except Exception:
            return result

    session.execute = types.MethodType(_execute, session)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:
            pass


def get_engine():
    # Return the module-level engine. Tests commonly monkeypatch this object;
    # auto-replacing from DATABASE_URL here can break request/session parity.
    from src.app.models.database_ownership import current_database_engine
    owned_engine = current_database_engine()
    return owned_engine if owned_engine is not None else engine


def get_db_for_request(request: Request | None = None):
    """Return a sessionmaker-bound session using the request.app.state.engine
    if available, otherwise fall back to the module-level engine. This helper
    is intended for use as a FastAPI dependency `Depends(get_db)`.
    """
    # Prefer a SessionLocal placed on the module by tests, otherwise create one
    # bound to the configured engine or the engine stored on request.app.state.
    eng = None
    try:
        if request is not None and hasattr(request, "app") and hasattr(request.app, "state"):
            eng = getattr(request.app.state, "engine", None)
    except Exception:
        eng = None

    if eng is None:
        eng = get_engine()
    # If a request-specific engine exists, prefer creating a sessionmaker
    # bound to that engine to avoid reusing a global SessionLocal which may
    # be bound to a different engine from another test run.
    if eng is not None and request is not None:
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng, future=True)
    else:
        # Always create a fresh sessionmaker bound to eng (module engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng, future=True)
    session = SessionLocal()
    from src.app.platform.tenant_session import bind_session_tenant
    bind_session_tenant(session)
    try:
        # Ensure minimal tables exist for SQLite binds so route handlers using
        # Depends(get_db) can safely operate in test environments.
        try:
            _ensure_minimal_sqlite_tables(session.bind)
        except Exception:
            pass
        yield session
    finally:
        session.close()


def get_db(request: Request):
    """FastAPI-friendly dependency: `Depends(get_db)` or `Depends(lambda req: get_db(req))`.
    When FastAPI injects the Request object it will be passed here automatically.
    """
    # Delegate to the request-aware session generator so FastAPI
    # treats this as a dependency with teardown (yield-style).
    # Using `yield from` makes `get_db` itself a generator function.
    yield from get_db_for_request(request)


def _build_upsert_sql(dialect: str, table: str, values: dict, conflict_columns: list[str]):
    """Build a dialect-aware upsert SQL statement and parameter dict.

    - For SQLite: uses `INSERT OR REPLACE` with all columns.
    - For Postgres: uses `INSERT ... ON CONFLICT (...) DO UPDATE SET ...`.
    """
    cols = list(values.keys())
    placeholders = ", ".join([f":{c}" for c in cols])
    col_list = ", ".join(cols)
    params = dict(values)
    d = (dialect or "").lower()
    if "sqlite" in d:
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
        return sql_text(sql), params
    # Default to Postgres-style upsert when not SQLite
    conflict_list = ", ".join(conflict_columns or [])
    # Update all non-conflict columns from EXCLUDED
    update_cols = [c for c in cols if c not in (conflict_columns or [])]
    if update_cols:
        set_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
    else:
        # If no non-conflict columns, do nothing on conflict
        set_clause = None
    base = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    if conflict_list:
        if set_clause:
            sql = f"{base} ON CONFLICT ({conflict_list}) DO UPDATE SET {set_clause}"
        else:
            sql = f"{base} ON CONFLICT ({conflict_list}) DO NOTHING"
    else:
        # Without explicit conflict columns, fall back to plain insert
        sql = base
    return sql_text(sql), params


def upsert(session, table: str, values: dict, conflict_columns: list[str]):
    """Execute a dialect-aware upsert using the provided session.

    Example:
        upsert(db, "rule_definitions",
               {"id": "r1", "title": "t", "active": True},
               ["id"])
    """
    try:
        dialect = str(getattr(getattr(session.bind, "dialect", None), "name", "")).lower()
    except Exception:
        dialect = ""
    stmt, params = _build_upsert_sql(dialect, table, values, conflict_columns)
    return session.execute(stmt, params)


async def async_db_op(fn, *args, **kwargs):
    """Run a synchronous ``db_session``-based callable on the default
    executor (thread pool) so async route handlers do not block the
    event loop.

    Usage::

        result = await async_db_op(lambda db: db.execute(...).fetchall())

    The callable receives a ``db_session`` context as its first argument.
    Additional *args / **kwargs are forwarded.
    """
    import asyncio

    def _run():
        with db_session() as _db:
            return fn(_db, *args, **kwargs)

    return await asyncio.to_thread(_run)
