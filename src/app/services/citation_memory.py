"""Layer 4: Citation Memory — Agent Learning ORM + Verification Loop.

Stores agent claims (recommendations, fraud assessments, triage decisions) as
persistent records. Verifies claims against actual outcomes (purchase, return,
chargeback) and adjusts trust scores. Trusted claims boost future confidence.

Architecture:
- AgentLearning table in PostgreSQL (persistent, cross-session)
- Verification loop: claim → outcome observed → trust score updated
- Trust decay: claims without verification decay over time
- Integration: fraud_scorer reads trust scores, orchestrator boosts high-trust patterns
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session


# ── Table setup ──

_TABLE_ENSURED = False


def ensure_agent_learning_table(db=None) -> None:
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    try:
        sess = db
        close = False
        if sess is None:
            sess = db_session().__enter__()
            close = True
        sess.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_learnings (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                claim_key TEXT,
                claim_value TEXT,
                confidence REAL DEFAULT 0.5,
                trust_score REAL DEFAULT 0.5,
                verification_status TEXT DEFAULT 'pending',
                outcome_data TEXT,
                session_id TEXT,
                tenant_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                verified_at TEXT,
                metadata_json TEXT
            )
        """))
        sess.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_learning_agent
            ON agent_learnings(agent_name, claim_type)
        """))
        sess.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_learning_key
            ON agent_learnings(claim_key, verification_status)
        """))
        try:
            sess.commit()
        except Exception:
            pass
        if close:
            try:
                sess.__exit__(None, None, None)
            except Exception:
                pass
        _TABLE_ENSURED = True
    except Exception:
        pass


# ── Data model ──

@dataclass
class AgentClaim:
    agent_name: str
    claim_type: str  # "recommendation", "fraud_assessment", "triage_decision"
    claim_key: str   # e.g., SKU, case_id, user_hash
    claim_value: str  # JSON-encoded prediction/recommendation
    confidence: float = 0.5
    session_id: str | None = None
    tenant_id: str | None = None
    metadata: Dict[str, Any] | None = None


# ── Store + Query ──

def store_claim(claim: AgentClaim) -> str:
    """Store a new agent claim. Returns the claim ID."""
    claim_id = str(uuid.uuid4())
    try:
        with db_session() as db:
            ensure_agent_learning_table(db)
            db.execute(text("""
                INSERT INTO agent_learnings
                (id, agent_name, claim_type, claim_key, claim_value, confidence,
                 trust_score, verification_status, session_id, tenant_id, metadata_json)
                VALUES (:id, :agent_name, :claim_type, :claim_key, :claim_value, :confidence,
                        :trust_score, :verification_status, :session_id, :tenant_id, :metadata_json)
            """), {
                "id": claim_id,
                "agent_name": claim.agent_name,
                "claim_type": claim.claim_type,
                "claim_key": claim.claim_key,
                "claim_value": claim.claim_value,
                "confidence": claim.confidence,
                "trust_score": 0.5,  # neutral starting trust
                "verification_status": "pending",
                "session_id": claim.session_id,
                "tenant_id": claim.tenant_id,
                "metadata_json": json.dumps(claim.metadata or {}),
            })
            db.commit()
    except Exception:
        pass
    return claim_id


