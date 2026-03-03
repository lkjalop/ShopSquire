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
          <div class="muted">Local demo convenience: auth is handled via session cookie flow.</div>
        </div>
        <script>
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
            <a id="incLink" href="/merchant/incident-room" target="_blank">Incidents</a>
          </div>
        </header>
        <div class="tabs" id="tabs">
          {links}
        </div>
        <div class="wrap">
          {frames}
        </div>
        <script>
          function getCookie(name){{
            try {{
              const parts = document.cookie.split(';').map(v => v.trim());
              const kv = parts.find(v => v.startsWith(name + '='));
              return kv ? decodeURIComponent(kv.split('=').slice(1).join('=')) : '';
            }} catch(e) {{ return ''; }}
          }}
          function getApiKey(){{ return getCookie('shopsquire_api_key') || ''; }}
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
          // Update Incidents link with count and deep-link to latest room
          (async function(){{
            try{{
              const headers = getApiKey() ? {{ 'x-api-key': getApiKey() }} : undefined;
              const r = await fetch('/api/v1/admin/incidents/', {{ headers }});
              const j = await r.json();
              const incs = (j && j.incidents) ? j.incidents : [];
              const a = document.getElementById('incLink');
              if(!a) return;
              a.textContent = 'Incidents' + (Array.isArray(incs) && incs.length ? ' (' + incs.length + ')' : '');
              if(Array.isArray(incs) && incs.length){{
                const latest = incs[0];
                const id = (latest && latest.id) ? latest.id.toString() : '';
                if(id){{
                  a.onclick = function(ev){{ ev.preventDefault(); window.open('/merchant/incident-room?incident_id=' + encodeURIComponent(id), '_blank'); }};
                }}
              }}
            }}catch(e){{}}
          }})();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/incident-room", response_class=HTMLResponse)
