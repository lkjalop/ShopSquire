from sqlalchemy import Column, String, Text
from sqlalchemy.sql import func, text as sql_text
from sqlalchemy.sql.sqltypes import TIMESTAMP
from .orm import Base


class DecisionAudit(Base):
    __tablename__ = "decision_audits"

    # Use cross-dialect friendly types so SQLite tests work without dialect-specifics
    id = Column(String(64), primary_key=True)
    decision_id = Column(String(128), nullable=False, index=True)
    action = Column(Text, nullable=False)
    actor = Column(String(256), nullable=True)
    # Store JSON as text in SQLite-friendly way; serialization handled in code
    metadata_ = Column("metadata", Text, nullable=True)
    # Prefer CURRENT_TIMESTAMP for broad compatibility
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.current_timestamp())

    # --- C01: Tamper-evidence hash chain (Merkle chain) ---
    # SHA-256 hash of this record's canonical content (id + decision_id + action + actor + metadata + created_at + prev_hash).
    record_hash = Column(String(64), nullable=True)
    # SHA-256 hash of the immediately preceding record — forms a forward-linked chain.
    prev_hash = Column(String(64), nullable=True)
