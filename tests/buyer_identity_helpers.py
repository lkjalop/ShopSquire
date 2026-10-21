"""Signed test principals; production authentication still verifies each request."""
import json
import os
import time
import jwt


def configure_buyer(monkeypatch, *, subject, tenant='default'):
    monkeypatch.setenv('JWT_SIGNING_KEY','isolated-test-buyer-signing-key-never-deploy')
    monkeypatch.setenv('BUYER_IDENTITY_MODE','strict')
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON',json.dumps({subject:[tenant]}))


def signed_buyer_headers(subject, tenant='default'):
    now=int(time.time())
    token=jwt.encode(dict(sub=subject,typ='access',iss='shopsquire',aud='shopsquire-api',iat=now,exp=now+300),
        os.environ['JWT_SIGNING_KEY'],algorithm='HS256')
    return {'Authorization':'Bearer '+token,'X-Tenant-ID':tenant}


def install_tenant_context(app):
    from src.app.platform.tenant_context import set_active_tenant_id,reset_active_tenant_id
    @app.middleware('http')
    async def tenant_context(request,call_next):
        token=set_active_tenant_id(request.headers.get('x-tenant-id'))
        try:return await call_next(request)
        finally:reset_active_tenant_id(token)
