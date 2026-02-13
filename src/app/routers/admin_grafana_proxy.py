from __future__ import annotations

from fastapi import APIRouter, Request, Response, HTTPException
import httpx
from src.app.services.secrets_manager import get_secret

router = APIRouter(prefix="/admin", tags=["admin"])


@router.route("/grafana_proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def grafana_proxy(request: Request, path: str):
    """Simple proxy to forward requests to Grafana adding API key header.

    Usage: set GRAFANA_URL and GRAFANA_API_KEY in environment. The proxy
    allows embedding Grafana panels in iframes without exposing the key.
    """
    grafana = get_secret("GRAFANA_URL")
    api_key = get_secret("GRAFANA_API_KEY")
    if not grafana:
        raise HTTPException(status_code=503, detail="Grafana URL not configured")
    url = grafana.rstrip("/") + "/" + path
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            content = await request.body()
            resp = await client.request(request.method, url, headers=headers, content=content, params=request.query_params)
            return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
