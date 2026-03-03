from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.supply_chain_controls import ingest_sbom_and_correlate


def _ensure_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS supply_chain_sbom_runs (
                      id TEXT PRIMARY KEY,
                      tenant_id TEXT,
                      sbom_path TEXT,
                      result_json TEXT NOT NULL,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def _sbom_paths() -> List[str]:
    raw = str(os.getenv("SUPPLY_CHAIN_SBOM_PATHS", "sbom.spdx.json,sbom.cdx.json") or "").strip()
    out: List[str] = []
    for part in raw.split(","):
        p = part.strip()
        if p:
            out.append(p)
    return out


def correlate_local_sboms(*, tenant_id: str | None = None) -> Dict[str, Any]:
    _ensure_table()
    checked = 0
    correlated = 0
    failures: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    for path in _sbom_paths():
        checked += 1
        p = Path(path)
        if not p.exists() or not p.is_file():
            failures.append({"path": path, "error": "not_found"})
            continue
        try:
            sbom = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(sbom, dict):
                raise ValueError("sbom_not_json_object")
            res = ingest_sbom_and_correlate(sbom, tenant_id=tenant_id)
            correlated += 1
            results.append({"path": path, "result": res})
            try:
                import uuid

                with db_session() as db:
                    db.execute(
                        text(
                            """
                            INSERT INTO supply_chain_sbom_runs (id, tenant_id, sbom_path, result_json, created_at)
                            VALUES (:id, :tenant_id, :sbom_path, :result_json, CURRENT_TIMESTAMP)
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "tenant_id": tenant_id,
                            "sbom_path": path,
                            "result_json": json.dumps(res, ensure_ascii=False),
                        },
                    )
                    db.commit()
            except Exception:
                pass
        except Exception as exc:
            failures.append({"path": path, "error": str(exc)[:300]})
    return {
        "checked": checked,
        "correlated": correlated,
        "failures": failures,
        "results": results,
    }
