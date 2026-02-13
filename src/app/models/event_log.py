from sqlalchemy import Column, Text, String
from sqlalchemy.sql.sqltypes import TIMESTAMP
from sqlalchemy.sql import func
from .orm import Base


class EventLog(Base):
    __tablename__ = "event_log"

    id = Column(String(64), primary_key=True)
    type = Column(String(128), nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    delivery_url = Column(String(512), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.current_timestamp())
    last_attempt = Column(TIMESTAMP(timezone=True), nullable=True)


def ensure_event_log_table():
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
                CREATE TABLE IF NOT EXISTS event_log (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    delivery_url TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_attempt TEXT
                )
                """
            )
            db.commit()
    except Exception:
        pass
