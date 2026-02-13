import os
import json
import secrets
import time
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException, Depends, Form

from src.app.security.auth import require_role, ROLE_OWNER
from src.app.services.jwks import ensure_jwks, issue_token, jwks_document, verify_token

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


def _clients_path() -> Path:
    return Path(os.getenv("CONNECTOR_CLIENTS_PATH", "config/connector_clients.json"))


def _load_clients() -> Dict:
    p = _clients_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_clients(clients: Dict) -> None:
    p = _clients_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clients, ensure_ascii=False, indent=2), encoding="utf-8")


@router.post("/register")
def register_connector(name: str, scopes: str = "", role: str = Depends(require_role([ROLE_OWNER]))) -> Dict:
    """Register a connector client (Owner only). Returns client_id and client_secret.

    `scopes` is a space-separated list.
    """
    clients = _load_clients()
    cid = f"cli_{secrets.token_urlsafe(10)}"
    secret = secrets.token_urlsafe(32)
    clients[cid] = {"name": name, "secret": secret, "scopes": scopes.split(), "created_at": int(time.time())}
    _save_clients(clients)
    return {"client_id": cid, "client_secret": secret, "scopes": scopes.split()}


@router.post("/token")
def token(client_id: str = Form(...), client_secret: str = Form(...), scope: str | None = Form(None)) -> Dict:
    """Client credentials token endpoint returning RS256 JWT with kid (JWKS).

    Falls back to HS256 if JWKS/RSA is unavailable.
    """
    clients = _load_clients()
    c = clients.get(client_id)
    if not c or c.get("secret") != client_secret:
        raise HTTPException(status_code=401, detail="invalid_client")
    allowed = set(c.get("scopes", []))
    req_scopes = set((scope or "").split()) if scope else set()
    if req_scopes and not req_scopes.issubset(allowed):
        raise HTTPException(status_code=400, detail="invalid_scope")
    ttl = int(os.getenv("CONNECTOR_TOKEN_TTL", "3600") or 3600)
    issuer = os.getenv("CONNECTOR_TOKEN_ISSUER", "shopsquire")
    scopes = sorted(list(req_scopes or allowed))
    try:
        ensure_jwks()
        tok = issue_token(sub=client_id, scopes=scopes, ttl_seconds=ttl, issuer=issuer)
        return {"access_token": tok, "token_type": "bearer", "expires_in": ttl, "scope": " ".join(scopes), "alg": "RS256"}
    except Exception:
        # HS256 fallback
        now = int(time.time())
        exp = now + ttl
        claims = {"iss": issuer, "sub": client_id, "scope": " ".join(scopes), "iat": now, "exp": exp}
        secret = os.getenv("CONNECTOR_JWT_SECRET", "local-connector-secret")
        try:
            import jwt

            token = jwt.encode(claims, secret, algorithm="HS256")
        except Exception:
            token = secrets.token_urlsafe(32)
        return {"access_token": token, "token_type": "bearer", "expires_in": ttl, "scope": " ".join(scopes), "alg": "HS256"}


@router.get("/.well-known/jwks.json")
def jwks():
    try:
        ensure_jwks()
        return jwks_document()
    except Exception:
        # No JWKS available
        return {"keys": []}


@router.post("/introspect")
def introspect(token: str = Form(...)) -> Dict:
    """Token introspection: verify signature and return active + claims summary."""
    ok, payload = verify_token(token)
    return {"active": bool(ok), "claims": payload if isinstance(payload, dict) else {"error": "invalid"}}
