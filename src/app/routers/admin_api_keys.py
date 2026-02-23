from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Body

from src.app.security.auth import require_role, ROLE_OWNER, _keys_path

router = APIRouter(prefix="/api/v1/admin/api-keys", tags=["admin"])


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        raise


@router.get("/")
def list_keys(role: str = Depends(require_role([ROLE_OWNER]))):
    path = _keys_path()
    try:
        if not path.exists():
            return {"keys": {}}
        doc = json.loads(path.read_text(encoding="utf-8"))
        return {"keys": doc}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/add")
def add_key(payload: Dict[str, Any] = Body(...), role: str = Depends(require_role([ROLE_OWNER]))):
    """Add a new API key for a role. Body: { "role": "developer", "label": "ci-bot" }
    Returns the generated key value (only shown once).
    """
    target_role = str(payload.get("role") or "").strip()
    if target_role not in ("merchant", "owner", "developer"):
        raise HTTPException(status_code=400, detail="invalid role")
    label = str(payload.get("label") or "").strip()
    key = secrets.token_urlsafe(32)
    path = _keys_path()
    try:
        doc = {}
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8")) or {}
        arr = doc.get(target_role) or []
        arr.append({"key": key, "label": label, "created_at": int(__import__("time").time())})
        doc[target_role] = arr
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, doc)
        return {"key": key}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/revoke")
def revoke_key(payload: Dict[str, Any] = Body(...), role: str = Depends(require_role([ROLE_OWNER]))):
    """Revoke an existing key; body: { "role": "developer", "key": "<value>" }
    """
    target_role = str(payload.get("role") or "").strip()
    key = str(payload.get("key") or "").strip()
    if not key or target_role not in ("merchant", "owner", "developer"):
        raise HTTPException(status_code=400, detail="invalid request")
    path = _keys_path()
    try:
        if not path.exists():
            raise HTTPException(status_code=404, detail="no keys file")
        doc = json.loads(path.read_text(encoding="utf-8")) or {}
        arr = [k for k in (doc.get(target_role) or []) if k.get("key") != key]
        doc[target_role] = arr
        _atomic_write(path, doc)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/rotate")
def rotate_role_key(payload: Dict[str, Any] = Body(...), role: str = Depends(require_role([ROLE_OWNER]))):
    """Rotate (append) a new key for a role and return it. Body: { "role": "developer", "label": "rotated-2026-02" }
    Use revoke to remove old keys.
    """
    target_role = str(payload.get("role") or "").strip()
    label = str(payload.get("label") or "").strip()
    if target_role not in ("merchant", "owner", "developer"):
        raise HTTPException(status_code=400, detail="invalid role")
    key = secrets.token_urlsafe(32)
    path = _keys_path()
    try:
        doc = {}
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8")) or {}
        arr = doc.get(target_role) or []
        arr.append({"key": key, "label": label, "created_at": int(__import__("time").time())})
        doc[target_role] = arr
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, doc)
        return {"key": key}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
