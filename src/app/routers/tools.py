from __future__ import annotations

import json
from typing import Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.tools.runner import ToolRunner
from src.app.services.registry import list_tools, load_from_config


router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


class ToolRunRequest(BaseModel):
    tool: str
    params: Dict | None = None
    uid: str | None = None
    trace_id: str | None = None


def _registry() -> List[Dict]:
    try:
        load_from_config()
    except Exception:
        pass
    out = list_tools()
    return out


@router.get("/registry")
def registry(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    return {"tools": _registry()}


@router.post("/run")
def run_tool(req: ToolRunRequest, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    runner = ToolRunner()
    uid = str(req.uid or "").strip() or "anonymous"
    return runner.run(req.tool, req.params or {}, source=uid, trace_id=req.trace_id)


@router.get("/invocations")
def invocations(limit: int = 30, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    items: list[Dict] = []
    try:
        with db_session() as db:
            rows = db.execute(
                "SELECT id, event_time, severity, verdict_score, details FROM security_events ORDER BY event_time DESC LIMIT :limit",
                {"limit": limit},
            ).fetchall()
            for r in rows:
                try:
                    details = json.loads(r[4] or "null")
                except Exception:
                    details = {}
                agent = details.get("agent_event") if isinstance(details, dict) else None
                if not agent or agent.get("interaction_type") != "mcp.tool.invoked":
                    continue
                items.append({
                    "id": r[0],
                    "time": str(r[1]),
                    "severity": r[2],
                    "score": r[3],
                    "tool": agent.get("details", {}).get("tool") if isinstance(agent, dict) else None,
                    "source": agent.get("source"),
                    "destination": agent.get("destination"),
                    "meta": agent.get("details"),
                })
    except Exception:
        pass
    return {"invocations": items}
