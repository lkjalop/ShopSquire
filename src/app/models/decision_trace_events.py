from sqlalchemy import Column, String, Text, Integer
from sqlalchemy.sql.sqltypes import TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy import text as sql_text
from .orm import Base


class DecisionTraceEvent(Base):
    __tablename__ = "decision_trace_events"

    id = Column(String(64), primary_key=True)
    seq = Column(Integer, nullable=True)
    trace_id = Column(String(64), nullable=False)
    event_type = Column(String(64), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=True)
    target_type = Column(String(32), nullable=True)
    target_id = Column(String(128), nullable=True)
    payload = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.current_timestamp())


def ensure_decision_trace_events_table():
    try:
        from src.app.models.db import get_engine

        eng = get_engine()
        try:
            if getattr(eng, "dialect", None) is not None and eng.dialect.name != "sqlite":
                return
        except Exception:
            pass
        from src.app.models.db import db_session
        with db_session() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_trace_events (
                    id TEXT PRIMARY KEY,
                    seq INTEGER,
                    trace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    target_type TEXT,
                    target_id TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Add seq column if missing
            try:
                db.execute(sql_text("ALTER TABLE decision_trace_events ADD COLUMN seq INTEGER"))
            except Exception:
                pass
            # Read-path indexes: with ~70k rows and NO secondary index, every campaign-correlator
            # query (event_type + created_at, measured 121ms per security scan) and every
            # DecisionTrace-panel read (trace_id) was a full-table scan.
            for _idx in (
                "CREATE INDEX IF NOT EXISTS ix_dte_type_created ON decision_trace_events(event_type, created_at)",
                "CREATE INDEX IF NOT EXISTS ix_dte_trace ON decision_trace_events(trace_id)",
            ):
                try:
                    db.execute(sql_text(_idx))
                except Exception:
                    pass
            db.commit()
    except Exception:
        pass
