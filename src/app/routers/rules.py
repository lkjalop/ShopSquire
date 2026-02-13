from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional, List
import uuid
import re

from src.app.services.rule_store import RuleStore
from src.app.rules.engine import RuleEngine
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_OWNER

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])
store = RuleStore()
engine = RuleEngine(rule_store=store)


def _validate_regex(pattern: str | None) -> Optional[str]:
    if not pattern:
        return None
    try:
        re.compile(str(pattern))
        return None
    except re.error as exc:
        return str(exc)


@router.get("/")
def list_rules(tenant_id: str | None = None, domain: str | None = None, role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER]))):
    rules = store.get_active_rules(tenant_id, domain=domain)
    return {"rules": rules}


@router.get("/{rule_id}")
def get_rule(rule_id: str, role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER]))):
    r = store.get_rule(rule_id)
    if not r:
        raise HTTPException(status_code=404, detail="not_found")
    return {"rule": r}


@router.post("/")
def create_rule(payload: Dict[str, Any], role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER]))):
    if "title" not in payload:
        raise HTTPException(status_code=400, detail="missing_fields")
    rid = payload.get("id") or str(uuid.uuid4())
    pat = payload.get("pattern")
    err = _validate_regex(pat)
    if err:
        raise HTTPException(status_code=400, detail={"error": "invalid_regex", "message": err})
    payload = dict(payload)
    payload["id"] = str(rid)
    payload.setdefault("created_by", role)
    payload.setdefault("domain", "recommend")
    ok = store.create_rule(payload)
    if not ok:
        raise HTTPException(status_code=500, detail="create_failed")
    return {"ok": True, "id": payload["id"]}


@router.put("/{rule_id}")
def update_rule(rule_id: str, updates: Dict[str, Any], role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER]))):
    if "pattern" in updates:
        err = _validate_regex(updates.get("pattern"))
        if err:
            raise HTTPException(status_code=400, detail={"error": "invalid_regex", "message": err})
    ok = store.update_rule(rule_id, updates)
    if not ok:
        raise HTTPException(status_code=500, detail="update_failed")
    return {"ok": True}


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER]))):
    ok = store.delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=500, detail="delete_failed")
    return {"ok": True}


@router.post("/preview")
def preview_rule(query: Dict[str, Any], role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER]))):
    # query: { text: str, tenant_id?: str }
    text_q = query.get("text")
    if not text_q:
        raise HTTPException(status_code=400, detail="missing_text")
    ctx = {"memory": {}, "live": {}}
    if query.get("tenant_id"):
        ctx["memory"] = {"tenant_id": query.get("tenant_id")}
    if query.get("domain"):
        ctx["domain"] = query.get("domain")
    res = engine.evaluate(text_q, ctx)
    return {"preview": res}


@router.post("/dry-run")
def dry_run(payload: Dict[str, Any], role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER]))):
    """Dry-run rules without persisting them.

    Payload:
      { "text": "...", "tenant_id"?: "...", "rules"?: [{title, pattern, priority?, id?}, ...] }
    """
    text_q = payload.get("text")
    if not text_q:
        raise HTTPException(status_code=400, detail="missing_text")
    rules_in: List[Dict[str, Any]] = payload.get("rules") or []
    compiled: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for idx, r in enumerate(rules_in):
        pat = r.get("pattern")
        err = _validate_regex(pat)
        if err:
            errors.append({"index": idx, "id": r.get("id"), "title": r.get("title"), "error": err})
            continue
        try:
            compiled.append(
                {
                    "id": str(r.get("id") or f"dry:{idx}"),
                    "title": str(r.get("title") or ""),
                    "pattern": str(pat) if pat else None,
                    "priority": int(r.get("priority") or 100),
                }
            )
        except Exception:
            continue
    compiled.sort(key=lambda x: int(x.get("priority") or 100))
    ql = str(text_q)
    match = None
    for r in compiled:
        if not r.get("pattern"):
            continue
        try:
            if re.search(str(r["pattern"]), ql, flags=re.IGNORECASE):
                match = r
                break
        except Exception:
            continue
    return {"match": match, "errors": errors, "evaluated": len(compiled)}
