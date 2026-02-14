from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.nlp_query_clustering import QueryClusterer
from src.app.observability.metrics import record_query_cluster_volume
from src.app.observability.drift import compute_drift
from src.app.models.db import db_session
from sqlalchemy import text as sql_text
from src.app.services.db_read_routing import read_session
from src.app.services.dependency_resilience import call_with_resilience

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


class ClusterRequest(BaseModel):
    queries: List[str]
    min_cluster_size: int | None = 5
    persist: bool | None = True


@router.post("/query_clusters")
def query_clusters(body: ClusterRequest, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])) ) -> Dict[str, Any]:
    clusters = QueryClusterer().cluster(body.queries or [], min_cluster_size=int(body.min_cluster_size or 5))
    try:
        for c in clusters:
            record_query_cluster_volume(c.label or "unknown", c.size)
    except Exception:
        pass
    if body.persist:
        try:
            with db_session() as db:
                try:
                    # SQLite tests/dev may not have migrations; create table best-effort.
                    if getattr(db.bind, "dialect", None) is not None and db.bind.dialect.name == "sqlite":
                        db.execute(
                            sql_text(
                                """
                                CREATE TABLE IF NOT EXISTS query_clusters (
                                  id TEXT PRIMARY KEY,
                                  label TEXT,
                                  size INT,
                                  top_exemplars TEXT,
                                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                                )
                                """
                            )
                        )
                except Exception:
                    pass
                for c in clusters:
                    import json as _json
                    exemplars = _json.dumps(c.members[:5], ensure_ascii=False)
                    try:
                        dialect = getattr(getattr(db, "bind", None), "dialect", None)
                        dname = (dialect.name if dialect is not None else "")
                    except Exception:
                        dname = ""

                    if dname == "sqlite":
                        db.execute(
                            sql_text(
                                "INSERT OR REPLACE INTO query_clusters (id, label, size, top_exemplars) VALUES (:id, :label, :size, :ex)"
                            ),
                            {"id": c.id, "label": c.label or "unknown", "size": int(c.size or 0), "ex": exemplars},
                        )
                    else:
                        # Postgres/others: upsert on primary key.
                        db.execute(
                            sql_text(
                                """
                                INSERT INTO query_clusters (id, label, size, top_exemplars)
                                VALUES (:id, :label, :size, :ex)
                                ON CONFLICT (id) DO UPDATE SET
                                  label = EXCLUDED.label,
                                  size = EXCLUDED.size,
                                  top_exemplars = EXCLUDED.top_exemplars,
                                  created_at = CURRENT_TIMESTAMP
                                """
                            ),
                            {"id": c.id, "label": c.label or "unknown", "size": int(c.size or 0), "ex": exemplars},
                        )
                try:
                    db.commit()
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
        except Exception:
            pass
    return {"clusters": [
        {"id": c.id, "size": c.size, "centroid_text": c.centroid_text, "label": c.label, "top_k_exemplars": c.members[:5]} for c in clusters
    ]}

def _is_loopback_or_localhost(req: Request) -> bool:
    try:
        host = str((req.headers.get("host") or "")).lower()
        # Docker port mapping means req.client.host may be a bridge address. Host header is what we want here.
        return host.startswith("127.0.0.1") or host.startswith("localhost") or host.startswith("[::1]")
    except Exception:
        return False


def _allow_unauth_merchant_analytics(req: Request) -> bool:
    """Local-only convenience so the browser dashboard can call analytics APIs without custom headers.

    This is gated by:
      - APP_ENV in local/dev/development (default)
      - Host header indicating loopback
    OR an explicit ALLOW_UNAUTH_MERCHANT_DASHBOARD toggle.
    """
    env = str(os.getenv("APP_ENV", "") or "").lower()
    explicit = str(os.getenv("ALLOW_UNAUTH_MERCHANT_DASHBOARD", "") or "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return _is_loopback_or_localhost(req)
    if explicit in ("0", "false", "no", "off"):
        return False
    return env in ("local", "dev", "development") and _is_loopback_or_localhost(req)


@router.get("/query_clusters/latest")
def query_clusters_latest(
    request: Request,
    limit: int = 50,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Dict[str, Any]:
    if not _allow_unauth_merchant_analytics(request):
        # Preserve normal auth semantics for non-local callers.
        _ = require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])(
            x_api_key=x_api_key, authorization=authorization, request=request
        )  # type: ignore[misc]
    items: List[Dict[str, Any]] = []
    try:
        with read_session(read_class="timeline") as db:
            rows = call_with_resilience(
                "db.analytics.query_clusters_latest",
                lambda: db.execute(
                    sql_text(
                        "SELECT id, label, size, top_exemplars, created_at FROM query_clusters ORDER BY created_at DESC LIMIT :limit"
                    ),
                    {"limit": int(limit)},
                ).fetchall(),
                timeout_s=3.0,
                retries=1,
            )
            for r in rows or []:
                import json as _json
                exemplars = []
                try:
                    exemplars = _json.loads(r[3] or "[]")
                except Exception:
                    exemplars = []
                items.append({"id": r[0], "label": r[1], "size": int(r[2] or 0), "top_k_exemplars": exemplars, "created_at": r[4]})
    except Exception:
        items = []
    return {"items": items}


@router.get("/query_clusters/drift")
def query_clusters_drift(window_a_min: int = 60, window_b_min: int = 10, model: str | None = None, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])) ) -> Dict[str, Any]:
    """Compute drift ratios between two time windows of cluster observations."""
    return compute_drift(window_a_min=window_a_min, window_b_min=window_b_min, model=model)