def merchant_incident_room(request: Request, incident_id: str | None = None):
    """Human escalation console entrypoint (local demo).

    Deep-links into the React escalation console (queue + chat + context).
    """
    if not (_is_loopback(request) or _is_local_demo_host(request)):
        raise HTTPException(status_code=403, detail="incident_room_local_only")

    inc = (incident_id or "").strip()
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
          const next = new URL('/merchant/app/index.html', window.location.origin);
          next.searchParams.set('tab', 'escalations');
          const incident = __INCIDENT_JSON__;
          if (incident) next.searchParams.set('incident_id', incident);
          window.location.href = next.toString();
        </script>
      </body>
    </html>
    """.replace("__INCIDENT_JSON__", json.dumps(inc))
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
              <span class="pill"><span>API Key</span> <span class="mono" id="apikey_hint">(cookie/session or env key)</span></span>
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
          function getCookie(name){{
            try {{
              const parts = document.cookie.split(';').map(v => v.trim());
              const kv = parts.find(v => v.startsWith(name + '='));
              return kv ? decodeURIComponent(kv.split('=').slice(1).join('=')) : '';
            }} catch(e) {{ return ''; }}
          }}
          function getApiKey(){{ return getCookie('shopsquire_api_key') || ''; }}
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
              const headers = getApiKey() ? {{ 'x-api-key': getApiKey() }} : undefined;
              const r = await fetch('/api/v1/admin/incidents/', {{ headers }});
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
                      headers: (getApiKey() ? {{ 'x-api-key': getApiKey() }} : undefined),
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


@router.get("/email-lab", response_class=HTMLResponse)
def merchant_email_lab(request: Request):
    """Email Security Triage Lab (local demo).

    Compose emails with attachments, run analysis via /api/v1/email_security/evaluate,
    and stream the decision trace (SSE) on the right-side panel.
    """
    if not (_is_loopback(request) or _is_local_demo_host(request)):
        raise HTTPException(status_code=403, detail="email_lab_local_only")

    html = """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Email Security Triage Lab</title>
        <style>
          :root { --bg:#0b1220; --fg:#e5e7eb; --muted:#94a3b8; --card:#0f172a; --accent:#f97316; }
          body { margin:0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial; background: var(--bg); color: var(--fg); }
          header { padding: 12px 14px; display:flex; justify-content:space-between; align-items:center; background: linear-gradient(90deg, #0b1220, #101a33); border-bottom: 1px solid rgba(148,163,184,0.2); }
          .brand { font-weight: 700; letter-spacing: 0.2px; }
          .sub { color: var(--muted); font-size: 12px; }
          .wrap { display:grid; grid-template-columns: 320px 1fr 380px; gap:10px; height: calc(100vh - 60px); }
          .col { border-right: 1px solid rgba(148,163,184,0.15); }
          .pane { padding: 10px 12px; }
          .card { border:1px solid rgba(148,163,184,0.18); border-radius: 12px; background: rgba(15,23,42,0.45); }
          .card h4 { margin: 0; padding: 10px 12px; border-bottom:1px solid rgba(148,163,184,0.14); font-size: 13px; color: #cbd5e1; }
          .card .body { padding: 10px 12px; }
          input, textarea, select { width: 100%; padding:8px 10px; border-radius:10px; border:1px solid rgba(148,163,184,0.25); background:#0b1220; color:#e5e7eb; }
          textarea { min-height: 180px; resize: vertical; }
          .row { display:flex; gap:10px; align-items:center; }
          .btn { padding:8px 10px; border-radius:10px; border:1px solid rgba(148,163,184,0.25); background:#111827; color:#e5e7eb; cursor:pointer; }
          .btn:hover { border-color: rgba(249,115,22,0.6); }
          .pill { display:inline-flex; align-items:center; gap:8px; padding: 6px 10px; border:1px solid rgba(148,163,184,0.18); border-radius: 999px; background: rgba(2,6,23,0.35); font-size: 12px; color:#cbd5e1; }
          .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
          .list { display:flex; flex-direction:column; gap:8px; max-height: 240px; overflow:auto; }
          .item { display:flex; justify-content:space-between; gap: 10px; padding: 8px 10px; border:1px solid rgba(148,163,184,0.16); border-radius: 12px; cursor:pointer; background: rgba(2,6,23,0.2); }
          .item:hover { border-color: rgba(249,115,22,0.55); }
          .small { font-size: 11px; color: #94a3b8; }
          .trace { height: calc(100vh - 180px); overflow:auto; padding: 8px 10px; border:1px solid rgba(148,163,184,0.18); border-radius: 12px; background: rgba(2,6,23,0.2); }
          .ev { margin-bottom:8px; padding:8px 10px; border-left: 3px solid rgba(249,115,22,0.45); background: rgba(15,23,42,0.55); border-radius: 8px; }
          .ev .meta { font-size: 11px; color:#9ca3af; margin-bottom:4px; }
        </style>
      </head>
      <body>
        <header>
          <div>
            <div class="brand">ShopSquire | Email Security Triage Lab</div>
            <div class="sub">Compose + Attachments → Analyze → Decision Trace</div>
          </div>
          <div class="row">
            <span class="pill">API: <span id="api_health">checking…</span></span>
            <button class="btn" onclick="window.open('/merchant/dashboard','_blank')">Merchant BI</button>
            <button class="btn" onclick="window.open('/merchant/incident-room','_blank')">Escalations</button>
          </div>
        </header>
        <div class="wrap">
          <div class="pane col">
            <div class="card">
              <h4>Inbox (Simulated)</h4>
              <div class="body">
                <div class="row" style="margin-bottom:8px;">
                  <button class="btn" onclick="newEmailPreset()">New Email</button>
                  <input id="search" placeholder="Search…" />
                </div>
                <div class="list" id="inbox"></div>
              </div>
            </div>
          </div>
          <div class="pane">
            <div class="card">
              <h4>Viewer / Composer</h4>
              <div class="body">
                <div class="row"><div style="min-width:60px">To</div><input id="to" placeholder="accounts@supplier.com" /></div>
                <div class="row" style="margin-top:8px"><div style="min-width:60px">Subject</div><input id="subject" placeholder="Supplier remittance update" /></div>
                <div style="margin-top:8px">Body</div>
                <textarea id="body" placeholder="Type email body…"></textarea>
                <div style="margin-top:8px">Attachments</div>
                <input type="file" id="files" multiple />
                <div id="att_list" class="small" style="margin-top:6px"></div>
                <div class="row" style="margin-top:10px">
                  <button class="btn" aria-label="Analyze email and populate security matrix" onclick="analyze()">Analyze</button>
                  <button class="btn" aria-label="Analyze email and escalate to incident room" onclick="submitEscalate()">Submit & Escalate</button>
                  <button class="btn" aria-label="Load email lab demo assets" onclick="loadDemoAssets()">Load Demo Assets</button>
                  <button class="btn" aria-label="Simulate agent events in decision trace" onclick="simulateAgents()">Simulate Agents</button>
                  <span class="small" id="status"></span>
                </div>
                <div style="margin-top:10px">
                  <div class="pill">Verdict: <span id="verdict">n/a</span></div>
                  <div class="small" id="reasons"></div>
                  <div class="small" id="extract"></div>
                </div>
              </div>
            </div>
          </div>
          <div class="pane col">
            <div class="card">
              <h4>Decision Trace & Security Matrix</h4>
              <div class="body">
                <div class="small">Trace ID: <span class="mono" id="trace_id">n/a</span></div>
                <div class="trace" id="trace"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px;">
              <h4>Related Incident</h4>
              <div class="body">
                <div class="small">Status: <span id="inc_status">none</span></div>
                <div id="inc_card" style="display:none; margin-top:8px;">
                  <div class="row" style="gap:8px; align-items:center; flex-wrap:wrap;">
                    <span class="pill">ID <span class="mono" id="inc_id">-</span></span>
                    <span class="pill">Severity <span id="inc_sev">-</span></span>
                    <span class="pill">Playbook <span id="inc_pb">-</span></span>
                    <button class="btn" id="inc_join">Join Room</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <script>
          const presets = [
            { label: 'Supplier invoice (Warn)', subject: 'Invoice settlement', body: 'Please see attached invoice. Banking details have recently changed.' },
            { label: 'Bank details update (High)', subject: 'Updated Payment Details', body: 'Our banking details have changed. Disregard previous remittance instructions.' },
            { label: 'Shipping delay notice (Info)', subject: 'Shipping delay', body: 'Minor delay expected with current shipment.' },
          ];
          let currentDecisionId = null;
          let es = null;
          function getCookie(name){
            try{
              const parts = document.cookie.split(';').map(v => v.trim());
              const kv = parts.find(v => v.startsWith(name + '='));
              return kv ? decodeURIComponent(kv.split('=').slice(1).join('=')) : '';
            } catch(e) { return ''; }
          }
          function getApiKey(){
            try { return getCookie('shopsquire_api_key') || ''; } catch(e){ return ''; }
          }
          function getOwnerKey(){
            try {
              const admin = getCookie('shopsquire_admin_key') || '';
              if(admin) return admin;
              const general = getCookie('shopsquire_api_key') || '';
              if(general && general.startsWith('sk_')) return general;
              return 'local-owner-key';
            } catch(e){ return 'local-owner-key'; }
          }
          async function ping(){
            try { const r = await fetch('/health'); const j = await r.json(); document.getElementById('api_health').textContent = (j && j.status) ? j.status : 'unknown'; } catch(e){ document.getElementById('api_health').textContent = 'down'; }
          }
          ping();
          function newEmailPreset(){ document.getElementById('to').value='accounts@ingramfаke.com.au'; document.getElementById('subject').value='Updated Payment Details'; document.getElementById('body').value='We are changing our payment procedures in the next couple of weeks. Disregard any previous remittance instructions.'; }
          function renderInbox(){ const list = document.getElementById('inbox'); list.innerHTML=''; for(const p of presets){ const d=document.createElement('div'); d.className='item'; d.innerHTML=`<div><div>${p.label}</div><div class='small'>${p.subject}</div></div><div class='small'>${p.body.slice(0,60)}…</div>`; d.onclick=()=>{ document.getElementById('subject').value=p.subject; document.getElementById('body').value=p.body; }; list.appendChild(d);} }
          renderInbox();
          document.getElementById('files').addEventListener('change', async (ev)=>{ const out=[]; for(const f of ev.target.files){ const b64 = await toB64(f); const sha = await sha256(f); out.push(`${f.name} · ${sha}`); } document.getElementById('att_list').textContent = out.join('\n'); });
          function toB64(file){ return new Promise((res,rej)=>{ const r=new FileReader(); r.onload=()=>res(r.result); r.onerror=rej; r.readAsDataURL(file); }); }
          async function sha256(file){ const buf = await file.arrayBuffer(); const dig = await crypto.subtle.digest('SHA-256', buf); const arr = Array.from(new Uint8Array(dig), b=>b.toString(16).padStart(2,'0')); return arr.join(''); }
          function collectAttachments(){ const files = document.getElementById('files').files; const atts=[]; for(const f of files){ atts.push({ name: f.name, content_type: f.type, size_bytes: f.size, content_b64: null }); }
            // Re-read b64 for payload construction
            return Promise.all(Array.from(files).map(f=>toB64(f))).then(b64s=>{ for(let i=0;i<b64s.length;i++){ atts[i].content_b64 = b64s[i]; } return atts; }); }
          async function loadDemoAssets(){
            document.getElementById('status').textContent='Loading demo assets…';
            const targets = [
              { url: '/static/email_lab/invoice_demo.md', name: 'invoice_demo.md', type: 'text/markdown' },
              { url: '/static/email_lab/email_demo.eml', name: 'email_demo.eml', type: 'message/rfc822' },
              { url: '/static/email_lab/homoglyph_demo.txt', name: 'homoglyph_demo.txt', type: 'text/plain' },
            ];
            const atts=[]; const list=[];
            for(const t of targets){
              try{
                const r = await fetch(t.url);
                const b = await r.arrayBuffer();
                const b64 = 'data:' + t.type + ';base64,' + btoa(String.fromCharCode(...new Uint8Array(b)));
                const sha = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', b)), b=>b.toString(16).padStart(2,'0')).join('');
                atts.push({ name: t.name, content_type: t.type, size_bytes: b.byteLength, content_b64: b64 });
                list.push(`${t.name} · ${sha}`);
              }catch(e){ /* ignore */ }
            }
            // Stash into a hidden file list by creating virtual File objects isn't trivial; pass via global
            window.__demoAtts = atts;
            document.getElementById('att_list').textContent = list.join('\n');
            document.getElementById('status').textContent='Demo assets ready';
          }
          async function collectAllAttachments(){
            const fromUpload = await collectAttachments();
            const fromDemo = Array.isArray(window.__demoAtts) ? window.__demoAtts : [];
            return fromUpload.concat(fromDemo);
          }
          function pushTraceNotice(eventType, payload){
            try{
              const box = document.getElementById('trace');
              const d = document.createElement('div');
              d.className = 'ev';
              const ts = new Date().toISOString();
              d.innerHTML = `<div class='meta'>${eventType} · ${ts}</div><div class='mono'>${JSON.stringify(payload || {}, null, 0).slice(0, 500)}</div>`;
              box.appendChild(d);
              box.scrollTop = box.scrollHeight;
            }catch(e){}
          }
          async function analyze(){ document.getElementById('status').textContent='Analyzing…'; const to = document.getElementById('to').value.trim(); const subj = document.getElementById('subject').value.trim(); const body = document.getElementById('body').value.trim(); const atts = await collectAllAttachments(); const payload = { message_id: 'lab-'+Math.random().toString(36).slice(2), from_addr: to, reply_to: to, subject: subj, body: body, attachments: atts, external_sender: true, dmarc_fail: false, spf_result: 'neutral', dkim_result: 'neutral', dmarc_result: 'quarantine', dmarc_policy: 'reject', vendor_domain: 'ingramfake.com.au' };
            try {
              // First try merchant key; on authz/authn failure retry with owner/developer key for local demo.
              let r = await fetch('/api/v1/email_security/evaluate', { method:'POST', headers: { 'Content-Type':'application/json', 'x-api-key': getApiKey() }, body: JSON.stringify(payload) });
              if (r.status === 401 || r.status === 403) {
                r = await fetch('/api/v1/email_security/evaluate', { method:'POST', headers: { 'Content-Type':'application/json', 'x-api-key': getOwnerKey() }, body: JSON.stringify(payload) });
              }
              const j = await r.json().catch(()=>null); if(!r.ok || !j){ const err=(j && (j.detail||j.error) ? (j.detail||j.error) : 'no details'); document.getElementById('status').textContent='Analyze failed ('+r.status+'): '+err; pushTraceNotice('analyze_failed', { status: r.status, error: err, endpoint: '/api/v1/email_security/evaluate' }); return; }
              document.getElementById('verdict').textContent = (j.verdict_action || 'unknown') + ' / ' + (j.severity || 'info');
              document.getElementById('reasons').textContent = (j.reasons||[]).slice(0,6).join(', ');
              const ex = []; try { const ev = j.evidence_snapshot||{}; const ioc = ev.ioc_counts||{}; ex.push(`IOC: url=${ioc.url||0} domain=${ioc.domain||0} hash=${ioc.hash||0}`); if(ev.sender_trust && ev.sender_trust.sender_trust_score!=null){ ex.push(`Trust=${ev.sender_trust.sender_trust_score}`); } } catch(e) {}
              document.getElementById('extract').textContent = ex.join(' | ');
              const tid = j.decision_trace_id || j.decision_id || payload.message_id; if (tid) { attachTrace(tid); }
              document.getElementById('status').textContent='Done';
            } catch(e) { document.getElementById('status').textContent='Analyze error'; pushTraceNotice('analyze_error', { endpoint: '/api/v1/email_security/evaluate', error: String(e && e.message ? e.message : e) }); }
          }
          async function submitEscalate(){
            document.getElementById('status').textContent='Analyzing & escalating…';
            const to = document.getElementById('to').value.trim();
            const subj = document.getElementById('subject').value.trim();
            const body = document.getElementById('body').value.trim();
            const atts = await collectAllAttachments();
            const payload = { message_id: 'lab-'+Math.random().toString(36).slice(2), from_addr: to, reply_to: to, subject: subj, body: body, attachments: atts, external_sender: true, dmarc_fail: false, spf_result: 'neutral', dkim_result: 'neutral', dmarc_result: 'quarantine', dmarc_policy: 'reject', vendor_domain: 'ingramfake.com.au' };
            try {
              let r = await fetch('/api/v1/email_security/evaluate', { method:'POST', headers: { 'Content-Type':'application/json', 'x-api-key': getApiKey() }, body: JSON.stringify(payload) });
              if (r.status === 401 || r.status === 403) {
                r = await fetch('/api/v1/email_security/evaluate', { method:'POST', headers: { 'Content-Type':'application/json', 'x-api-key': getOwnerKey() }, body: JSON.stringify(payload) });
              }
              const j = await r.json().catch(()=>null);
              if(!r.ok || !j){ const err=(j && (j.detail||j.error) ? (j.detail||j.error) : 'no details'); document.getElementById('status').textContent='Analyze failed ('+r.status+')'; pushTraceNotice('submit_analyze_failed', { status: r.status, error: err, endpoint: '/api/v1/email_security/evaluate' }); return; }
              document.getElementById('verdict').textContent = (j.verdict_action || 'unknown') + ' / ' + (j.severity || 'info');
              document.getElementById('reasons').textContent = (j.reasons||[]).slice(0,6).join(', ');
              const tid = j.decision_trace_id || j.decision_id || payload.message_id; if (tid) { attachTrace(tid); }
              // Now escalate: create an incident via the public escalation endpoint
              try {
                const escPayload = { case_id: j.decision_trace_id || j.decision_id || payload.message_id, trace_id: j.decision_trace_id, reason: 'email_lab_manual_escalation', context: { subject: subj, verdict: j.verdict_action, severity: j.severity, reasons: (j.reasons||[]).slice(0,6) } };
                const escR = await fetch('/api/v1/incidents/escalate', { method:'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(escPayload) });
                const escJ = await escR.json();
                if(escJ && escJ.ok && escJ.incident_id){
                  document.getElementById('status').textContent='Escalated: '+escJ.incident_id;
                  // Re-search for related incident to display in right panel
                  if(j.decision_trace_id){ findRelatedIncident(j.decision_trace_id); }
                } else {
                  document.getElementById('status').textContent='Analyzed (escalation note: '+(escJ?.detail||'no incident created')+')';
                  pushTraceNotice('escalation_note', { status: escR.status, detail: (escJ?.detail||'no incident created') });
                }
              } catch(esc) { document.getElementById('status').textContent='Analyzed (escalation failed)'; pushTraceNotice('escalation_error', { endpoint: '/api/v1/incidents/escalate', error: String(esc && esc.message ? esc.message : esc) }); }
            } catch(e) { document.getElementById('status').textContent='Submit error'; pushTraceNotice('submit_error', { endpoint: '/api/v1/email_security/evaluate', error: String(e && e.message ? e.message : e) }); }
          }
          function attachTrace(traceId){ currentDecisionId = traceId; document.getElementById('trace_id').textContent = traceId; const box = document.getElementById('trace'); box.innerHTML=''; if(es) try{ es.close(); }catch(e){}
            es = new EventSource(`/api/v1/trace/${encodeURIComponent(traceId)}/events/stream`);
            function formatFrameworks(fr){
              try{
                const chips = [];
                const mitre = Array.isArray(fr?.mitre_attack) ? fr.mitre_attack : [];
                const stride = Array.isArray(fr?.stride_categories) ? fr.stride_categories : [];
                const pasta = (fr?.pasta_stage || '').toString();
                const comp = (fr?.compliance?.frameworks || []);
                const owasp = Array.isArray(fr?.owasp_llm_top10) ? fr.owasp_llm_top10 : [];
                const scenarios = Array.isArray(fr?.scenarios) ? fr.scenarios : [];
                if(mitre.length){ chips.push(`<span class='pill'>MITRE ${mitre.slice(0,2).join(', ')}</span>`); }
                if(stride.length){ chips.push(`<span class='pill'>STRIDE ${stride.slice(0,2).join(', ')}</span>`); }
                if(pasta){ chips.push(`<span class='pill'>PASTA ${pasta}</span>`); }
                if(owasp.length){ chips.push(`<span class='pill'>OWASP LLM ${owasp.slice(0,2).join(', ')}</span>`); }
                let shown = 0;
                for(const f of comp){ if(shown>=2) break; const fw = (f?.framework||'').toString(); const c = Array.isArray(f?.controls) ? f.controls : []; if(fw && c.length){ chips.push(`<span class='pill'>${fw} ${c[0]}</span>`); shown++; } }
                // Scenario badges (titles)
                let sShown = 0;
                for(const s of scenarios){ if(sShown>=2) break; const t = (s?.title||'').toString(); if(t){ chips.push(`<span class='pill'>Scenario ${t}</span>`); sShown++; } }
                return chips.join(' ');
              }catch(e){ return ''; }
            }
            es.onmessage = (ev)=>{ try { const arr = JSON.parse(ev.data); for(const it of (arr||[])){
                const d=document.createElement('div'); d.className='ev'; const tag = (it.event_type||'event'); const ts = it.created_at || '';
                const frameworks = formatFrameworks(it?.payload?.frameworks || {});
                d.innerHTML = `<div class='meta'>${tag} · ${ts}</div>` + (frameworks ? (`<div class='small' style='margin-bottom:6px; display:flex; gap:6px; flex-wrap:wrap;'>${frameworks}</div>`) : '') + `<div class='mono'>${JSON.stringify(it.payload||{}, null, 0).slice(0, 300)}</div>`;
                box.appendChild(d); box.scrollTop = box.scrollHeight; } } catch(e){} };
            es.onerror = ()=>{};
            // Attempt to find a related incident for this trace.
            findRelatedIncident(traceId);
          }
          async function findRelatedIncident(traceId){
            try{
              document.getElementById('inc_status').textContent = 'searching…';
              const r = await fetch('/api/v1/admin/email_security/incidents?limit=20&has_ticket=true');
              let j = null;
              if(r.status === 401 || r.status === 403){
                const r2 = await fetch('/api/v1/admin/email_security/incidents?limit=20&has_ticket=true', { headers: { 'x-api-key': getOwnerKey() } });
                j = await r2.json();
              } else {
                j = await r.json();
              }
              const incs = (j && j.incidents) ? j.incidents : [];
              const match = incs.find(it => {
                const ev = (it && it.evidence_snapshot) ? it.evidence_snapshot : {};
                return (ev.trace_id === traceId) || (ev.decision_id === traceId);
              });
              if(!match){ document.getElementById('inc_status').textContent = 'none'; return; }
              document.getElementById('inc_status').textContent = 'found';
              document.getElementById('inc_card').style.display = 'block';
              document.getElementById('inc_id').textContent = match.id || '-';
              document.getElementById('inc_sev').textContent = (match.severity || 'unknown').toString();
              document.getElementById('inc_pb').textContent = ((match.playbook||{}).title || 'n/a');
              try{
                const t = await fetch(`/api/v1/admin/incidents/${encodeURIComponent(match.id)}/room/token`, { method:'POST', headers:{ 'x-api-key': getOwnerKey() } });
                const tj = await t.json();
                if(tj && tj.staff_token){
                  const tok = tj.staff_token;
                  const btn = document.getElementById('inc_join');
                  btn.onclick = function(){ window.open(`/merchant/incident-room-lite?incident_id=${encodeURIComponent(match.id)}&token=${encodeURIComponent(tok)}`, '_blank'); };
                }
              }catch(e){}
            }catch(e){ document.getElementById('inc_status').textContent = 'error'; }
          }
          async function simulateAgents(){
            const traceId = currentDecisionId || ('sim-'+Math.random().toString(36).slice(2));
            attachTrace(traceId);
            const batch = [
              { trace_id: traceId, event_type: 'security_scan', source_type: 'agent', source_id: 'Email_Security_Agent', payload: { severity: 'warning', signals: ['bank_change_request','confusable_homoglyph_domain'] } },
              { trace_id: traceId, event_type: 'sender_trust_assessed', source_type: 'agent', source_id: 'Email_Trust_Graph_Agent', payload: { sender_trust_score: 0.32, vendor_relationship_confidence: 0.28 } },
              { trace_id: traceId, event_type: 'ioc_enrichment_fusion', source_type: 'agent', source_id: 'IOC_Enrichment_Agent', payload: { malicious_hits: 0, cache_hits: 1, provider_weights: { local_cache: 0.6 } } },
              { trace_id: traceId, event_type: 'policy_gate', source_type: 'agent', source_id: 'Email_Policy_Gate_Agent', payload: { decision: 'review', reason: 'rule_first_gate' } },
            ];
            try{
              const r = await fetch('/api/v1/trace/events', { method:'POST', headers:{ 'Content-Type':'application/json', 'x-api-key': getApiKey() }, body: JSON.stringify(batch) });
              if(!r.ok){ document.getElementById('status').textContent='Simulation failed'; return; }
              document.getElementById('status').textContent='Simulation events sent';
            }catch(e){ document.getElementById('status').textContent='Simulation error'; }
          }
          // Explicit exports for Playwright/runtime checks.
          window.analyze = analyze;
          window.simulateAgents = simulateAgents;
          // Preload defaults
          newEmailPreset();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
