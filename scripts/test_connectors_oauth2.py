"""Local test for connector OAuth2 (JWKS RS256):

1) Ensure JWKS exists
2) Register a client
3) Request token for a scope
4) Introspect token and check claims
"""
import json
import time
import secrets

from src.app.services.jwks import ensure_jwks, jwks_document, issue_token, verify_token


def main():
    ensure_jwks()
    doc = jwks_document()
    print({"jwks_keys": len(doc.get("keys", []))})
    # Simulate a client and scope issuance
    client_id = f"cli_{secrets.token_hex(6)}"
    scopes = ["connector:read", "connector:write"]
    tok = issue_token(sub=client_id, scopes=scopes, ttl_seconds=600, issuer="shopsquire")
    ok, payload = verify_token(tok)
    print({"verified": ok, "scope": payload.get("scope") if isinstance(payload, dict) else None, "sub": payload.get("sub") if isinstance(payload, dict) else None})


if __name__ == "__main__":
    main()
