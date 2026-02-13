from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from src.app.models.db import db_session
from sqlalchemy import text as sql_text


class EvidenceWriter:
    """Persist evidence packages to disk and the `evidence_bundles` table."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.path.join("tmp", "returns")

    def write(self, case_id: str, evidence: Dict[str, Any], *, evidence_id: Optional[str] = None) -> Optional[str]:
        eid = evidence_id or evidence.get("evidence_id")
        if not eid:
            try:
                eid = __import__("uuid").uuid4().hex
            except Exception:
                return None

        # Write a stable JSON artifact to disk (best-effort)
        try:
            base = os.path.join(self.base_dir, str(eid))
            os.makedirs(base, exist_ok=True)
            with open(os.path.join(base, "package.json"), "w", encoding="utf-8") as f:
                json.dump(evidence or {}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # Persist to DB (best-effort). Prefer using a provided evidence id so disk + DB align.
        try:
            payload = json.dumps(evidence or {}, ensure_ascii=False)
            with db_session() as db:
                db.execute(
                    sql_text(
                        "INSERT INTO evidence_bundles (id, case_id, bundle_json, created_at) "
                        "VALUES (:id, :case_id, :bundle_json, CURRENT_TIMESTAMP)"
                    ),
                    {"id": str(eid), "case_id": case_id, "bundle_json": payload},
                )
                db.commit()
        except Exception:
            # If the row already exists, do a best-effort update.
            try:
                payload = json.dumps(evidence or {}, ensure_ascii=False)
                with db_session() as db:
                    db.execute(
                        sql_text("UPDATE evidence_bundles SET bundle_json = :bundle_json WHERE id = :id"),
                        {"id": str(eid), "bundle_json": payload},
                    )
                    db.commit()
            except Exception:
                pass

        return str(eid)
