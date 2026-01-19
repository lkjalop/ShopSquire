from typing import Dict, Optional
from fastapi import APIRouter, HTTPException

from src.app.config import load_feature_flags, get_settings
from src.app.models.db import db_session

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])


@router.get("/query")
def query_decisions(valid_from: Optional[str] = None, valid_to: Optional[str] = None, system_from: Optional[str] = None, system_to: Optional[str] = None) -> Dict:
    flags = load_feature_flags(get_settings().feature_flags_path)
    if not flags.get("DECISION_LOG_WRITES_ENABLED", False):
        # Avoid DB access during local/tests
        raise HTTPException(status_code=501, detail="Decision reads disabled in this environment")
    sql = (
        "SELECT id, agent_name, valid_from, valid_to, system_from, system_to, input_data, proposed_action, policy_version, approval_required, execution_status FROM decision_logs"
    )
    params = {}
    clauses = []
    if valid_from:
        clauses.append("valid_from >= :vf")
        params["vf"] = valid_from
    if valid_to:
        clauses.append("valid_to <= :vt")
        params["vt"] = valid_to
    if system_from:
        clauses.append("system_from >= :sf")
        params["sf"] = system_from
    if system_to:
        clauses.append("system_to <= :st")
        params["st"] = system_to
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    with db_session() as db:
        rows = db.execute(sql, params).mappings().all()
    return {"results": list(rows)}
