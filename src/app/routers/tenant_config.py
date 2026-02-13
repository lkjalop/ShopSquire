from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional

from src.app.rules.tenant_config_store import TenantConfigStore
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_OWNER


router = APIRouter(prefix="/api/v1/config", tags=["tenant-config"])
store = TenantConfigStore(cache_ttl=0)


@router.get("/{config_key}")
def get_config(config_key: str, tenant_id: Optional[str] = None, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    val = store.get_override(config_key, tenant_id=tenant_id)
    return {"tenant_id": tenant_id or "global", "config_key": config_key, "value": val}


@router.put("/{config_key}")
def put_config(config_key: str, payload: Dict[str, Any], tenant_id: Optional[str] = None, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="value_must_be_object")
    ok = store.set_override(config_key, payload, tenant_id=tenant_id)
    if not ok:
        raise HTTPException(status_code=500, detail="write_failed")
    return {"ok": True}


@router.delete("/{config_key}")
def delete_config(config_key: str, tenant_id: Optional[str] = None, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    ok = store.delete_override(config_key, tenant_id=tenant_id)
    if not ok:
        raise HTTPException(status_code=500, detail="delete_failed")
    return {"ok": True}

