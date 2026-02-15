from __future__ import annotations

import json
import os

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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
def merchant_dashboard(request: Request):
    """Merchant dashboard entrypoint (local demo).

    We serve a built React app at `/merchant/app` (mounted by `src/app/main.py`).
    This route exists as a stable demo URL and simply deep-links into the BI tab.
    """
    if not (_is_loopback(request) or _is_local_demo_host(request)):
        # Keep the "merchant pages are local-only" stance for now.
        raise HTTPException(status_code=403, detail="merchant_dashboard_local_only")

    html = """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Merchant Dashboard</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 24px; }
          .card { border: 1px solid #eee; border-radius: 12px; padding: 14px; max-width: 720px; }
          .btn { display:inline-block; padding: 8px 12px; border-radius: 10px; background: #0b61d6; color: #fff; text-decoration:none; }
          .muted { color: #666; font-size: 12px; margin-top: 8px; }
          code { background: #f6f7f9; padding: 2px 6px; border-radius: 8px; }
        </style>
      </head>
      <body>
        <div class="card">
          <h2 style="margin:0 0 8px 0;">Merchant Dashboard</h2>
          <div class="muted">Opening BI charts and queues…</div>
          <div style="margin-top: 12px;">
            <a class="btn" href="/merchant/app/index.html?tab=merchant-bi">Open now</a>
          </div>
          <div class="muted">Local demo convenience: we set <code>localStorage.shopsquire_api_key</code> to <code>local-merchant-key</code> if missing.</div>
        </div>
        <script>
          try {
            const k = (localStorage.getItem('shopsquire_api_key') || '').trim();
            if(!k) localStorage.setItem('shopsquire_api_key', 'local-merchant-key');
          } catch (e) {}
          window.location.href = '/merchant/app/index.html?tab=merchant-bi';
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/dashboard-faq", response_class=HTMLResponse)
def merchant_dashboard_faq(
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
def merchant_incident_room(request: Request):
    """Human escalation console entrypoint (local demo).

    Deep-links into the React escalation console (queue + chat + context).
    """
    if not (_is_loopback(request) or _is_local_demo_host(request)):
        raise HTTPException(status_code=403, detail="incident_room_local_only")

    html = """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Incident Console</title>
      </head>
      <body>
        <script>
          try {
            const k = (localStorage.getItem('shopsquire_api_key') || '').trim();
            if(!k) localStorage.setItem('shopsquire_api_key', 'local-merchant-key');
          } catch (e) {}
          window.location.href = '/merchant/app/index.html?tab=escalations';
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/incident-room-lite", response_class=HTMLResponse)
def merchant_incident_room_lite(request: Request, incident_id: str | None = None, token: str | None = None):
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
          .card {{ margin: 12px 14px; border:1px solid rgba(148,163,184,0.18); border-radius: 14px; background: rgba(15,23,42,0.45); }}
          .card h4 {{ margin: 0; padding: 10px 12px; border-bottom:1px solid rgba(148,163,184,0.14); font-size: 13px; color: #cbd5e1; }}
          .card .body {{ padding: 10px 12px; }}
          input {{ padding:8px 10px; border-radius:10px; border:1px solid rgba(148,163,184,0.25); background:#0b1220; color:#e5e7eb; min-width: 280px; }}
          button {{ padding:8px 10px; border-radius:10px; border:1px solid rgba(148,163,184,0.25); background:#111827; color:#e5e7eb; cursor:pointer; }}
          button:hover {{ border-color: rgba(249,115,22,0.6); }}
          .pill {{ display:inline-flex; align-items:center; gap:8px; padding: 6px 10px; border:1px solid rgba(148,163,184,0.18); border-radius: 999px; background: rgba(2,6,23,0.35); font-size: 12px; color:#cbd5e1; }}
          .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace; }}
          .inc-list {{ display:flex; flex-direction:column; gap:8px; max-height: 160px; overflow:auto; }}
          .inc-item {{ display:flex; justify-content:space-between; gap: 10px; padding: 8px 10px; border:1px solid rgba(148,163,184,0.16); border-radius: 12px; cursor:pointer; background: rgba(2,6,23,0.2); }}
          .inc-item:hover {{ border-color: rgba(249,115,22,0.55); }}
          .inc-left {{ display:flex; flex-direction:column; gap:4px; }}
          .inc-right {{ display:flex; flex-direction:column; gap:4px; align-items:flex-end; }}
          .small {{ font-size: 11px; color: #94a3b8; }}
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
        <div class="card">
          <h4>Open Incidents</h4>
          <div class="body">
            <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px;">
              <span class="pill"><span>API Key</span> <span class="mono" id="apikey_hint">(uses localStorage or local-merchant-key)</span></span>
              <button onclick="loadIncidents()">Load Open Incidents</button>
              <span class="small" id="inc_status"></span>
            </div>
            <div class="inc-list" id="inc_list"></div>
          </div>
        </div>
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
          function getApiKey(){{
            try {{
              return (localStorage.getItem('x-api-key') || localStorage.getItem('api_key') || '').trim() || 'local-merchant-key';
            }} catch(e) {{
              return 'local-merchant-key';
            }}
          }}
          function append(rec){{
            const log = document.getElementById('log');
            const d = document.createElement('div');
            d.className = 'msg' + ((rec.role && rec.role !== 'buyer' && rec.role !== 'assistant') ? ' me' : '');
            const ts = (rec.ts ? new Date(rec.ts) : new Date());
            d.innerHTML = `<div class='meta'>${{ts.toLocaleTimeString()}} | ${{rec.role || 'unknown'}}</div><div>${{(rec.message||'').replace(/</g,'&lt;')}}</div>`;
            log.appendChild(d);
            log.scrollTop = log.scrollHeight;
          }}
          async function loadIncidents(){{
            const status = document.getElementById('inc_status');
            const list = document.getElementById('inc_list');
            status.textContent = 'Loading...';
            list.innerHTML = '';
            try {{
              const r = await fetch('/api/v1/admin/incidents/', {{
                headers: {{ 'x-api-key': getApiKey() }}
              }});
              const j = await r.json();
              const incs = (j && j.incidents) ? j.incidents : [];
              if (!Array.isArray(incs) || incs.length === 0) {{
                status.textContent = 'No open incidents found.';
                return;
              }}
              status.textContent = `${{incs.length}} open incident(s)`;
              for (const it of incs) {{
                const row = document.createElement('div');
                row.className = 'inc-item';
                const created = it.created_at ? new Date(it.created_at) : null;
                row.innerHTML = `
                  <div class='inc-left'>
                    <div class='mono'>${{it.id || ''}}</div>
                    <div class='small'>${{(it.title || 'Incident').toString().slice(0, 90)}}</div>
                  </div>
                  <div class='inc-right'>
                    <div class='pill'>${{(it.severity || 'unknown').toString()}}</div>
                    <div class='small'>${{created ? created.toLocaleString() : ''}}</div>
                  </div>
                `;
                row.onclick = async () => {{
                  try {{
                    const incId = (it.id || '').toString();
                    if(!incId) return;
                    document.getElementById('incident').value = incId;
                    // Issue/rotate a staff token so EventSource can connect (no headers).
                    const tr = await fetch(`/api/v1/admin/incidents/${{encodeURIComponent(incId)}}/room/token`, {{
                      method: 'POST',
                      headers: {{ 'x-api-key': getApiKey() }},
                    }});
                    const tj = await tr.json();
                    if (tj && tj.staff_token) {{
                      document.getElementById('token').value = tj.staff_token;
                    }}
                    connect();
                  }} catch(e) {{}}
                }};
                list.appendChild(row);
              }}
            }} catch (e) {{
              status.textContent = 'Failed to load incidents.';
            }}
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
          try {{
            document.getElementById('apikey_hint').textContent = getApiKey();
          }} catch(e) {{}}
          if("{inc}" && "{tok}") {{
            connect();
          }} else {{
            // Auto-load list for convenience in demos.
            loadIncidents();
          }}
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
