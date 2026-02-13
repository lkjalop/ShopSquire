from __future__ import annotations

from typing import Dict, Any
from sqlalchemy import text
from src.app.models.db import db_session


def ensure_compliance_registry_table() -> None:
    """Create `compliance_registry` table if it does not exist.

    Minimal columns for CI artifact evidence:
    - id (uuid-like string)
    - artifact_type (e.g., 'container_scan', 'asv', 'pentest')
    - vendor (e.g., 'trivy', 'snyk', 'qualys')
    - scan_id (external id/reference)
    - status ('pass'|'fail'|'warn')
    - details (JSON/text)
    - created_at (timestamp)
    """
    with db_session() as db:
        try:
            # Try Postgres-compatible DDL
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS compliance_registry (
                        id TEXT PRIMARY KEY,
                        artifact_type TEXT NOT NULL,
                        vendor TEXT,
                        scan_id TEXT,
                        status TEXT,
                        details TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.commit()
        except Exception:
            # Fallback: SQLite-compatible DDL
            try:
                db.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS compliance_registry (
                            id TEXT PRIMARY KEY,
                            artifact_type TEXT NOT NULL,
                            vendor TEXT,
                            scan_id TEXT,
                            status TEXT,
                            details TEXT,
                            created_at TEXT DEFAULT (datetime('now'))
                        )
                        """
                    )
                )
                db.commit()
            except Exception:
                db.rollback()


def insert_artifact(
    *,
    id: str,
    artifact_type: str,
    vendor: str | None,
    scan_id: str | None,
    status: str | None,
    details: str | None,
) -> Dict[str, Any]:
    with db_session() as db:
        try:
            db.execute(
                text(
                    """
                    INSERT INTO compliance_registry (id, artifact_type, vendor, scan_id, status, details)
                    VALUES (:id, :artifact_type, :vendor, :scan_id, :status, :details)
                    """
                ),
                {
                    "id": id,
                    "artifact_type": artifact_type,
                    "vendor": vendor,
                    "scan_id": scan_id,
                    "status": status,
                    "details": details,
                },
            )
            db.commit()
            return {"inserted": True, "id": id}
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            return {"inserted": False, "error": str(e)}


def list_artifacts(limit: int = 50) -> list[Dict[str, Any]]:
    with db_session() as db:
        try:
            rows = db.execute(
                text(
                    "SELECT id, artifact_type, vendor, scan_id, status, details, created_at FROM compliance_registry ORDER BY created_at DESC LIMIT :lim"
                ),
                {"lim": limit},
            ).mappings().all()
            return [dict(r) for r in rows]
        except Exception:
            return []