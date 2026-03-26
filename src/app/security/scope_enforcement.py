from typing import List
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.app.services.jwks import verify_token
import os


bearer_scheme = HTTPBearer(auto_error=False)


def require_scopes(required: List[str]):
    async def _dep(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
        ok, payload = verify_token(creds.credentials)
        if not ok or not isinstance(payload, dict):
            raise HTTPException(status_code=401, detail="invalid_token")
        token_scopes = set(str(payload.get("scope", "")).split())
        missing = [s for s in required if s not in token_scopes]
        if missing:
            raise HTTPException(status_code=403, detail="insufficient_scope")
        return payload
    return _dep


def optional_connector_read():
    async def _dep(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
        # Default fail-closed: enforce scopes in all envs unless explicitly disabled.
        # Set ENFORCE_CONNECTOR_SCOPES=0 only for local dev where no IdP is available.
        enforce = os.getenv("ENFORCE_CONNECTOR_SCOPES", "1").lower() not in ("0", "false", "no")
        if not enforce:
            return {"scope": ""}
        if creds is None or not creds.credentials:
            raise HTTPException(status_code=401, detail="missing_token")
        ok, payload = verify_token(creds.credentials)
        if not ok or not isinstance(payload, dict):
            raise HTTPException(status_code=401, detail="invalid_token")
        token_scopes = set(str(payload.get("scope", "")).split())
        if "connector:read" not in token_scopes:
            raise HTTPException(status_code=403, detail="insufficient_scope")
        return payload
    return _dep
