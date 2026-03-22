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

    import os as _os
    _owner_key = _os.getenv("OWNER_API_KEY", "local-owner-key")

    html = """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Email Security Triage Lab</title>
        <style>
          /* ── ShopSquire Enterprise Theme ── off-white / warm-slate palette ── */
          :root {
            --bg:       #f5f6f8;    /* warm off-white page background */
            --surface:  #ffffff;    /* card white */
            --surface2: #f0f2f5;    /* alternating surface */
            --border:   #dde1e8;    /* subtle divider */
            --fg:       #1a1f2e;    /* near-black text */
            --fg2:      #4a5568;    /* secondary text */
            --muted:    #8a95a8;    /* muted / hints */
            --accent:   #2c5fe6;    /* primary action blue */
            --accent2:  #e8501a;    /* warning / escalate orange */
            --success:  #0f8a5e;    /* success green */
            --header-bg:#1e2d4d;    /* deep navy header — single dark element */
            --header-fg:#eef1f7;
            --radius:   10px;
          }
          *, *::before, *::after { box-sizing: border-box; }
          body { margin:0; font-family: Inter, "Segoe UI", system-ui, -apple-system, Arial, sans-serif; background: var(--bg); color: var(--fg); font-size: 13px; line-height: 1.5; }
          /* Header */
          header { padding: 0 18px; height: 52px; display:flex; justify-content:space-between; align-items:center; background: var(--header-bg); box-shadow: 0 2px 8px rgba(0,0,0,0.18); }
          .brand { font-weight: 700; font-size: 14px; color: var(--header-fg); letter-spacing: 0.2px; }
          .sub { color: rgba(238,241,247,0.6); font-size: 11px; margin-top: 2px; }
          /* Layout */
          .wrap { display:grid; grid-template-columns: 310px 1fr 390px; gap:0; height: calc(100vh - 52px); overflow: hidden; }
          .col { border-right: 1px solid var(--border); overflow-y: auto; }
          .pane { padding: 12px 14px; }
          /* Cards */
          .card { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 10px; }
          .card h4 { margin: 0; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 12px; font-weight: 600; color: var(--fg2); text-transform: uppercase; letter-spacing: 0.5px; background: var(--surface2); border-radius: var(--radius) var(--radius) 0 0; }
          .card .body { padding: 12px 14px; }
          /* Form controls */
          input, textarea, select { width: 100%; padding: 7px 10px; border-radius: 7px; border: 1px solid var(--border); background: var(--surface); color: var(--fg); font-size: 12px; outline: none; transition: border-color 0.15s; }
          input:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(44,95,230,0.12); }
          textarea { min-height: 160px; resize: vertical; }
          input[type=file] { border-style: dashed; padding: 10px; cursor: pointer; }
          /* Labels */
          .field-label { font-size: 11px; font-weight: 600; color: var(--fg2); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.4px; }
          /* Rows */
          .row { display:flex; gap:8px; align-items:center; }
          /* Buttons */
          .btn { padding: 7px 13px; border-radius: 7px; border: 1px solid var(--border); background: var(--surface); color: var(--fg); cursor: pointer; font-size: 12px; font-weight: 500; white-space: nowrap; transition: all 0.15s; }
          .btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
          .btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
          .btn-primary:hover { background: #1e4ac8; border-color: #1e4ac8; }
          .btn-danger { background: var(--accent2); color: #fff; border-color: var(--accent2); }
          .btn-danger:hover { background: #c43c10; border-color: #c43c10; }
          /* Pills / badges */
          .pill { display:inline-flex; align-items:center; gap:4px; padding: 3px 9px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface2); font-size: 11px; color: var(--fg2); font-weight: 500; }
          /* Inbox items */
          .list { display:flex; flex-direction:column; gap:6px; max-height: 220px; overflow:auto; }
          .item { display:flex; flex-direction:column; gap:4px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; cursor:pointer; background: var(--surface); transition: all 0.12s; }
          .item:hover { border-color: var(--accent); background: rgba(44,95,230,0.04); }
          .item .item-from { font-weight: 600; font-size: 12px; color: var(--fg); }
          .item .item-sub { font-size: 11px; color: var(--fg2); }
          .item .item-preview { font-size: 11px; color: var(--muted); }
          /* Verdict badge */
          #verdict { display: inline-block; font-weight: 700; font-size: 13px; }
          /* Small / muted */
          .small { font-size: 11px; color: var(--muted); }
          .mono { font-family: ui-monospace, "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace; font-size: 11px; }
          /* Trace / SSE stream */
          .trace { overflow:auto; padding: 8px; border: 1px solid var(--border); border-radius: 8px; background: #f8f9fb; }
          .ev { margin-bottom: 6px; padding: 7px 10px; border-left: 3px solid var(--accent); background: var(--surface); border-radius: 0 6px 6px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
          .ev .meta { font-size: 10px; color: var(--muted); margin-bottom: 3px; }
          /* Severity verdict bar states */
          .sev-error   { background: #fff1f0; border-left: 4px solid #ef4444; color: #b91c1c; }
          .sev-warning { background: #fffbeb; border-left: 4px solid #f59e0b; color: #92400e; }
          .sev-info    { background: #eff6ff; border-left: 4px solid #3b82f6; color: #1d4ed8; }
          .right-rail.detached {
            position: fixed;
            top: 72px;
            right: 16px;
            width: min(560px, 44vw);
            max-height: calc(100vh - 88px);
            z-index: 1000;
            background: rgba(243, 246, 251, 0.98);
            border: 1px solid var(--border);
            border-radius: 14px;
            box-shadow: 0 24px 64px rgba(15, 23, 42, 0.24);
            padding: 10px;
          }
          .rail-toolbar { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }
          .card-grid { display:grid; grid-template-columns:1fr; gap:10px; }
          .summary-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
          .finding-list { margin:0; padding-left:16px; }
          .finding-list li { margin:4px 0; }
          .section-label { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:#64748b; margin-bottom:4px; font-weight:700; }
          .evidence-block { padding:10px; border:1px solid var(--border); border-radius:10px; background:#fff; margin-top:8px; }
          .attachment-row { padding:10px; border:1px solid var(--border); border-radius:10px; background:#fff; margin-top:8px; }
          .thumb-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-top:8px; }
          .thumb-grid img { width:100%; border:1px solid var(--border); border-radius:8px; background:#fff; }
          .trace-toggle { display:flex; gap:6px; margin:8px 0; }
          .trace-toggle button.active { background:#1d4ed8; color:#fff; border-color:#1d4ed8; }
          /* Scrollbar */
          ::-webkit-scrollbar { width: 5px; height: 5px; }
          ::-webkit-scrollbar-track { background: transparent; }
          ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        </style>
      </head>
      <body>
        <header>
          <div>
            <div class="brand">ShopSquire &nbsp;·&nbsp; Email Security Triage Lab</div>
            <div class="sub">Compose · Attach · Analyze · Decision Trace · Escalate</div>
          </div>
          <div class="row">
            <span class="pill" style="background:rgba(238,241,247,0.1);color:#eef1f7;border-color:rgba(238,241,247,0.2);">API <span id="api_health" style="font-weight:700;">checking…</span></span>
            <button class="btn btn-primary" style="font-size:12px;" onclick="window.open('/merchant/dashboard','_blank')">Merchant BI</button>
            <button class="btn" style="background:rgba(238,241,247,0.1);color:#eef1f7;border-color:rgba(238,241,247,0.2);font-size:12px;" onclick="window.open('/merchant/incident-room','_blank')">Escalations</button>
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
                <div class="row"><div class="field-label" style="min-width:60px">To</div><input id="to" placeholder="accounts@supplier.com" /></div>
                <div class="row" style="margin-top:8px"><div class="field-label" style="min-width:60px">Subject</div><input id="subject" placeholder="Supplier remittance update" /></div>
                <div style="margin-top:10px" class="field-label">Body</div>
                <textarea id="body" placeholder="Type email body…"></textarea>
                <div style="margin-top:10px" class="field-label">Attachments</div>
                <input type="file" id="files" multiple />
                <div id="att_list" class="small mono" style="margin-top:6px; white-space:pre-wrap;"></div>
                <div class="row" style="margin-top:12px; flex-wrap:wrap; gap:6px;">
                  <button class="btn btn-primary" aria-label="Analyze email and populate security matrix" onclick="analyze()">&#128269; Analyze</button>
                  <button class="btn btn-danger" aria-label="Analyze email and escalate to incident room" onclick="submitEscalate()">&#9888; Escalate</button>
                  <button class="btn" aria-label="Load email lab demo assets" onclick="loadDemoAssets()">&#128196; Demo</button>
                  <button class="btn" aria-label="Simulate agent events in decision trace" onclick="simulateAgents()">&#129302; Agents</button>
                  <span class="small" id="status" style="flex:1; padding-left:4px;"></span>
                </div>
                <div style="margin-top:12px; padding:10px 12px; border:1px solid var(--border); border-radius:8px; background:var(--surface2);">
                  <div class="field-label" style="margin-bottom:6px;">Last Verdict</div>
                  <div><span id="verdict" class="pill">n/a</span></div>
                  <div class="small" id="reasons" style="margin-top:6px; line-height:1.6;"></div>
                  <div class="small mono" id="extract" style="margin-top:4px;"></div>
                </div>
              </div>
            </div>
          </div>
          <div class="pane col right-rail" id="right_rail" style="overflow-y:auto; max-height:calc(100vh - 60px);">
            <div class="rail-toolbar">
              <button class="btn" type="button" onclick="toggleDetachRightRail()">Detach Rail</button>
              <button class="btn" type="button" onclick="openRightRailTab()">Open In New Tab</button>
            </div>
            <div class="card" id="exec_card" style="display:none;">
              <h4>Executive Summary</h4>
              <div class="body">
                <div class="summary-grid">
                  <div>
                    <div class="section-label">What Happened</div>
                    <div id="exec_what_happened" class="small"></div>
                  </div>
                  <div>
                    <div class="section-label">Business Risk</div>
                    <div id="exec_business_risk" class="small"></div>
                  </div>
                </div>
                <div style="margin-top:8px;">
                  <div class="section-label">Why It Was Flagged</div>
                  <div id="exec_why_flagged" class="small"></div>
                </div>
                <div style="margin-top:8px;">
                  <div class="section-label">Immediate Actions</div>
                  <div id="exec_immediate_actions" class="small"></div>
                </div>
                <div style="margin-top:8px;">
                  <div class="section-label">Recommended Next Steps</div>
                  <div id="exec_next_steps" class="small"></div>
                </div>
              </div>
            </div>
            <!-- Security Overview Panel (populated after Analyze) -->
            <div class="card" id="sec_overview" style="display:none;">
              <h4>Security Overview</h4>
              <div class="body">
                <div class="row" style="flex-wrap:wrap; gap:6px; margin-bottom:8px;" id="sec_badges"></div>
                <div id="sec_verdict_bar" style="padding:8px 10px; border-radius:8px; margin-bottom:8px; font-weight:600;"></div>
                <div class="small" id="sec_reasons_list"></div>
              </div>
            </div>
            <!-- BEC Kill Chain -->
            <div class="card" style="margin-top:10px; display:none;" id="bec_card">
              <h4>BEC Kill Chain</h4>
              <div class="body">
                <div id="bec_stage" style="font-weight:700; color:#f97316; font-size:15px;"></div>
                <div id="bec_flow" class="small" style="margin-top:6px;"></div>
                <div class="row" style="margin-top:6px; gap:6px; flex-wrap:wrap;" id="bec_badges"></div>
              </div>
            </div>
            <!-- Trust Case & Access Policy -->
            <div class="card" style="margin-top:10px; display:none;" id="trust_card">
              <h4>Trust Case & Access Policy</h4>
              <div class="body">
                <div class="row" style="gap:10px; flex-wrap:wrap;">
                  <div><div class="small">Trust Score</div><div id="trust_score" style="font-size:22px; font-weight:700;">-</div></div>
                  <div><div class="small">Level</div><div id="trust_level" style="font-size:14px; font-weight:600;">-</div></div>
                  <div><div class="small">Access</div><div id="trust_access" style="font-size:14px; font-weight:600;">-</div></div>
                </div>
                <div class="small" style="margin-top:6px;" id="trust_actions"></div>
                <div class="small" style="margin-top:4px; color:#94a3b8;" id="trust_reasons"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="infra_card">
              <h4>Sender / Infrastructure Correlation</h4>
              <div class="body">
                <div id="infra_sections" class="small"></div>
              </div>
            </div>
            <!-- Threat Correlation (MITRE/DREAD/CVSS/KEV/PASTA) -->
            <div class="card" style="margin-top:10px; display:none;" id="threat_card">
              <h4>Threat Correlation</h4>
              <div class="body">
                <div class="row" style="gap:6px; flex-wrap:wrap;" id="threat_badges"></div>
                <div style="margin-top:8px; display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                  <div><div class="small">DREAD avg</div><div id="dread_avg" style="font-weight:700;">-</div></div>
                  <div><div class="small">CVSS</div><div id="cvss_score" style="font-weight:700;">-</div></div>
                  <div><div class="small">Kill Chain</div><div id="kc_stage" style="font-weight:700;">-</div></div>
                  <div><div class="small">PASTA Stage</div><div id="pasta_stage" style="font-weight:700;">-</div></div>
                </div>
                <div class="small" style="margin-top:6px;" id="kev_list"></div>
              </div>
            </div>
            <!-- Sandbox / Detonation / IOC -->
            <div class="card" style="margin-top:10px; display:none;" id="sandbox_card">
              <h4>Sandbox & IOC Enrichment</h4>
              <div class="body">
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                  <div><div class="small">Detonation</div><div id="det_result" style="font-weight:700;">-</div></div>
                  <div><div class="small">IOC Malicious</div><div id="ioc_hits" style="font-weight:700;">0</div></div>
                  <div><div class="small">IOC Resolution</div><div id="ioc_resolution" style="font-weight:600;">-</div></div>
                  <div><div class="small">Enrichment Latency</div><div id="enrich_latency" class="small">-</div></div>
                </div>
                <div class="small" style="margin-top:6px;" id="sandbox_findings"></div>
              </div>
            </div>
            <!-- Attachment Forensics -->
            <div class="card" style="margin-top:10px; display:none;" id="attach_card">
              <h4>Attachment Forensics</h4>
              <div class="body">
                <div id="attach_forensics" class="small" style="max-height:340px; overflow:auto;"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="pdf_diff_card">
              <h4>Supplier Baseline Diff</h4>
              <div class="body">
                <div id="pdf_diff_sections" class="small"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="visual_diff_card">
              <h4>Supplier Baseline Visual Diff</h4>
              <div class="body">
                <div id="visual_diff_sections" class="small"></div>
              </div>
            </div>
            <!-- QR / OCR Findings -->
            <div class="card" style="margin-top:10px; display:none;" id="qr_card">
              <h4>QR / OCR Findings</h4>
              <div class="body">
                <div id="qr_findings" class="small"></div>
              </div>
            </div>
            <!-- Playbook Run -->
            <div class="card" style="margin-top:10px; display:none;" id="playbook_card">
              <h4>Playbook Run</h4>
              <div class="body">
                <div class="row" style="gap:6px; flex-wrap:wrap; margin-bottom:6px;">
                  <span class="pill" id="pb_name">-</span>
                  <span class="pill" id="pb_status" style="background:#22c55e22;color:#166534;">-</span>
                </div>
                <div class="small" style="margin-bottom:4px; font-weight:600;">Actions completed:</div>
                <div id="pb_actions" class="small" style="display:flex; flex-wrap:wrap; gap:4px;"></div>
                <div class="small" style="margin-top:6px; color:#94a3b8;" id="pb_next_steps"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="evidence_card">
              <h4>Evidence</h4>
              <div class="body">
                <div id="evidence_sections" class="small"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="actions_card">
              <h4>Actions</h4>
              <div class="body">
                <div id="actions_sections" class="small"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="integrations_card">
              <h4>Integrations</h4>
              <div class="body">
                <div id="integrations_sections" class="small"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="gov_card">
              <h4>Supplier Governance</h4>
              <div class="body">
                <div id="gov_sections" class="small"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="graph_card">
              <h4>Vendor Trust Graph</h4>
              <div class="body">
                <div id="graph_sections" class="small"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="tones_card">
              <h4>Verdict In 3 Views</h4>
              <div class="body">
                <div id="tones_sections" class="small"></div>
              </div>
            </div>
            <!-- Decision Trace (SSE stream) -->
            <div class="card" style="margin-top:10px;">
              <h4>Decision Trace & Security Matrix</h4>
              <div class="body">
                <div class="small">Trace ID: <span class="mono" id="trace_id">n/a</span></div>
                <div class="trace-toggle">
                  <button class="btn active" id="trace_btn_explain" type="button" onclick="setTraceMode('explain')">Explain</button>
                  <button class="btn" id="trace_btn_raw" type="button" onclick="setTraceMode('raw')">Raw</button>
                </div>
                <div class="trace" id="trace_human" style="max-height:280px;"></div>
                <div class="trace" id="trace" style="max-height:280px; display:none;"></div>
              </div>
            </div>
            <!-- Related Incident -->
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
          let currentSecurityResult = null;
          let currentConnectorHealth = null;
          let currentFeedbackSummary = null;
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
          function renderInbox(){ const list = document.getElementById('inbox'); list.innerHTML=''; for(const p of presets){ const d=document.createElement('div'); d.className='item'; d.innerHTML=`<div class='item-from'>${p.label}</div><div class='item-sub'>${p.subject}</div><div class='item-preview'>${p.body.slice(0,72)}…</div>`; d.onclick=()=>{ document.getElementById('subject').value=p.subject; document.getElementById('body').value=p.body; }; list.appendChild(d);} }
          renderInbox();
          document.getElementById('files').addEventListener('change', async (ev)=>{ try{ const out=[]; for(const f of ev.target.files){ const sha = await sha256(f); out.push(`${f.name} · ${sha}`); } document.getElementById('att_list').textContent = out.join('\\\\n'); document.getElementById('status').textContent = out.length ? `${out.length} attachment(s) ready` : ''; } catch(e){ const msg = 'Attachment read failed: ' + String(e && e.message ? e.message : e); document.getElementById('status').textContent = msg; pushTraceNotice('attachment_read_failed', { error: msg }); } });
          function bytesToBase64(bytes){ const chunk = 0x8000; let binary = ''; for(let i=0;i<bytes.length;i+=chunk){ binary += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + chunk, bytes.length))); } return btoa(binary); }
          function toB64Raw(file){ return new Promise((res,rej)=>{ const r=new FileReader(); r.onload=()=>{ try { res(bytesToBase64(new Uint8Array(r.result))); } catch(err){ rej(err); } }; r.onerror=()=>rej(r.error || new Error('file_read_failed')); r.readAsArrayBuffer(file); }); }
          async function sha256(file){ const buf = await file.arrayBuffer(); const dig = await crypto.subtle.digest('SHA-256', buf); const arr = Array.from(new Uint8Array(dig), b=>b.toString(16).padStart(2,'0')); return arr.join(''); }
          function collectAttachments(){ const files = document.getElementById('files').files; const atts=[]; for(const f of files){ atts.push({ name: f.name, content_type: f.type, size_bytes: f.size, content_b64: null }); }
            // Re-read b64 for payload construction
            return Promise.all(Array.from(files).map(f=>toB64Raw(f))).then(b64s=>{ for(let i=0;i<b64s.length;i++){ atts[i].content_b64 = b64s[i]; } return atts; }); }
          async function loadDemoAssets(){
            document.getElementById('status').textContent='Loading demo assets…';
            // Use inline demo content — static files may not exist in all environments
            const demoFiles = [
              {
                name: 'invoice_demo.txt',
                type: 'text/plain',
                text: 'INVOICE #INV-2026-0142\\\\nIngramWake Pty Ltd\\\\nABN: 51 123 456 789\\\\nBSB: 062-000\\\\nAccount: 12345678\\\\nAmount Due: $48,500.00\\\\nDue Date: 2026-04-01\\\\nPlease remit to the above account. Banking details have changed from prior invoices.',
              },
              {
                name: 'homoglyph_demo.txt',
                type: 'text/plain',
                text: 'From: accounts@ingramf\\u0430ke.com.au\\\\nSubject: Updated Payment Details\\\\nPlease note: our banking details have \\u0441hanged. Disregard any previous remittance instructions.\\\\nNew BSB: 062-111  Account: 98765432',
              },
              {
                name: 'catalog_attachment.txt',
                type: 'text/plain',
                text: 'IngramWake March 2026 Catalog\\\\nProduct Ref: IW-CAT-2026-03\\\\nNote: All orders must be remitted to our new account effective immediately.\\\\nContact: payments@ingramwake.finance',
              },
            ];
            const atts=[]; const list=[];
            for(const f of demoFiles){
              try{
                const enc = new TextEncoder().encode(f.text);
                const b64 = bytesToBase64(enc);
                const sha = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', enc)), b=>b.toString(16).padStart(2,'0')).join('');
                atts.push({ name: f.name, content_type: f.type, size_bytes: enc.byteLength, content_b64: b64 });
                list.push(`${f.name} · ${sha.slice(0,16)}…`);
              }catch(e){ list.push(`${f.name} · encode_error`); }
            }
            window.__demoAtts = atts;
            document.getElementById('att_list').textContent = list.join('\\\\n');
            document.getElementById('status').textContent=`Demo assets ready (${atts.length} inline files)`;
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
          /* ── Render structured security panels from evaluate response ── */
          function resetPlaybookRunCard(){
            try{
              window.__emailLabPlaybookRun = null;
              const pbc = document.getElementById('playbook_card');
              if(pbc) pbc.style.display = 'none';
              const name = document.getElementById('pb_name'); if(name) name.textContent = '-';
              const status = document.getElementById('pb_status'); if(status) status.textContent = '-';
              const actions = document.getElementById('pb_actions'); if(actions) actions.innerHTML = '';
              const next = document.getElementById('pb_next_steps'); if(next) next.textContent = '';
            }catch(e){}
          }
          function renderPlaybookRun(pb){
            try{
              if(!pb) return;
              const acts = Array.isArray(pb.actions_completed) ? pb.actions_completed : (Array.isArray(pb.actions) ? pb.actions : []);
              if(!(pb.playbook_id || pb.title || pb.id || acts.length || pb.status || pb.outcome)) return;
              const pbc = document.getElementById('playbook_card'); pbc.style.display='block';
              const pbName = pb.playbook_id || pb.title || pb.id || 'unknown';
              document.getElementById('pb_name').textContent = pbName;
              const pbSt = pb.status || pb.outcome || 'completed';
              document.getElementById('pb_status').textContent = pbSt;
              document.getElementById('pb_actions').innerHTML = acts.slice(0,8).map(a=>`<span class='pill'>${typeof a==='string'?a:JSON.stringify(a)}</span>`).join('');
              const nxt = Array.isArray(pb.next_steps) ? pb.next_steps.join(' · ') : (pb.next_step || '');
              document.getElementById('pb_next_steps').textContent = nxt ? ('Next: ' + nxt) : '';
            }catch(e){ pushTraceNotice('render_playbook_error', { error: String(e) }); }
          }
          function mergePlaybookRun(update){
            try{
              const prev = window.__emailLabPlaybookRun || {};
              const prevActs = Array.isArray(prev.actions_completed) ? prev.actions_completed : [];
              const nextActs = Array.isArray(update?.actions_completed) ? update.actions_completed : (Array.isArray(update?.actions) ? update.actions : []);
              const mergedActs = [];
              for(const item of prevActs.concat(nextActs)){
                const normalized = typeof item === 'string' ? item : JSON.stringify(item);
                if(normalized && !mergedActs.includes(normalized)) mergedActs.push(normalized);
              }
              const merged = Object.assign({}, prev, update || {});
              if(mergedActs.length) merged.actions_completed = mergedActs;
              window.__emailLabPlaybookRun = merged;
              renderPlaybookRun(merged);
            }catch(e){}
          }
          function ingestPlaybookTraceEvent(it){
            try{
              const payload = it?.payload || {};
              const original = String(payload._original_event_type || it?.event_type || '');
              if(payload.playbook_id || payload.title || payload.id){
                mergePlaybookRun({
                  playbook_id: payload.playbook_id || payload.id || payload.title,
                  title: payload.title || payload.playbook_id || payload.id || null,
                  status: payload.status || (original === 'playbook_selected' ? 'selected' : undefined),
                });
              }
              if(payload.action_type){
                mergePlaybookRun({
                  status: payload.status || 'running',
                  actions_completed: [payload.action_type],
                });
              }
              const executed = payload?.evidence?.result?.executed;
              if(Array.isArray(executed) && executed.length){
                mergePlaybookRun({
                  status: payload.status || 'completed',
                  actions_completed: executed.map(step => step?.action_type || step).filter(Boolean),
                });
              }
              if(original === 'playbook_run_completed' || payload.outcome || payload.next_step || payload.next_steps){
                mergePlaybookRun({
                  status: payload.status || undefined,
                  outcome: payload.outcome || undefined,
                  next_step: payload.next_step || undefined,
                  next_steps: Array.isArray(payload.next_steps) ? payload.next_steps : undefined,
                });
              }
            }catch(e){}
          }
          function escHtml(value){
            return String(value == null ? '' : value)
              .replaceAll('&', '&amp;')
              .replaceAll('<', '&lt;')
              .replaceAll('>', '&gt;')
              .replaceAll('"', '&quot;');
          }
          function listHtml(items){
            const rows = (Array.isArray(items) ? items : []).filter(Boolean);
            if(!rows.length) return '<div class="small" style="color:#94a3b8;">No additional details.</div>';
            return `<ul class="finding-list">${rows.map(item=>`<li>${escHtml(item)}</li>`).join('')}</ul>`;
          }
          function reasonToPlainEnglish(reason){
            const map = {
              oob_verification_required: 'The message asks for a change that should be verified using a trusted phone number or supplier portal.',
              bimi_visual_brand_similarity_spoof: 'Branding looks close to a known supplier, but the identity checks do not fully line up.',
              auth_alignment_failed_under_dmarc_policy: 'The sender failed normal email identity checks, so the platform could not trust it as genuine.',
              forced_reauth_required: 'Trust controls treated this message as risky enough to require stronger identity verification.',
              llm_policy_gate_denied: 'The content matched policy rules that require security review instead of auto-approval.',
              artifact_risk_block_band: 'The attachments contained enough high-risk signals to force a security review.',
              artifact_risk_review_band: 'The attachments did not look normal enough to auto-approve, so they were sent for review.',
              sandbox_detonation_malicious: 'A sandbox or malware detonation signal showed behavior consistent with a malicious file or link.',
              ioc_enrichment_malicious_hit: 'The message matched threat indicators already associated with known malicious activity.',
              progressive_access_restricted: 'Trust policy reduced access because the message did not meet the expected confidence threshold.',
              progressive_access_challenge: 'Trust policy requires an extra verification step before acting on this message.',
              vendor_master_mismatch: 'The sender does not match the expected supplier record.',
              approved_contact_mismatch: 'The sender or reply address is not one of the approved supplier contacts.',
              bank_fingerprint_baseline_mismatch: 'The requested bank details do not match the trusted supplier baseline.',
              bank_fingerprint_extracted_mismatch: 'Bank details extracted from the attachment differ from the trusted supplier baseline.',
              vendor_homoglyph_impersonation: 'The message uses lookalike characters to imitate a trusted brand or supplier.',
              pdf_producer_vulnerable: 'A PDF attachment was created with a tool associated with known security issues.'
            };
            return map[reason] || String(reason || '').replaceAll('_', ' ');
          }
          function severityToBusinessRisk(j, thr){
            const dreadAvg = parseFloat((((thr||{}).dread||{}).avg ?? (thr||{}).dread_avg ?? 0) || 0);
            const cvss = parseFloat((((thr||{}).cvss||{}).score ?? 0) || 0);
            const band = String(j.risk_band || '').toLowerCase();
            const stage = String((thr||{}).pasta_stage || (thr||{}).kill_chain_stage || '').trim();
            if(band === 'high' || dreadAvg >= 7 || cvss >= 8){
              return `High business risk. This email could lead to payment fraud, supplier impersonation, or account misuse if staff act on it. ${stage ? `Threat modeling places it at ${stage}.` : ''}`.trim();
            }
            if(band === 'medium' || dreadAvg >= 4.5 || cvss >= 5){
              return `Moderate business risk. The message shows enough suspicious behavior that acting on it could create financial loss or trust issues without verification. ${stage ? `Current threat stage: ${stage}.` : ''}`.trim();
            }
            return `Lower business risk. The message still needs review, but current evidence suggests limited business impact if normal controls stay in place. ${stage ? `Current threat stage: ${stage}.` : ''}`.trim();
          }
          function findingToPlainEnglish(f){
            if(!f || typeof f !== 'object') return '';
            const biz = String(f.business_meaning || '').trim();
            if(biz) return biz;
            const summary = String(f.summary || '').trim();
            if(summary) return summary;
            const kind = String(f.finding_type || 'finding').replaceAll('_', ' ');
            const ev = Array.isArray(f.evidence) ? f.evidence.filter(Boolean) : [];
            return ev.length ? `${kind}: ${ev.slice(0,2).join(' | ')}` : kind;
          }
          function findingContextLine(f){
            if(!f || typeof f !== 'object') return '';
            const t = f.threat_context || {};
            const dread = t.dread || {};
            const comp = Array.isArray(f.compliance_mapping) ? f.compliance_mapping : [];
            const fw = comp.slice(0,2).map(x => `${x.framework}${Array.isArray(x.controls) && x.controls.length ? ' ' + x.controls[0] : ''}`).join(', ');
            const parts = [
              String(f.confidence_band || 'medium') + ' confidence',
              String(f.source_type || 'policy'),
              String(t.pasta_stage || ''),
              dread.damage!=null ? `Damage ${dread.damage}` : '',
              dread.reproducibility!=null ? `Repro ${dread.reproducibility}` : '',
              fw ? `Audit: ${fw}` : ''
            ].filter(Boolean);
            return parts.join(' · ');
          }
          function provenanceChipLabel(src){
            const s = String(src || '').toLowerCase().trim();
            if(s === 'ocr') return 'OCR';
            if(s === 'static') return 'static';
            if(s === 'baseline') return 'baseline';
            if(s === 'intel') return 'intel';
            if(s === 'policy') return 'policy';
            if(s === 'behavioral') return 'behavioral';
            return s || 'policy';
          }
          function provenanceChipHtml(src){
            return `<span class="pill">${escHtml(provenanceChipLabel(src))}</span>`;
          }
          function findingProvenanceChips(f){
            if(!f || typeof f !== 'object') return '';
            const chips = [];
            if(f.source_type) chips.push(provenanceChipHtml(f.source_type));
            if(f.evidence_kind) chips.push(`<span class="pill">${escHtml(String(f.evidence_kind))}</span>`);
            if(f.confidence_band) chips.push(`<span class="pill">${escHtml(String(f.confidence_band))} confidence</span>`);
            return chips.join(' ');
          }
          function findingDrilldownHtml(f){
            if(!f || typeof f !== 'object') return '';
            const d = f.drilldown || {};
            if(!d || typeof d !== 'object' || !Object.keys(d).length) return '';
            const evidence = Array.isArray(f.evidence) ? f.evidence.filter(Boolean) : [];
            const mitre = Array.isArray(f.mitre_attack) && f.mitre_attack.length ? f.mitre_attack : (Array.isArray(((f.threat_context||{}).mitre_attack)) ? (f.threat_context||{}).mitre_attack : []);
            const comp = Array.isArray(f.compliance_mapping) ? f.compliance_mapping : [];
            const compRows = comp.map(x => `${x.framework}${Array.isArray(x.controls) && x.controls.length ? `: ${x.controls.join(', ')}` : ''}`);
            const pasta = String(f.pasta_stage || ((f.threat_context||{}).pasta_stage || '')).trim();
            const dread = (f.threat_context || {}).dread || {};
            const blocks = [
              d.business_risk ? `<div><strong>Business risk:</strong> ${escHtml(d.business_risk)}</div>` : '',
              d.affected_scope ? `<div><strong>Affected scope:</strong> ${escHtml(d.affected_scope)}</div>` : '',
              evidence.length ? `<div><strong>Evidence:</strong>${listHtml(evidence)}</div>` : '',
              Array.isArray(d.forensic_checks) && d.forensic_checks.length ? `<div><strong>Forensics:</strong>${listHtml(d.forensic_checks)}</div>` : '',
              Array.isArray(d.hunt_queries) && d.hunt_queries.length ? `<div><strong>Threat hunting:</strong>${listHtml(d.hunt_queries)}</div>` : '',
              Array.isArray(d.crisis_actions) && d.crisis_actions.length ? `<div><strong>Crisis / comms:</strong>${listHtml(d.crisis_actions)}</div>` : '',
              (pasta || mitre.length || compRows.length) ? `<div><strong>Frameworks:</strong>${listHtml([
                pasta ? `PASTA: ${pasta}` : null,
                mitre.length ? `MITRE: ${mitre.join(', ')}` : null,
                dread.damage!=null ? `DREAD: D=${dread.damage} R=${dread.reproducibility} E=${dread.exploitability} A=${dread.affected_users} Dv=${dread.discoverability}` : null,
                ...compRows
              ])}</div>` : ''
            ].filter(Boolean);
            return `<details class="finding-drilldown"><summary>Drill down</summary><div class="finding-drilldown-body">${blocks.join('')}</div></details>`;
          }
          function attachmentProvenanceChips(item){
            if(!item || typeof item !== 'object') return '';
            const chips = [];
            if(Array.isArray(item.evidence_excerpt_lines) && item.evidence_excerpt_lines.length) chips.push(provenanceChipHtml('ocr'));
            if(item.pdf_forensics && Object.keys(item.pdf_forensics).length) chips.push(provenanceChipHtml('static'));
            if(item.baseline_similarity && Object.keys(item.baseline_similarity).length) chips.push(provenanceChipHtml('baseline'));
            if(Array.isArray(item.embedded_urls) && item.embedded_urls.length) chips.push(provenanceChipHtml('intel'));
            if(item.supports_sender_claim) chips.push(provenanceChipHtml('policy'));
            return Array.from(new Set(chips)).join(' ');
          }
          function buildExecutiveSummary(j){
            const ev = j.evidence_snapshot || {};
            const card = ev.explainability_card || j.explainability_card || {};
            const thr = ev.threat_correlation || j.threat_correlation || {};
            const tc = ev.trust_case || j.trust_case || {};
            const pb = ev.playbook_run || j.playbook_run || j.playbook || {};
            const ranked = Array.isArray(ev.top_ranked_findings) ? ev.top_ranked_findings : (Array.isArray(card.top_ranked_findings) ? card.top_ranked_findings : []);
            const why = ranked.length
              ? ranked.map(f => `${findingToPlainEnglish(f)} (${findingContextLine(f)})`)
              : (Array.isArray(card.why_flagged) ? card.why_flagged.map(reasonToPlainEnglish) : (j.reasons||[]).map(reasonToPlainEnglish));
            const what = `The platform treated this email as ${(j.verdict_action || 'review').replaceAll('_', ' ')} because the sender identity, attachment content, or trust controls did not look consistent with a normal supplier message.`;
            const immediate = [];
            if(String(j.route || '').includes('security_review')) immediate.push('Do not reply, pay, or change supplier details from this email.');
            if(why.some(item => /supplier|bank|payment/i.test(item))) immediate.push('Verify the request using a phone number or supplier portal you already trust.');
            immediate.push('Quarantine the email and notify finance or security before any business action.');
            const next = [];
            if(ranked.length){
              for(const f of ranked){
                if(Array.isArray(f.next_steps)) next.push(...f.next_steps);
              }
            }
            if(Array.isArray(tc.actions)) next.push(...tc.actions.map(x => String(x).replaceAll('_',' ')));
            if(Array.isArray(pb.next_steps)) next.push(...pb.next_steps);
            if(!next.length) next.push('Review the attachments, confirm supplier identity, and record the outcome in the incident or ticket.');
            return {
              what,
              why,
              impact: severityToBusinessRisk(j, thr),
              immediate: Array.from(new Set(immediate)),
              next: Array.from(new Set(next)).slice(0, 6),
            };
          }
          function renderExecutiveSummary(j){
            const card = document.getElementById('exec_card');
            const summary = buildExecutiveSummary(j);
            card.style.display = 'block';
            document.getElementById('exec_what_happened').textContent = summary.what;
            document.getElementById('exec_why_flagged').innerHTML = listHtml(summary.why);
            document.getElementById('exec_business_risk').textContent = summary.impact;
            document.getElementById('exec_immediate_actions').innerHTML = listHtml(summary.immediate);
            document.getElementById('exec_next_steps').innerHTML = listHtml(summary.next);
          }
          function renderEvidenceSummary(j){
            const ev = j.evidence_snapshot || {};
            const thr = ev.threat_correlation || j.threat_correlation || {};
            const tc = ev.trust_case || j.trust_case || {};
            const artIntel = ev.artifact_intel || {};
            const atts = Array.isArray(ev.attachment_forensics) ? ev.attachment_forensics : [];
            const auth = ev.auth_verdicts || {};
            const ranked = Array.isArray(ev.top_ranked_findings) ? ev.top_ranked_findings : [];
            const gate = ev.pre_agent_gate || {};
            const agentRuns = Array.isArray(ev.agent_runs) ? ev.agent_runs : [];
            const sections = [];
            sections.push(`<div class="evidence-block"><div class="section-label">Top Ranked Evidence</div>${listHtml(
              ranked.length ? ranked.map(f => `${findingToPlainEnglish(f)} ${findingProvenanceChips(f)} [${escHtml(findingContextLine(f))}]${Array.isArray(f.next_steps) && f.next_steps.length ? ` Next: ${escHtml(f.next_steps[0])}` : ''}${findingDrilldownHtml(f)}`) : ['No ranked evidence available yet.']
            )}</div>`);
            sections.push(`<div class="evidence-block"><div class="section-label">Sender / Auth</div>${listHtml([
              auth.spf_result ? `SPF: ${auth.spf_result}` : null,
              auth.dkim_result ? `DKIM: ${auth.dkim_result}` : null,
              auth.dmarc_result ? `DMARC: ${auth.dmarc_result}` : null,
              auth.dmarc_fail ? 'DMARC alignment failed for this message.' : null
            ])}</div>`);
            sections.push(`<div class="evidence-block"><div class="section-label">Attachment Signals</div>${listHtml([
              atts.length ? `${atts.length} attachment(s) were parsed and inspected.` : 'No attachment evidence was returned.',
              (((artIntel||{}).signal_scores||{}).band) ? `Attachment risk band: ${artIntel.signal_scores.band}` : null,
              (((artIntel||{}).signal_scores||{}).total!=null) ? `Attachment risk score: ${artIntel.signal_scores.total}` : null
            ])}</div>`);
            sections.push(`<div class="evidence-block"><div class="section-label">Trust Baseline Deviation</div>${listHtml([
              tc.level ? `Trust level: ${tc.level}` : null,
              tc.progressive_access ? `Access policy: ${tc.progressive_access}` : null,
              ...(Array.isArray(tc.reasons) ? tc.reasons.map(reasonToPlainEnglish) : [])
            ])}</div>`);
            sections.push(`<div class="evidence-block"><div class="section-label">Threat Intel Correlation</div>${listHtml([
              Array.isArray(thr.mitre_attack) && thr.mitre_attack.length ? `Mapped to MITRE: ${thr.mitre_attack.join(', ')}` : null,
              Array.isArray(thr.kev) && thr.kev.length ? `Known exploited references: ${thr.kev.join(', ')}` : null,
              (((thr||{}).cvss||{}).score!=null) ? `CVSS: ${thr.cvss.score} ${thr.cvss.severity || ''}` : null,
              (((thr||{}).dread||{}).avg!=null) ? `DREAD average: ${thr.dread.avg}` : null
            ])}</div>`);
            sections.push(`<div class="evidence-block"><div class="section-label">Agent Safety & Audit</div>${listHtml([
              gate.artifact_text_untrusted ? 'Attachment and OCR text were treated as untrusted before model-facing analysis.' : null,
              gate.ocr_text_sanitized ? 'OCR and extracted text were sanitized before explanation and reasoning.' : null,
              gate.blocked_attachment_count!=null ? `Blocked attachments before model access: ${gate.blocked_attachment_count}` : null,
              gate.blocked_qr_url_count!=null ? `Blocked QR URLs before model access: ${gate.blocked_qr_url_count}` : null,
              Array.isArray(gate.blocked_tool_intents) && gate.blocked_tool_intents.length ? `Blocked tool intents: ${gate.blocked_tool_intents.join(', ')}` : null,
              agentRuns.length ? `Scoped agents executed: ${agentRuns.map(r => r.agent_name).join(', ')}` : 'No agent audit rows were returned.'
            ])}</div>`);
            const el = document.getElementById('evidence_sections');
            document.getElementById('evidence_card').style.display = 'block';
            el.innerHTML = sections.join('');
          }
          function renderActionsSummary(j){
            const ev = j.evidence_snapshot || {};
            const tc = ev.trust_case || j.trust_case || {};
            const pb = ev.playbook_run || j.playbook_run || j.playbook || {};
            const ap = ev.action_policy || j.action_policy || {};
            const hg = ev.human_gate || j.human_gate || ap.human_gate || {};
            const immediate = [
              'Hold payment changes and do not trust this email on sender reputation alone.',
              'Quarantine the email and preserve the attachments for review.',
            ];
            const analyst = [];
            const owner = [];
            const recovery = [];
            if(Array.isArray(tc.actions)) analyst.push(...tc.actions.map(x => String(x).replaceAll('_', ' ')));
            if(Array.isArray(pb.actions_completed)) analyst.push(...pb.actions_completed.map(x => String(x).replaceAll('_', ' ')));
            owner.push('Verify the supplier using an existing trusted contact path.');
            owner.push('Check whether finance, procurement, or accounts payable acted on the request.');
            recovery.push('Push indicators and verdict to SIEM or XDR for correlation and case tracking.');
            recovery.push('If a user interacted with the message, review account access and session controls.');
            const gating = [
              ap.lane ? `Human gate lane: ${String(ap.lane_label || ap.lane).replaceAll('_',' ')}` : null,
              ap.lane_reason ? ap.lane_reason : null,
              hg.business_hold_message ? hg.business_hold_message : null,
              Array.isArray(ap.threshold_reasons) && ap.threshold_reasons.length ? `Threshold reasons: ${ap.threshold_reasons.join(' | ')}` : null,
              Array.isArray(ap.auto_allowed_actions) && ap.auto_allowed_actions.length ? `Auto-allowed: ${ap.auto_allowed_actions.join(', ')}` : null,
              Array.isArray(ap.human_approval_actions) && ap.human_approval_actions.length ? `Human approval required: ${ap.human_approval_actions.join(', ')}` : null,
              Array.isArray(ap.blocked_actions) && ap.blocked_actions.length ? `Blocked by policy: ${ap.blocked_actions.join(', ')}` : null
            ];
            const html = [
              `<div class="evidence-block"><div class="section-label">Human Gate Thresholds</div>${listHtml(gating)}</div>`,
              `<div class="evidence-block"><div class="section-label">Immediate</div>${listHtml(immediate)}</div>`,
              `<div class="evidence-block"><div class="section-label">Analyst</div>${listHtml(Array.from(new Set(analyst)).slice(0,8))}</div>`,
              `<div class="evidence-block"><div class="section-label">Business Owner</div>${listHtml(owner)}</div>`,
              `<div class="evidence-block"><div class="section-label">Recovery</div>${listHtml(recovery)}</div>`
            ];
            document.getElementById('actions_card').style.display = 'block';
            document.getElementById('actions_sections').innerHTML = html.join('');
          }
          function renderInfrastructureSummary(j){
            const ev = j.evidence_snapshot || {};
            const infra = ev.sender_infrastructure || {};
            const hf = ev.header_forensics || {};
            const geo = infra.originating_geo || {};
            const rel = infra.related_incidents || {};
            const items = [
              infra.sender_address ? `Sender: ${infra.sender_address}` : null,
              infra.reply_to ? `Reply-To: ${infra.reply_to}` : null,
              infra.reply_domain_mismatch ? 'Reply-To domain differs from the sender domain.' : null,
              infra.originating_ip ? `Originating IP: ${infra.originating_ip}` : null,
              geo.country ? `GeoIP country: ${geo.country}` : null,
              geo.asn ? `ASN: ${geo.asn}${geo.asn_org ? ` (${geo.asn_org})` : ''}` : null,
              infra.reputation && infra.reputation.risk_score!=null ? `Infrastructure risk score: ${infra.reputation.risk_score}` : null,
              Array.isArray(infra.reputation?.flags) && infra.reputation.flags.length ? `Reputation flags: ${infra.reputation.flags.join(', ')}` : null,
              hf.mailer_fingerprint ? `Mailer fingerprint: ${hf.mailer_fingerprint}` : null,
              hf.message_id_domain_mismatch ? 'Message-ID domain does not match the sender domain.' : null,
              hf.message_id_reuse ? 'Message-ID reuse was detected.' : null,
              rel.count ? `Related incidents found: ${rel.count}` : 'Related incidents found: 0',
            ];
            const relatedHtml = Array.isArray(rel.matches) && rel.matches.length
              ? `<div class="evidence-block"><div class="section-label">Related Incidents</div>${listHtml(rel.matches.map(m => `${m.incident_id} (${m.severity || 'unknown'}) via ${(m.match_on || []).join(', ')}`))}</div>`
              : '';
            document.getElementById('infra_card').style.display = 'block';
            document.getElementById('infra_sections').innerHTML = `<div class="evidence-block"><div class="section-label">Infrastructure</div>${listHtml(items)}</div>${relatedHtml}`;
          }
          async function replaySiemHandoff(){
            try{
              const j = currentSecurityResult || {};
              const siem = j.siem_handoff || {};
              const event = siem.event || {};
              if(!event || !Object.keys(event).length){
                document.getElementById('status').textContent = 'No handoff event available to replay.';
                return;
              }
              document.getElementById('status').textContent = 'Replaying SIEM/XDR handoff…';
              const r = await fetch('/api/v1/admin/email_security/connectors/replay-event', {
                method:'POST',
                headers:{ 'Content-Type':'application/json', 'x-api-key': getOwnerKey() },
                body: JSON.stringify({ event })
              });
              const out = await r.json().catch(()=>null);
              if(!r.ok || !out){
                document.getElementById('status').textContent = `Replay failed (${r.status})`;
                return;
              }
              j.siem_handoff = { event, status: (out.result || {}) };
              currentSecurityResult = j;
              renderIntegrationsSummary(j);
              document.getElementById('status').textContent = 'SIEM/XDR handoff replayed.';
            }catch(e){
              document.getElementById('status').textContent = 'SIEM/XDR replay error';
            }
          }
          async function refreshConnectorHealth(){
            try{
              let r = await fetch('/api/v1/admin/email_security/connectors/dashboard?hours=24&dlq_limit=5', { headers:{ 'x-api-key': getOwnerKey() } });
              const out = await r.json().catch(()=>null);
              if(r.ok && out){ currentConnectorHealth = out; if(currentSecurityResult) renderIntegrationsSummary(currentSecurityResult); }
            }catch(e){}
          }
          async function refreshFeedbackSummary(tenantId){
            try{
              const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
              let r = await fetch(`/api/v1/admin/email_security/feedback/summary${q}`, { headers:{ 'x-api-key': getOwnerKey() } });
              const out = await r.json().catch(()=>null);
              if(r.ok && out){ currentFeedbackSummary = out; if(currentSecurityResult) renderIntegrationsSummary(currentSecurityResult); }
            }catch(e){}
          }
          async function submitFeedbackOutcome(outcomeType, outcomeValue, reasonCode){
            try{
              const incidentId = String((document.getElementById('inc_id')?.textContent || '')).trim();
              if(!incidentId || incidentId === '-'){
                document.getElementById('status').textContent = 'No related incident is available to label yet.';
                return;
              }
              const tenantId = String((((currentSecurityResult || {}).siem_handoff || {}).event || {}).tenant_id || 'default');
              document.getElementById('status').textContent = 'Recording analyst outcome…';
              const payload = {
                incident_ids: [incidentId],
                outcome_type: outcomeType,
                outcome_value: outcomeValue,
                actor_id: 'email_lab',
                actor_role: 'owner',
                note: reasonCode,
                reason_code: reasonCode
              };
              const r = await fetch('/api/v1/admin/email_security/feedback/bulk_label', {
                method:'POST',
                headers:{ 'Content-Type':'application/json', 'x-api-key': getOwnerKey() },
                body: JSON.stringify(payload)
              });
              const out = await r.json().catch(()=>null);
              if(!r.ok || !out){
                document.getElementById('status').textContent = `Outcome recording failed (${r.status})`;
                return;
              }
              document.getElementById('status').textContent = `Outcome recorded: ${outcomeValue}`;
              await refreshFeedbackSummary(tenantId);
            }catch(e){
              document.getElementById('status').textContent = 'Outcome recording error';
            }
          }
          async function reviewSupplierGovernance(updateKey, decision){
            try{
              const gov = (((currentSecurityResult || {}).evidence_snapshot || {}).supplier_governance || {});
              const supplierKey = String(gov.supplier_key || '').trim();
              if(!supplierKey || !updateKey){
                document.getElementById('status').textContent = 'No supplier governance item is available to review.';
                return;
              }
              const tenantId = String((((currentSecurityResult || {}).siem_handoff || {}).event || {}).tenant_id || gov.tenant_id || 'default');
              document.getElementById('status').textContent = `${decision === 'approve' ? 'Approving' : 'Rejecting'} governance update…`;
              const r = await fetch('/api/v1/admin/email_security/supplier-governance/review', {
                method:'POST',
                headers:{ 'Content-Type':'application/json', 'x-api-key': getOwnerKey() },
                body: JSON.stringify({
                  tenant_id: tenantId,
                  supplier_key: supplierKey,
                  update_key: updateKey,
                  decision: decision,
                  actor_id: 'email_lab',
                  actor_role: 'owner'
                })
              });
              const out = await r.json().catch(()=>null);
              if(!r.ok || !out || !out.ok){
                document.getElementById('status').textContent = `Supplier governance review failed (${r.status})`;
                return;
              }
              if(currentSecurityResult && currentSecurityResult.evidence_snapshot){
                currentSecurityResult.evidence_snapshot.supplier_governance = out.profile || gov;
              }
              renderSupplierGovernance(currentSecurityResult || {});
              document.getElementById('status').textContent = `Supplier governance update ${decision}d`;
            }catch(e){
              document.getElementById('status').textContent = 'Supplier governance review error';
            }
          }
          function renderIntegrationsSummary(j){
            const siem = j.siem_handoff || {};
            const pb = (j.evidence_snapshot || {}).playbook_run || j.playbook_run || {};
            const st = siem.status || {};
            const hc = currentConnectorHealth || {};
            const fb = currentFeedbackSummary || {};
            const hcSummary = hc.summary || {};
            const byTarget = Array.isArray(hc.by_target) ? hc.by_target : [];
            const statusLines = [
              j.decision_trace_id ? `Decision trace: ${j.decision_trace_id}` : null,
              pb.playbook_id ? `Playbook: ${pb.playbook_id}` : null,
              j.verdict_action ? `Verdict action: ${String(j.verdict_action).replaceAll('_', ' ')}` : null,
              j.escalation ? `Escalation path: ${String(j.escalation).replaceAll('_', ' ')}` : null,
              Array.isArray(st.sent) && st.sent.length ? `Sent to: ${st.sent.join(', ')}` : null,
              Array.isArray(st.retrying) && st.retrying.length ? `Retrying: ${st.retrying.join(', ')}` : null,
              Array.isArray(st.failed) && st.failed.length ? `Failed: ${st.failed.join(', ')}` : null,
              Array.isArray(st.dlq) && st.dlq.length ? `DLQ: ${st.dlq.join(', ')}` : null,
              hcSummary.attempts!=null ? `Connector attempts (24h): ${hcSummary.attempts}` : null,
              hcSummary.success_rate!=null ? `Connector success rate: ${(parseFloat(hcSummary.success_rate||0)*100).toFixed(0)}%` : null,
              byTarget.length ? `Targets: ${byTarget.map(t => `${t.target} sent=${t.sent||0} dlq=${t.dlq||0}`).join(' | ')}` : null,
              fb.false_positive_rate!=null ? `False-positive rate: ${(parseFloat(fb.false_positive_rate||0)*100).toFixed(1)}%` : null,
            ];
            document.getElementById('integrations_card').style.display = 'block';
            document.getElementById('integrations_sections').innerHTML = `<div class="evidence-block"><div class="section-label">SIEM / XDR Handoff State</div>${listHtml(statusLines)}<div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap;"><button class="btn" type="button" onclick="replaySiemHandoff()">Push To SIEM / XDR</button><button class="btn" type="button" onclick="refreshConnectorHealth()">Refresh Connector Health</button></div></div><div class="evidence-block"><div class="section-label">Analyst Outcome Workflow</div>${listHtml(['Use these controls after review to improve precision and governance.', 'Mark Legit lowers false-positive risk. Mark Malicious reinforces true-positive coverage. Baseline Update requests human review before trust changes.'])}<div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap;"><button class="btn" type="button" onclick="submitFeedbackOutcome('analyst_review','false_positive','marked_legit')">Mark Legit</button><button class="btn" type="button" onclick="submitFeedbackOutcome('analyst_review','true_positive','confirmed_malicious')">Mark Malicious</button><button class="btn" type="button" onclick="submitFeedbackOutcome('business_exception','approved_exception','business_approved')">Approved Exception</button><button class="btn" type="button" onclick="submitFeedbackOutcome('baseline_review','approved_exception','baseline_update_requested')">Request Baseline Update</button></div></div>`;
            const tenantId = String(((siem.event || {}).tenant_id || 'default'));
            if(!currentConnectorHealth) refreshConnectorHealth();
            if(!currentFeedbackSummary) refreshFeedbackSummary(tenantId);
          }
          function renderSupplierGovernance(j){
            const ev = j.evidence_snapshot || {};
            const gov = ev.supplier_governance || {};
            if(!gov || !gov.supplier_key) return;
            const pending = Array.isArray(gov.pending_updates) ? gov.pending_updates : [];
            const pendingHtml = pending.length
              ? pending.map(item => `<div class="attachment-row"><div><strong>${escHtml(item)}</strong></div><div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap;"><button class="btn" type="button" onclick="reviewSupplierGovernance(${JSON.stringify(item)}, 'approve')">Approve</button><button class="btn" type="button" onclick="reviewSupplierGovernance(${JSON.stringify(item)}, 'reject')">Reject</button></div></div>`).join('')
              : `<div class="small">No supplier governance approvals are pending.</div>`;
            const sections = [
              `Supplier: ${gov.vendor_name || gov.supplier_key}`,
              `Governance state: ${String(gov.governance_state || 'stable').replaceAll('_',' ')}`,
              Array.isArray(gov.approved_domains) && gov.approved_domains.length ? `Approved domains: ${gov.approved_domains.join(', ')}` : null,
              Array.isArray(gov.observed_domains) && gov.observed_domains.length ? `Observed domains: ${gov.observed_domains.join(', ')}` : null,
              Array.isArray(gov.approved_bank_fingerprints) && gov.approved_bank_fingerprints.length ? `Approved bank fingerprints: ${gov.approved_bank_fingerprints.join(', ')}` : null,
              Array.isArray(gov.observed_bank_fingerprints) && gov.observed_bank_fingerprints.length ? `Observed bank fingerprints: ${gov.observed_bank_fingerprints.join(', ')}` : null,
              Array.isArray(gov.history) && gov.history.length ? `Recent decisions: ${gov.history.slice(-6).join(' | ')}` : null,
              pending.length ? `Pending review count: ${pending.length}` : 'No pending supplier governance updates.'
            ];
            document.getElementById('gov_card').style.display = 'block';
            document.getElementById('gov_sections').innerHTML = `<div class="evidence-block"><div class="section-label">Governance Snapshot</div>${listHtml(sections)}</div><div class="evidence-block"><div class="section-label">Pending Approvals</div>${pendingHtml}</div>`;
          }
          function renderVendorTrustGraph(j){
            const ev = j.evidence_snapshot || {};
            const graph = ev.vendor_trust_graph || {};
            if(!graph || !graph.supplier_key) return;
            const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
            const edges = Array.isArray(graph.edges) ? graph.edges : [];
            const incidentGraph = ev.incident_graph || {};
            const timeline = Array.isArray(graph.timeline) ? graph.timeline : ((Array.isArray(incidentGraph.timeline)) ? incidentGraph.timeline : []);
            const rel = (incidentGraph.relationships && typeof incidentGraph.relationships === 'object') ? incidentGraph.relationships : {};
            const sections = [
              `Supplier key: ${graph.supplier_key}`,
              `Nodes: ${graph.node_count || nodes.length || 0}`,
              `Edges: ${graph.edge_count || edges.length || 0}`,
              `Related incidents: ${graph.incident_count || (incidentGraph.incident_count || 0)}`,
              Array.isArray(graph.risk_notes) && graph.risk_notes.length ? `Risk notes: ${graph.risk_notes.join(', ')}` : null,
              (ev.supplier_governance && Array.isArray(ev.supplier_governance.history) && ev.supplier_governance.history.length) ? `Governance history: ${ev.supplier_governance.history.slice(-6).join(' | ')}` : null,
              nodes.length ? `Entities: ${nodes.slice(0,8).map(n => `${n.label} (${n.type})`).join(' | ')}` : null,
              edges.length ? `Relationships: ${edges.slice(0,8).map(e => `${e.source.split(':').slice(-1)[0]} -> ${e.target.split(':').slice(-1)[0]} (${e.relation})`).join(' | ')}` : null
            ];
            const relationshipSections = [
              Array.isArray(rel.domains) && rel.domains.length ? `Domains: ${rel.domains.join(', ')}` : null,
              Array.isArray(rel.bank_fingerprints) && rel.bank_fingerprints.length ? `Bank fingerprints: ${rel.bank_fingerprints.join(', ')}` : null,
              Array.isArray(rel.template_hashes) && rel.template_hashes.length ? `Template hashes: ${rel.template_hashes.join(', ')}` : null
            ];
            const timelineHtml = timeline.length
              ? `<div class="evidence-block"><div class="section-label">Incident Timeline</div>${listHtml(timeline.slice(0,8).map(item => `${item.created_at || '-'} · ${item.incident_id || '-'} · ${item.severity || 'info'}${Array.isArray(item.reasons) && item.reasons.length ? ` · ${item.reasons.join(', ')}` : ''}`))}</div>`
              : '';
            const relationshipHtml = relationshipSections.some(Boolean)
              ? `<div class="evidence-block"><div class="section-label">Relationship Buckets</div>${listHtml(relationshipSections)}</div>`
              : '';
            document.getElementById('graph_card').style.display = 'block';
            document.getElementById('graph_sections').innerHTML = `<div class="evidence-block"><div class="section-label">Trust Graph Snapshot</div>${listHtml(sections)}</div>${relationshipHtml}${timelineHtml}`;
          }
          function renderVerdictTones(j){
            const ev = j.evidence_snapshot || {};
            const explain = ev.explainability_card || j.explainability_card || {};
            const attachmentForensics = Array.isArray(ev.attachment_forensics) ? ev.attachment_forensics : [];
            const ranked = Array.isArray(ev.top_ranked_findings) ? ev.top_ranked_findings : [];
            const rawEvidence = [];
            for(const item of attachmentForensics.slice(0,2)){
              if(Array.isArray(item.evidence_excerpt_lines)){
                rawEvidence.push(...item.evidence_excerpt_lines.map(line => `${item.file_name}: ${line}`));
              }
            }
            if(ranked.length){
              rawEvidence.unshift(...ranked.map(f => `${String(f.agent_origin || 'agent')}: ${findingToPlainEnglish(f)} [${findingContextLine(f)}]`));
            }
            if(!rawEvidence.length && Array.isArray(j.reasons)){
              rawEvidence.push(...j.reasons.slice(0,4));
            }
            const businessSafe = buildExecutiveSummary(j).what + ' ' + buildExecutiveSummary(j).impact;
            const analyst = explain.analyst_summary || `Flagged due to ${(j.reasons || []).slice(0,4).join(', ')}.`;
            const html = [
              `<div class="evidence-block"><div class="section-label">Business-Safe Summary</div><div>${escHtml(businessSafe)}</div></div>`,
              `<div class="evidence-block"><div class="section-label">Analyst Summary</div><div>${escHtml(analyst)}</div></div>`,
              `<div class="evidence-block"><div class="section-label">Raw Technical Evidence</div>${listHtml(rawEvidence)}</div>`
            ];
            document.getElementById('tones_card').style.display = 'block';
            document.getElementById('tones_sections').innerHTML = html.join('');
          }
          function renderAttachmentForensics(ev){
            const artIntel = ev.artifact_intel || {};
            const attGate = ev.attachment_ingest_gate || {};
            const items = Array.isArray(ev.attachment_forensics) ? ev.attachment_forensics : [];
            if(!(Object.keys(artIntel).length || Object.keys(attGate).length || items.length)) return;
            const ac = document.getElementById('attach_card'); ac.style.display='block';
            const rows = [];
            if(attGate.attachment_count!=null){
              rows.push(`<div class="evidence-block"><div class="section-label">Intake Gate</div>${listHtml([
                `Attachments received: ${attGate.attachment_count}`,
                `Accepted: ${attGate.accepted_count || 0}`,
                `Blocked: ${attGate.blocked_count || 0}`,
                Array.isArray(attGate.block_reasons) && attGate.block_reasons.length ? `Block reasons: ${attGate.block_reasons.join(', ')}` : null
              ])}</div>`);
            }
            for(const item of items){
              const pdf = item.pdf_forensics || {};
              const sim = item.baseline_similarity || {};
              rows.push(
                `<div class="attachment-row">
                  <div class="row" style="justify-content:space-between; align-items:flex-start; gap:8px; flex-wrap:wrap;">
                    <div><strong>${escHtml(item.file_name || 'attachment')}</strong><div class="small">${escHtml(item.file_type || 'unknown')}</div><div style="margin-top:6px;">${attachmentProvenanceChips(item)}</div></div>
                    <div class="small mono">${escHtml((item.sha256 || '').slice(0,20))}${item.sha256 ? '…' : ''}</div>
                  </div>
                  <div class="small" style="margin-top:6px;">${escHtml(item.text_summary || 'No text extracted from this attachment.')}</div>
                  <div class="small" style="margin-top:6px;"><strong>Supports sender claim:</strong> ${escHtml(String(item.supports_sender_claim || 'neutral').replaceAll('_',' '))}</div>
                  <div class="small" style="margin-top:6px;">${listHtml([
                    item.bank_fields_present ? 'Attachment contains bank or remittance fields.' : null,
                    item.embedded_urls && item.embedded_urls.length ? `Embedded URLs: ${item.embedded_urls.join(', ')}` : null,
                    item.suspicious_instructions && item.suspicious_instructions.length ? item.suspicious_instructions.join(' ') : null,
                    item.brand_supplier_mismatch_signals && item.brand_supplier_mismatch_signals.length ? item.brand_supplier_mismatch_signals.join(' ') : null,
                    item.evidence_excerpt_lines && item.evidence_excerpt_lines.length ? `Evidence excerpts: ${item.evidence_excerpt_lines.join(' | ')}` : null,
                    pdf.producer ? `PDF producer: ${pdf.producer}` : null,
                    (pdf.embedded_files_count||0) > 0 ? `Embedded files: ${pdf.embedded_files_count}` : null,
                    (pdf.object_stream_count||0) > 0 ? `Object streams: ${pdf.object_stream_count}` : null,
                    sim.template_aligned === false ? 'Template similarity check failed against the baseline.' : null,
                    sim.logo_layout_aligned === false ? 'Logo or layout similarity check failed against the baseline.' : null
                  ])}</div>
                </div>`
              );
            }
            document.getElementById('attach_forensics').innerHTML = rows.join('');
          }
          function renderPdfBaselineDiff(ev){
            const diff = ev.attachment_baseline_diffs || {};
            const comps = Array.isArray(diff.comparisons) ? diff.comparisons : [];
            if(!comps.length) return;
            document.getElementById('pdf_diff_card').style.display = 'block';
            document.getElementById('pdf_diff_sections').innerHTML = comps.map(item => {
              const bbox = Array.isArray(item.drift_bbox) && item.drift_bbox.length ? item.drift_bbox.join(', ') : 'none';
              const visualGrid = item.baseline_preview_b64 && item.candidate_preview_b64 && (item.overlay_preview_b64 || item.heatmap_preview_b64)
                ? `<div class="thumb-grid">
                    <div><div class="section-label">Baseline</div><img alt="pdf baseline preview" src="data:image/png;base64,${item.baseline_preview_b64 || ''}" /></div>
                    <div><div class="section-label">Candidate</div><img alt="pdf candidate preview" src="data:image/png;base64,${item.candidate_preview_b64 || ''}" /></div>
                    <div><div class="section-label">Overlay</div><img alt="pdf overlay preview" src="data:image/png;base64,${item.overlay_preview_b64 || item.heatmap_preview_b64 || ''}" /></div>
                  </div>
                  ${item.heatmap_preview_b64 ? `<div class="thumb-grid" style="grid-template-columns:1fr;"><div><div class="section-label">Heatmap</div><img alt="pdf heatmap preview" src="data:image/png;base64,${item.heatmap_preview_b64}" /></div></div>` : ''}`
                : '';
              return `<div class="attachment-row">
                <div><strong>Baseline:</strong> ${escHtml(item.baseline_file || '-')}</div>
                <div><strong>Compare:</strong> ${escHtml(item.candidate_file || '-')}</div>
                <div class="small" style="margin-top:6px;"><strong>Text similarity:</strong> ${escHtml(String(item.text_similarity ?? '-'))} Â· <strong>Visual drift:</strong> ${escHtml(String(item.mean_pixel_diff ?? '-'))} Â· <strong>Drift box:</strong> ${escHtml(bbox)}</div>
                <div class="small" style="margin-top:6px;">${listHtml([
                  Array.isArray(item.differences) && item.differences.length ? `Differences: ${item.differences.join(' ')}` : 'No major structural differences were detected.',
                  item.baseline_urls && item.baseline_urls.length ? `Baseline URLs: ${item.baseline_urls.join(', ')}` : null,
                  item.candidate_urls && item.candidate_urls.length ? `Candidate URLs: ${item.candidate_urls.join(', ')}` : null,
                  item.baseline_bank_fields && Object.keys(item.baseline_bank_fields).length ? `Baseline bank fields: ${JSON.stringify(item.baseline_bank_fields)}` : null,
                  item.candidate_bank_fields && Object.keys(item.candidate_bank_fields).length ? `Candidate bank fields: ${JSON.stringify(item.candidate_bank_fields)}` : null
                ])}</div>${visualGrid}
              </div>`;
            }).join('');
          }
          function renderVisualBaselineDiff(ev){
            const diff = ev.attachment_visual_diffs || {};
            const comps = Array.isArray(diff.comparisons) ? diff.comparisons : [];
            if(!comps.length) return;
            document.getElementById('visual_diff_card').style.display = 'block';
            document.getElementById('visual_diff_sections').innerHTML = comps.map(item => {
              const bbox = Array.isArray(item.drift_bbox) && item.drift_bbox.length ? item.drift_bbox.join(', ') : 'none';
              return `<div class="attachment-row">
                <div><strong>Baseline:</strong> ${escHtml(item.baseline_file || '-')}</div>
                <div><strong>Compare:</strong> ${escHtml(item.candidate_file || '-')}</div>
                <div class="small" style="margin-top:6px;">Mean pixel drift: ${escHtml(String(item.mean_pixel_diff ?? '-'))} · Drift box: ${escHtml(bbox)}</div>
                <div class="thumb-grid">
                  <div><div class="section-label">Baseline</div><img alt="baseline preview" src="data:image/png;base64,${item.baseline_preview_b64 || ''}" /></div>
                  <div><div class="section-label">Candidate</div><img alt="candidate preview" src="data:image/png;base64,${item.candidate_preview_b64 || ''}" /></div>
                  <div><div class="section-label">Heatmap</div><img alt="diff heatmap" src="data:image/png;base64,${item.diff_preview_b64 || ''}" /></div>
                </div>
              </div>`;
            }).join('');
          }
          function renderNarrativeTraceEvent(it){
            const payload = it?.payload || {};
            const eventType = String(it?.event_type || 'event');
            const sentenceMap = {
              security_scan: 'The security scanner collected signals from the email body and attachments.',
              sender_trust_assessed: 'Sender trust and supplier relationship confidence were recalculated.',
              ioc_enrichment_fusion: 'Threat indicators were checked against enrichment and intelligence sources.',
              policy_gate: 'The policy gate decided whether the message could be allowed, reviewed, or escalated.',
              playbook_selected: 'A response playbook was selected for this incident.',
              playbook_run_completed: 'The playbook finished and reported its next steps.'
            };
            const narrative = sentenceMap[eventType] || `The platform recorded ${eventType.replaceAll('_', ' ')}.`;
            return `<div class="ev"><div class="meta">${escHtml(eventType)} · ${escHtml(it?.created_at || '')}</div><div>${escHtml(narrative)}</div></div>`;
          }
          function setTraceMode(mode){
            const explain = mode !== 'raw';
            document.getElementById('trace_human').style.display = explain ? 'block' : 'none';
            document.getElementById('trace').style.display = explain ? 'none' : 'block';
            document.getElementById('trace_btn_explain').classList.toggle('active', explain);
            document.getElementById('trace_btn_raw').classList.toggle('active', !explain);
          }
          function toggleDetachRightRail(){
            document.getElementById('right_rail').classList.toggle('detached');
          }
          function openRightRailTab(){
            try{
              const win = window.open('', '_blank');
              if(!win) return;
              const content = document.getElementById('right_rail').innerHTML;
              win.document.write(`<!doctype html><html><head><title>Email Lab Right Rail</title><style>body{font-family:Segoe UI,Arial,sans-serif;background:#f3f6fb;color:#0f172a;padding:18px}.card{border:1px solid #dbe3ee;border-radius:12px;background:#fff;margin-bottom:12px}.card h4{margin:0;padding:12px 14px;border-bottom:1px solid #dbe3ee}.body{padding:12px 14px}.pill{display:inline-block;padding:6px 10px;border-radius:999px;border:1px solid #dbe3ee;background:#f8fafc;margin:2px}.small{font-size:12px;color:#475569}.mono{font-family:Consolas,monospace}.finding-list{padding-left:18px}.section-label{font-size:11px;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:4px}.evidence-block,.attachment-row{padding:10px;border:1px solid #dbe3ee;border-radius:10px;background:#fff;margin-top:8px}.row{display:flex;gap:8px;flex-wrap:wrap}.rail-toolbar{display:none}</style></head><body>${content}</body></html>`);
              win.document.close();
            }catch(e){}
          }
          function renderSecurityPanels(j){
            try{
              currentSecurityResult = j;
              const ev = j.evidence_snapshot || {};
              renderExecutiveSummary(j);
              renderEvidenceSummary(j);
              renderActionsSummary(j);
              renderInfrastructureSummary(j);
              renderIntegrationsSummary(j);
              renderSupplierGovernance(j);
              renderVendorTrustGraph(j);
              renderVerdictTones(j);
              /* ── Security Overview ── */
              const ov = document.getElementById('sec_overview'); ov.style.display='block';
              const badges = document.getElementById('sec_badges');
              const sevColor = {'error':'#ef4444','warning':'#f97316','info':'#3b82f6','critical':'#dc2626'}[j.severity] || '#64748b';
              badges.innerHTML = `<span class='pill' style='background:${sevColor};color:#fff;'>${(j.severity||'info').toUpperCase()}</span>`
                + `<span class='pill'>${j.verdict_action||'unknown'}</span>`
                + `<span class='pill'>Route: ${j.route||'-'}</span>`
                + (j.risk_band ? `<span class='pill'>Risk: ${j.risk_band}</span>` : '')
                + (j.escalation ? `<span class='pill'>Escalation: ${j.escalation}</span>` : '');
              const vBar = document.getElementById('sec_verdict_bar');
              vBar.style.background = sevColor + '22'; vBar.style.color = sevColor; vBar.style.borderLeft = `4px solid ${sevColor}`;
              vBar.textContent = `${j.verdict_action||'unknown'} / ${j.severity||'info'}`;
              document.getElementById('sec_reasons_list').innerHTML = (j.reasons||[]).map(r=>`<div style='margin:2px 0;'>• ${r}</div>`).join('');

              /* ── BEC Kill Chain ── */
              const bec = ev.bec_kill_chain || j.bec_kill_chain || {};
              if(bec.stage || j.bec_kill_chain_stage){
                const bc = document.getElementById('bec_card'); bc.style.display='block';
                document.getElementById('bec_stage').textContent = `Stage: ${bec.stage || j.bec_kill_chain_stage || '-'}`;
                const flow = bec.attack_flow || bec.flow || [];
                document.getElementById('bec_flow').innerHTML = Array.isArray(flow) ? flow.map(s=>`<span class='pill'>${s}</span>`).join(' → ') : '';
                const bbadges = document.getElementById('bec_badges');
                bbadges.innerHTML = (bec.confidence!=null ? `<span class='pill'>Conf: ${(bec.confidence*100).toFixed(0)}%</span>` : '')
                  + (bec.signal_count!=null ? `<span class='pill'>Signals: ${bec.signal_count}</span>` : '')
                  + (bec.techniques ? `<span class='pill'>Techniques: ${JSON.stringify(bec.techniques).slice(0,80)}</span>` : '');
              }

              /* ── Trust Case ── */
              const tc = ev.trust_case || j.trust_case || {};
              if(tc.score!=null || tc.level){
                const td = document.getElementById('trust_card'); td.style.display='block';
                const scoreEl = document.getElementById('trust_score');
                const sc = tc.score!=null ? parseFloat(tc.score) : null;
                scoreEl.textContent = sc!=null ? sc.toFixed(2) : '-';
                scoreEl.style.color = sc!=null && sc<0.3 ? '#ef4444' : sc<0.6 ? '#f97316' : '#22c55e';
                document.getElementById('trust_level').textContent = tc.level || '-';
                document.getElementById('trust_access').textContent = tc.progressive_access || '-';
                const acts = tc.actions || [];
                document.getElementById('trust_actions').innerHTML = acts.map(a=>`<span class='pill'>${a}</span>`).join(' ');
                const reasons = tc.reasons || [];
                document.getElementById('trust_reasons').textContent = reasons.join(', ');
              }

              /* ── Threat Correlation (MITRE / DREAD / CVSS / KEV / PASTA) ── */
              const thr = ev.threat_correlation || j.threat_correlation || {};
              if(thr.mitre_attack || thr.dread || thr.cvss || thr.kev || thr.kill_chain_stage){
                const tc2 = document.getElementById('threat_card'); tc2.style.display='block';
                const mitre = Array.isArray(thr.mitre_attack) ? thr.mitre_attack : [];
                const kev = Array.isArray(thr.kev) ? thr.kev : [];
                document.getElementById('threat_badges').innerHTML = mitre.map(m=>`<span class='pill' style='background:#4338ca22;color:#4338ca;'>MITRE ${m}</span>`).join('')
                  + kev.map(k=>`<span class='pill' style='background:#dc262622;color:#dc2626;'>KEV ${k}</span>`).join('');
                const dread = thr.dread || {};
                document.getElementById('dread_avg').textContent = dread.avg!=null ? dread.avg : (thr.dread_avg!=null ? thr.dread_avg : '-');
                const cvss = thr.cvss || {};
                document.getElementById('cvss_score').textContent = cvss.score!=null ? `${cvss.score} (${cvss.severity||''})` : '-';
                document.getElementById('kc_stage').textContent = thr.kill_chain_stage || '-';
                document.getElementById('pasta_stage').textContent = thr.pasta_stage || (ev.pasta_stage) || '-';
                document.getElementById('kev_list').textContent = kev.length ? `KEV: ${kev.join(', ')}` : '';
              }

              /* ── Sandbox / Detonation / IOC ── */
              const det = ev.detonation || j.detonation || {};
              const iocQ = ev.ioc_quality || {};
              const iocC = ev.ioc_counts || {};
              const sandIoc = ev.sandbox_ioc_stage || '';
              if(det.provider || det.malicious!=null || iocQ.resolution || iocC.url!=null || sandIoc){
                const sc2 = document.getElementById('sandbox_card'); sc2.style.display='block';
                document.getElementById('det_result').textContent = det.malicious!=null ? (det.malicious ? 'MALICIOUS' : 'clean') : (sandIoc || '-');
                document.getElementById('det_result').style.color = det.malicious ? '#ef4444' : '#22c55e';
                document.getElementById('ioc_hits').textContent = (iocC.url||0) + (iocC.domain||0) + (iocC.hash||0);
                document.getElementById('ioc_resolution').textContent = iocQ.resolution || '-';
                const enrichSecs = ((j.latency || {}).enrichment_seconds ?? (ev.latency || {}).enrichment_seconds);
                document.getElementById('enrich_latency').textContent = enrichSecs!=null ? `${(parseFloat(enrichSecs)*1000).toFixed(0)}ms` : '-';
                const findings = det.findings || det.ioc_list || [];
                document.getElementById('sandbox_findings').innerHTML = Array.isArray(findings) ? findings.slice(0,6).map(f=>`<div>• ${typeof f==='string'?f:JSON.stringify(f)}</div>`).join('') : '';
              }

              /* ── Attachment Forensics ── */
              renderAttachmentForensics(ev);
              renderPdfBaselineDiff(ev);
              renderVisualBaselineDiff(ev);

              /* ── QR / OCR ── */
              const qr = ev.ocr_qr_sanitization || {};
              if(qr.qr_count!=null || qr.ocr_tokens || qr.urls_found){
                const qc = document.getElementById('qr_card'); qc.style.display='block';
                const parts = [];
                if(qr.qr_count!=null) parts.push(`QR codes: ${qr.qr_count}`);
                if(qr.malicious_qr!=null) parts.push(`Malicious: ${qr.malicious_qr}`);
                if(qr.benign_qr!=null) parts.push(`Benign: ${qr.benign_qr}`);
                if(qr.urls_found) parts.push(`URLs: ${JSON.stringify(qr.urls_found).slice(0,200)}`);
                if(qr.ocr_tokens) parts.push(`OCR tokens: ${qr.ocr_tokens}`);
                document.getElementById('qr_findings').innerHTML = parts.map(p=>`<div>• ${p}</div>`).join('');
              }

              /* ── Playbook Run ── */
              const pb = ev.playbook_run || j.playbook_run || ev.playbook || j.playbook || null;
              if(pb && (pb.playbook_id || pb.title || pb.actions_completed)){
                mergePlaybookRun(pb);
                const pbName = pb.playbook_id || pb.title || pb.id || 'unknown';
                document.getElementById('pb_name').textContent = pbName;
                const pbSt = pb.status || pb.outcome || 'completed';
                document.getElementById('pb_status').textContent = pbSt;
                const acts = Array.isArray(pb.actions_completed) ? pb.actions_completed : (Array.isArray(pb.actions) ? pb.actions : []);
                document.getElementById('pb_actions').innerHTML = acts.slice(0,8).map(a=>`<span class='pill'>${typeof a==='string'?a:JSON.stringify(a)}</span>`).join('');
                const nxt = Array.isArray(pb.next_steps) ? pb.next_steps.join(' · ') : (pb.next_step || '');
                if(nxt){ document.getElementById('pb_next_steps').textContent = 'Next: ' + nxt; }
              }
            }catch(e){ pushTraceNotice('render_panels_error', { error: String(e) }); }
          }

          async function analyze(){ resetPlaybookRunCard(); document.getElementById('status').textContent='Analyzing…'; const to = document.getElementById('to').value.trim(); const subj = document.getElementById('subject').value.trim(); const body = document.getElementById('body').value.trim(); let atts = []; try { atts = await collectAllAttachments(); } catch(attErr){ const msg = 'Attachment encoding failed: ' + String(attErr && attErr.message ? attErr.message : attErr); document.getElementById('status').textContent = msg; pushTraceNotice('attachment_encoding_failed', { error: msg }); return; } const payload = { message_id: 'lab-'+Math.random().toString(36).slice(2), from_addr: to, reply_to: to, subject: subj, body: body, attachments: atts, external_sender: true, dmarc_fail: false, spf_result: 'neutral', dkim_result: 'neutral', dmarc_result: 'quarantine', dmarc_policy: 'reject', vendor_domain: 'ingramfake.com.au' };
            try {
              let r = await fetch('/api/v1/email_security/evaluate', { method:'POST', headers: { 'Content-Type':'application/json', 'x-api-key': getApiKey() }, body: JSON.stringify(payload) });
              if (r.status === 401 || r.status === 403) {
                r = await fetch('/api/v1/email_security/evaluate', { method:'POST', headers: { 'Content-Type':'application/json', 'x-api-key': getOwnerKey() }, body: JSON.stringify(payload) });
              }
              const j = await r.json().catch(()=>null); if(!r.ok || !j){ const err=(j && (j.detail||j.error) ? (j.detail||j.error) : 'no details'); document.getElementById('status').textContent='Analyze failed ('+r.status+'): '+err; pushTraceNotice('analyze_failed', { status: r.status, error: err, endpoint: '/api/v1/email_security/evaluate' }); return; }
              const sevCls = {'error':'sev-error','warning':'sev-warning'}.hasOwnProperty(j.severity||'') ? 'sev-'+j.severity : 'sev-info';
              document.getElementById('verdict').textContent = (j.verdict_action || 'unknown').toUpperCase() + ' · ' + (j.severity || 'info').toUpperCase();
              document.getElementById('verdict').className = 'pill ' + sevCls;
              document.getElementById('reasons').textContent = (j.reasons||[]).slice(0,6).join(' · ');
              const ex = []; try { const ev = j.evidence_snapshot||{}; const ioc = ev.ioc_counts||{}; ex.push(`IOC: url=${ioc.url||0} domain=${ioc.domain||0} hash=${ioc.hash||0}`); if(ev.sender_trust && ev.sender_trust.sender_trust_score!=null){ ex.push(`Trust=${parseFloat(ev.sender_trust.sender_trust_score).toFixed(2)}`); } } catch(e) {}
              document.getElementById('extract').textContent = ex.join(' | ');
              renderSecurityPanels(j);
              const tid = j.decision_trace_id || j.decision_id || payload.message_id; if (tid) { attachTrace(tid); }
              document.getElementById('status').textContent='✓ Analysis complete';
            } catch(e) { document.getElementById('status').textContent='Analyze error'; pushTraceNotice('analyze_error', { endpoint: '/api/v1/email_security/evaluate', error: String(e && e.message ? e.message : e) }); }
          }
          async function submitEscalate(){
            resetPlaybookRunCard();
            document.getElementById('status').textContent='Analyzing & escalating…';
            const to = document.getElementById('to').value.trim();
            const subj = document.getElementById('subject').value.trim();
            const body = document.getElementById('body').value.trim();
            let atts = [];
            try { atts = await collectAllAttachments(); }
            catch(attErr){
              const msg = 'Attachment encoding failed: ' + String(attErr && attErr.message ? attErr.message : attErr);
              document.getElementById('status').textContent = msg;
              pushTraceNotice('attachment_encoding_failed', { error: msg });
              return;
            }
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
              renderSecurityPanels(j);
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
          function attachTrace(traceId){ currentDecisionId = traceId; document.getElementById('trace_id').textContent = traceId; const box = document.getElementById('trace'); const human = document.getElementById('trace_human'); box.innerHTML=''; if(human) human.innerHTML=''; if(es) try{ es.close(); }catch(e){}
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
                box.appendChild(d); box.scrollTop = box.scrollHeight; if(human){ const h=document.createElement('div'); h.innerHTML = renderNarrativeTraceEvent(it); if(h.firstChild) human.appendChild(h.firstChild); human.scrollTop = human.scrollHeight; } ingestPlaybookTraceEvent(it); } } catch(e){} };
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
                let roomIncidentId = match.id || '';
                const traceRef = String((match.evidence_snapshot || {}).trace_id || (match.evidence_snapshot || {}).decision_id || traceId || '').trim();
                if(traceRef){
                  try{
                    const incR = await fetch(`/api/v1/admin/incidents/${encodeURIComponent(traceRef)}`, { headers:{ 'x-api-key': getOwnerKey() } });
                    const incJ = await incR.json().catch(()=>null);
                    if(incR.ok && incJ && incJ.id){ roomIncidentId = incJ.id; }
                  }catch(e){}
                }
                const t = await fetch(`/api/v1/admin/incidents/${encodeURIComponent(roomIncidentId)}/room/token`, { method:'POST', headers:{ 'x-api-key': getOwnerKey() } });
                const tj = await t.json();
                if(tj && tj.staff_token){
                  const tok = tj.staff_token;
                  const btn = document.getElementById('inc_join');
                  btn.onclick = function(){ window.open(`/merchant/incident-room-lite?incident_id=${encodeURIComponent(roomIncidentId)}&token=${encodeURIComponent(tok)}`, '_blank'); };
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
              let r = await fetch('/api/v1/trace/events', { method:'POST', headers:{ 'Content-Type':'application/json', 'x-api-key': getApiKey() }, body: JSON.stringify(batch) });
              if(r.status === 401 || r.status === 403){
                r = await fetch('/api/v1/trace/events', { method:'POST', headers:{ 'Content-Type':'application/json', 'x-api-key': getOwnerKey() }, body: JSON.stringify(batch) });
              }
              if(!r.ok){ document.getElementById('status').textContent='Simulation failed ('+r.status+')'; pushTraceNotice('simulation_failed', { status: r.status }); return; }
              document.getElementById('status').textContent='Simulation events sent';
            }catch(e){ document.getElementById('status').textContent='Simulation error'; pushTraceNotice('simulation_error', { error: String(e && e.message ? e.message : e) }); }
          }
          // Explicit exports for Playwright/runtime checks.
          window.analyze = analyze;
          window.simulateAgents = simulateAgents;
          window.addEventListener('error', function(ev){
            try{
              const msg = 'UI script error: ' + String(ev && ev.message ? ev.message : ev);
              document.getElementById('status').textContent = msg;
              pushTraceNotice('ui_script_error', { error: msg });
            } catch(e){}
          });
          // Preload defaults
          newEmailPreset();
        </script>
      </body>
    </html>
    """
    resp = HTMLResponse(content=html)
    resp.set_cookie("shopsquire_api_key", _owner_key, httponly=False, samesite="strict")
    return resp
