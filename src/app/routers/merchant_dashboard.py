from __future__ import annotations

import json
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
              const container = document.getElementById('list');
              if(!r.ok){
                const t = await r.text();
                container.innerText = `Unable to load data (${r.status}).` + (t ? (' ' + t) : '');
                return;
              }
              const j = await r.json();
              const items = (j && j.items) ? j.items : [];
              container.innerHTML = '';
              if(!items.length){
                container.innerText = 'No dashboard data yet. Seed query clusters via POST /api/v1/analytics/query_clusters.';
                return;
              }
              for(const it of items){
                const d = document.createElement('div'); d.className='faq';
                d.innerHTML = `<strong>${it.label}</strong> - ${it.size} examples<br/><em>${(it.top_k_exemplars||[]).slice(0,2).join(' | ')}</em>`;
                container.appendChild(d);
              }
            }catch(e){ document.getElementById('list').innerText = 'Unable to load dashboard data.' }
          }
          load();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/bi", response_class=HTMLResponse)
def merchant_bi(request: Request):
    """Demo-friendly merchant BI surface.

    This embeds the provisioned Grafana dashboards so you get real charts without building a bespoke BI UI.
    """
    # Local-only by design (Grafana is anonymous-viewer in docker-compose for demos).
    if not (_is_loopback(request) or _is_local_demo_host(request)):
        raise HTTPException(status_code=403, detail="merchant_bi_local_only")

    graf = os.getenv("GRAFANA_PUBLIC_BASE", "http://127.0.0.1:3005").rstrip("/")
    dashboards = [
        ("Overview", "shopsquire-merchant-bi"),
        ("Executive", "shopsquire-exec-overview"),
        ("Security SOC", "shopsquire-security-soc"),
        ("CV Analytics", "shopsquire-cv-analytics"),
        ("Escalations", "shopsquire-escalation-rates"),
        ("BI Views", "shopsquire-bi-views"),
    ]
    links = "\n".join([f"<button class='tab' onclick=\"show('{uid}')\">{name}</button>" for name, uid in dashboards])
    frames = "\n".join(
        [
            f"""<iframe id="f-{uid}" class="frame" style="display:none" src="{graf}/d/{uid}?orgId=1&kiosk&refresh=10s"></iframe>"""
            for _, uid in dashboards
        ]
    )
    default_uid = dashboards[0][1]
    html = f"""
    <html>
      <head>
        <title>Merchant BI</title>
        <style>
          :root {{ --bg:#0b1220; --fg:#e5e7eb; --muted:#94a3b8; --card:#0f172a; --accent:#f97316; }}
          body {{ margin:0; font-family: Arial, sans-serif; background: var(--bg); color: var(--fg); }}
          header {{ padding: 12px 14px; display:flex; justify-content:space-between; align-items:center; background: linear-gradient(90deg, #0b1220, #101a33); border-bottom: 1px solid rgba(148,163,184,0.2); }}
          .brand {{ font-weight: 700; letter-spacing: 0.2px; }}
          .sub {{ color: var(--muted); font-size: 12px; }}
          .tabs {{ display:flex; gap:8px; flex-wrap:wrap; padding: 10px 14px; background: rgba(15,23,42,0.35); border-bottom: 1px solid rgba(148,163,184,0.15);}}
          .tab {{ background: rgba(15,23,42,0.85); color: var(--fg); border: 1px solid rgba(148,163,184,0.2); border-radius: 10px; padding: 8px 10px; cursor:pointer; font-size: 13px; }}
          .tab.active {{ border-color: rgba(249,115,22,0.65); box-shadow: 0 0 0 2px rgba(249,115,22,0.12) inset; }}
          .wrap {{ height: calc(100vh - 96px); }}
          .frame {{ width: 100%; height: 100%; border: 0; background: #0b1220; }}
          .right a {{ color: var(--fg); text-decoration:none; border:1px solid rgba(148,163,184,0.25); padding: 6px 10px; border-radius: 10px; font-size: 12px; }}
          .right a:hover {{ border-color: rgba(249,115,22,0.6); }}
        </style>
      </head>
      <body>
        <header>
          <div>
            <div class="brand">ShopSquire Merchant BI</div>
            <div class="sub">Live dashboards (Grafana embed). Refreshes every 10s.</div>
          </div>
          <div class="right" style="display:flex; gap:8px;">
            <a href="/merchant/dashboard" target="_blank">Suggested FAQs</a>
            <a href="{graf}" target="_blank">Open Grafana</a>
          </div>
        </header>
        <div class="tabs" id="tabs">
          {links}
        </div>
        <div class="wrap">
          {frames}
        </div>
        <script>
          const all = {json.dumps([uid for _, uid in dashboards])};
          function show(uid){{
            for(const u of all){{
              const el = document.getElementById('f-' + u);
              if(el) el.style.display = (u === uid) ? 'block' : 'none';
            }}
            for(const b of document.querySelectorAll('.tab')) {{
              b.classList.toggle('active', b.getAttribute('onclick').includes(\"'\"+uid+\"'\"));
            }}
          }}
          show('{default_uid}');
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/incident-room", response_class=HTMLResponse)
def merchant_incident_room(request: Request, incident_id: str | None = None, token: str | None = None):
    """Lightweight staff incident room UI (local demo).

    Use `token` from `/api/v1/incidents/escalate` (staff_token) to join.
    """
    if not (_is_loopback(request) or _is_local_demo_host(request)):
        raise HTTPException(status_code=403, detail="incident_room_local_only")
    inc = (incident_id or "").strip()
    tok = (token or "").strip()
    html = f"""
    <html>
      <head>
        <title>Incident Room</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 0; background:#0b1220; color:#e5e7eb; }}
          header {{ padding: 12px 14px; border-bottom:1px solid rgba(148,163,184,0.18); background:#0f172a; }}
          .row {{ display:flex; gap:10px; padding: 12px 14px; align-items:center; flex-wrap:wrap; }}
          input {{ padding:8px 10px; border-radius:10px; border:1px solid rgba(148,163,184,0.25); background:#0b1220; color:#e5e7eb; min-width: 280px; }}
          button {{ padding:8px 10px; border-radius:10px; border:1px solid rgba(148,163,184,0.25); background:#111827; color:#e5e7eb; cursor:pointer; }}
          button:hover {{ border-color: rgba(249,115,22,0.6); }}
          .log {{ height: calc(100vh - 170px); overflow:auto; padding: 12px 14px; }}
          .msg {{ margin-bottom:10px; padding:10px 12px; border-radius:12px; background: rgba(15,23,42,0.7); border:1px solid rgba(148,163,184,0.18);}}
          .meta {{ font-size: 11px; color:#94a3b8; margin-bottom:4px; }}
          .me {{ border-color: rgba(249,115,22,0.35); }}
          .compose {{ padding: 12px 14px; border-top:1px solid rgba(148,163,184,0.18); background:#0f172a; display:flex; gap:10px; }}
          .compose input {{ flex:1; min-width: 200px; }}
        </style>
      </head>
      <body>
        <header>
          <div style="font-weight:700">Incident Room (Staff)</div>
          <div style="color:#94a3b8; font-size:12px;">Join with incident_id + staff token. This is a local demo UI.</div>
        </header>
        <div class="row">
          <div>Incident ID</div><input id="incident" value="{inc}" placeholder="incident_id" />
          <div>Token</div><input id="token" value="{tok}" placeholder="staff_token" />
          <button onclick="connect()">Connect</button>
        </div>
        <div class="log" id="log"></div>
        <div class="compose">
          <input id="text" placeholder="Type a message..." onkeydown="if(event.key==='Enter') send();" />
          <button onclick="send()">Send</button>
        </div>
        <script>
          let es = null;
          function append(rec){{
            const log = document.getElementById('log');
            const d = document.createElement('div');
            d.className = 'msg' + ((rec.role && rec.role !== 'buyer' && rec.role !== 'assistant') ? ' me' : '');
            const ts = (rec.ts ? new Date(rec.ts) : new Date());
            d.innerHTML = `<div class='meta'>${{ts.toLocaleTimeString()}} | ${{rec.role || 'unknown'}}</div><div>${{(rec.message||'').replace(/</g,'&lt;')}}</div>`;
            log.appendChild(d);
            log.scrollTop = log.scrollHeight;
          }}
          function connect(){{
            const inc = document.getElementById('incident').value.trim();
            const tok = document.getElementById('token').value.trim();
            if(!inc || !tok) return;
            if(es) try{{ es.close(); }}catch(e){{}}
            document.getElementById('log').innerHTML = '';
            es = new EventSource(`/api/v1/incidents/${{encodeURIComponent(inc)}}/room/stream?token=${{encodeURIComponent(tok)}}`);
            es.onmessage = (ev) => {{
              try{{
                const arr = JSON.parse(ev.data);
                for(const rec of (arr||[])) append(rec);
              }}catch(e){{}}
            }};
            es.onerror = () => {{
              // keep trying; browser auto-reconnects
            }};
          }}
          async function send(){{
            const inc = document.getElementById('incident').value.trim();
            const tok = document.getElementById('token').value.trim();
            const msg = document.getElementById('text').value.trim();
            if(!inc || !tok || !msg) return;
            document.getElementById('text').value = '';
            try{{
              await fetch(`/api/v1/incidents/${{encodeURIComponent(inc)}}/room/message`, {{
                method: 'POST',
                headers: {{ 'Content-Type':'application/json', 'x-incident-token': tok }},
                body: JSON.stringify({{ message: msg }})
              }});
            }}catch(e){{}}
          }}
          if("{inc}" && "{tok}") connect();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
