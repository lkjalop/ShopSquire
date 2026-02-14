from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from src.app.security.auth import ROLE_MERCHANT, require_role
from src.app.services.nlp_query_clustering import QueryClusterer

router = APIRouter(prefix="/merchant", tags=["merchant"])


def _is_loopback(req: Request) -> bool:
    try:
        host = getattr(getattr(req, "client", None), "host", None)
        return str(host) in ("127.0.0.1", "::1", "localhost")
    except Exception:
        return False


def _is_local_demo_host(req: Request) -> bool:
    # When running behind Docker port-mapping, client.host may be a bridge IP.
    # Use Host header as the primary signal for "opened on localhost in a browser".
    try:
        host = str((req.headers.get("host") or "")).lower()
        return host.startswith("127.0.0.1") or host.startswith("localhost")
    except Exception:
        return False


def _allow_unauth_dashboard(req: Request) -> bool:
    # Make local demos easy: allow loopback access without headers when running in local env.
    env = str(os.getenv("APP_ENV", "") or "").lower()
    explicit = str(os.getenv("ALLOW_UNAUTH_MERCHANT_DASHBOARD", "") or "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return _is_loopback(req) or _is_local_demo_host(req)
    if explicit in ("0", "false", "no", "off"):
        return False
    return env in ("local", "dev", "development") and (_is_loopback(req) or _is_local_demo_host(req))


@router.get("/dashboard", response_class=HTMLResponse)
def merchant_dashboard(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
):
    """Simple merchant dashboard showing top suggested FAQs from clustering."""
    if not _allow_unauth_dashboard(request):
        # Enforce the same merchant key as the API for non-local requests.
        expected = os.getenv("MERCHANT_API_KEY", "local-merchant-key")
        if not x_api_key or x_api_key.strip() != str(expected).strip():
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        # Keep role semantics for internal callers that already use dependency injection.
        # (This is a no-op if the key maps to ROLE_MERCHANT.)
        _ = require_role([ROLE_MERCHANT])(x_api_key=x_api_key, authorization=None, request=request)  # type: ignore[misc]
    # Render a tiny page that queries `/api/v1/analytics/query_clusters/latest`
    html = """
    <html>
      <head>
        <title>Merchant Dashboard</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 16px }
          .faq { border:1px solid #eee; padding:10px; border-radius:6px; margin-bottom:8px }
        </style>
      </head>
      <body>
        <h2>Merchant Dashboard - Suggested FAQs</h2>
        <div id="list">Loading...</div>
        <script>
          async function load(){
            try{
              const r = await fetch('/api/v1/analytics/query_clusters/latest?limit=10');
              const j = await r.json();
              const container = document.getElementById('list');
              container.innerHTML = '';
              for(const it of j.items || []){
                const d = document.createElement('div'); d.className='faq';
                d.innerHTML = `<strong>${it.label}</strong> — ${it.size} examples<br/><em>${(it.top_k_exemplars||[]).slice(0,2).join(' | ')}</em>`;
                container.appendChild(d);
              }
            }catch(e){ document.getElementById('list').innerText = 'error' }
          }
          load();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