def verify_claim(claim_id: str, *, outcome: str, outcome_correct: bool,
                 outcome_data: Dict[str, Any] | None = None) -> float:
    """Verify a claim against an observed outcome. Returns updated trust score."""
    try:
        with db_session() as db:
            ensure_agent_learning_table(db)
            row = db.execute(
                text("SELECT trust_score, confidence FROM agent_learnings WHERE id = :id"),
                {"id": claim_id}
            ).fetchone()
            if not row:
                return 0.5

            old_trust = float(row[0] or 0.5)
            confidence = float(row[1] or 0.5)

            # Bayesian-ish update: correct outcomes increase trust, incorrect decrease
            if outcome_correct:
                new_trust = min(0.99, old_trust + (1.0 - old_trust) * 0.2 * confidence)
            else:
                new_trust = max(0.01, old_trust - old_trust * 0.3 * confidence)

            db.execute(text("""
                UPDATE agent_learnings
                SET trust_score = :trust, verification_status = :status,
                    outcome_data = :outcome_data, verified_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {
                "id": claim_id,
                "trust": round(new_trust, 4),
                "status": "verified_correct" if outcome_correct else "verified_incorrect",
                "outcome_data": json.dumps({"outcome": outcome, **(outcome_data or {})}),
            })
            db.commit()
            return new_trust
    except Exception:
        return 0.5


def get_agent_trust_score(agent_name: str, claim_type: str | None = None) -> float:
    """Get the aggregate trust score for an agent across verified claims."""
    try:
        with db_session() as db:
            ensure_agent_learning_table(db)
            if claim_type:
                rows = db.execute(text("""
                    SELECT trust_score FROM agent_learnings
                    WHERE agent_name = :agent AND claim_type = :ctype
                    AND verification_status LIKE 'verified_%'
                    ORDER BY verified_at DESC LIMIT 50
                """), {"agent": agent_name, "ctype": claim_type}).fetchall()
            else:
                rows = db.execute(text("""
                    SELECT trust_score FROM agent_learnings
                    WHERE agent_name = :agent
                    AND verification_status LIKE 'verified_%'
                    ORDER BY verified_at DESC LIMIT 50
                """), {"agent": agent_name}).fetchall()
            if not rows:
                return 0.5
            scores = [float(r[0]) for r in rows]
            return round(sum(scores) / len(scores), 4)
    except Exception:
        return 0.5


def get_trusted_claims(agent_name: str, claim_type: str, min_trust: float = 0.7,
                       limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve high-trust claims that can boost future confidence."""
    try:
        with db_session() as db:
            ensure_agent_learning_table(db)
            rows = db.execute(text("""
                SELECT id, claim_key, claim_value, trust_score, confidence, metadata_json
                FROM agent_learnings
                WHERE agent_name = :agent AND claim_type = :ctype
                AND trust_score >= :min_trust
                ORDER BY trust_score DESC, verified_at DESC
                LIMIT :lim
            """), {
                "agent": agent_name, "ctype": claim_type,
                "min_trust": min_trust, "lim": limit,
            }).fetchall()
            return [
                {
                    "id": r[0], "claim_key": r[1],
                    "claim_value": json.loads(r[2]) if r[2] else None,
                    "trust_score": float(r[3]),
                    "confidence": float(r[4]),
                    "metadata": json.loads(r[5]) if r[5] else {},
                }
                for r in rows
            ]
    except Exception:
        return []


def get_claim_stats(agent_name: str | None = None) -> Dict[str, Any]:
    """Get claim statistics for monitoring dashboards."""
    try:
        with db_session() as db:
            ensure_agent_learning_table(db)
            where = "WHERE agent_name = :agent" if agent_name else ""
            params = {"agent": agent_name} if agent_name else {}

            total = db.execute(
                text(f"SELECT COUNT(*) FROM agent_learnings {where}"), params
            ).fetchone()
            verified = db.execute(
                text(f"SELECT COUNT(*) FROM agent_learnings {where} {'AND' if where else 'WHERE'} verification_status LIKE 'verified_%'"),
                params
            ).fetchone()
            correct = db.execute(
                text(f"SELECT COUNT(*) FROM agent_learnings {where} {'AND' if where else 'WHERE'} verification_status = 'verified_correct'"),
                params
            ).fetchone()
            avg_trust = db.execute(
                text(f"SELECT AVG(trust_score) FROM agent_learnings {where} {'AND' if where else 'WHERE'} verification_status LIKE 'verified_%'"),
                params
            ).fetchone()

            total_n = int(total[0]) if total else 0
            verified_n = int(verified[0]) if verified else 0
            correct_n = int(correct[0]) if correct else 0

            return {
                "agent_name": agent_name or "all",
                "total_claims": total_n,
                "verified_claims": verified_n,
                "correct_claims": correct_n,
                "accuracy_rate": round(correct_n / max(1, verified_n), 4),
                "avg_trust_score": round(float(avg_trust[0] or 0.5), 4) if avg_trust else 0.5,
                "pending_claims": total_n - verified_n,
            }
    except Exception:
        return {"agent_name": agent_name, "total_claims": 0, "error": "query_failed"}
