from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.app.security.auth import require_role, ROLE_MERCHANT
from src.app.services.nlp_query_clustering import QueryClusterer

router = APIRouter(prefix="/merchant", tags=["merchant"])


@router.get("/dashboard", response_class=HTMLResponse)
def merchant_dashboard(request: Request, role: str = Depends(require_role([ROLE_MERCHANT]))):
    """Simple merchant dashboard showing top suggested FAQs from clustering."""
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
        <h2>Merchant Dashboard — Suggested FAQs</h2>
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
