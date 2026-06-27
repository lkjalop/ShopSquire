from __future__ import annotations

import base64
import html
import json
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.app.security.auth import ROLE_MERCHANT, require_role
from src.app.security.csrf_middleware import CSRF_COOKIE_NAME, generate_csrf_token, set_csrf_cookie
from src.app.services.nlp_query_clustering import QueryClusterer

router = APIRouter(prefix="/merchant", tags=["merchant"])


def _is_https_request(req: Request) -> bool:
    try:
        proto = str(req.headers.get("x-forwarded-proto") or req.url.scheme or "").lower()
        return proto == "https"
    except Exception:
        return False


def _merchant_html_response(request: Request, html: str) -> HTMLResponse:
    response = HTMLResponse(content=html)
    # Local merchant demo pages still rely on inline scripts and handlers.
    response.headers["content-security-policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss:; "
        "media-src 'self' blob:; "
        "worker-src blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "report-uri /api/v1/security/csp-report"
    )
    try:
        if not request.cookies.get(CSRF_COOKIE_NAME):
            set_csrf_cookie(response.headers, generate_csrf_token(), secure=_is_https_request(request))
    except Exception:
        pass
    return response


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


from src.app.services.demo_hunt_report import (  # extracted: pure deterministic demo report builder
    build_demo_hunt_report as _build_demo_hunt_report,
    decode_demo_hunt_context as _decode_demo_hunt_context,
)


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
    return _merchant_html_response(request, html)


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
    return _merchant_html_response(request, html)


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
          function getCsrfToken(){{ return getCookie('ss_csrf') || ''; }}
          function postHeaders(extra){{
            const out = Object.assign({{}}, extra || {{}});
            const csrf = getCsrfToken();
            if(csrf) out['x-csrf-token'] = csrf;
            return out;
          }}
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
    return _merchant_html_response(request, html)


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
    return _merchant_html_response(request, html)


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
                      credentials: 'include',
                      headers: postHeaders(getApiKey() ? {{ 'x-api-key': getApiKey() }} : undefined),
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
                credentials: 'include',
                headers: postHeaders({{ 'Content-Type':'application/json', 'x-incident-token': tok }}),
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
    return _merchant_html_response(request, html)


@router.get("/email-lab/threat-hunt", response_class=HTMLResponse)
def merchant_email_lab_threat_hunt(request: Request, ctx: str | None = None):
    if not (_is_loopback(request) or _is_local_demo_host(request)):
        raise HTTPException(status_code=403, detail="email_lab_local_only")

    report = _build_demo_hunt_report(_decode_demo_hunt_context(ctx))

    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else ""))

    def bullets(values: list[str]) -> str:
        rows = [f"<li>{esc(v)}</li>" for v in values if str(v or "").strip()]
        return "<ul>" + "".join(rows) + "</ul>" if rows else "<div class='muted'>No additional detail.</div>"

    def pill(text: str, tone: str = "") -> str:
        klass = f"pill {tone}".strip()
        return f"<span class=\"{klass}\">{esc(text)}</span>"

    pivot_rows = "".join(
        f"""
        <tr>
          <td>{esc(item.get("label"))}</td>
          <td>{esc(item.get("value"))}</td>
          <td>{'Included' if item.get("included") else 'Excluded'}</td>
          <td>{esc(item.get("why"))}</td>
        </tr>
        """
        for item in (report.get("pivots") or [])
    )

    source_rows = "".join(
        f"""
        <tr>
          <td>{esc(item.get("name"))}</td>
          <td>{esc(item.get("scope"))}</td>
          <td>{esc(item.get("query_count"))}</td>
          <td>{esc(item.get("why"))}</td>
        </tr>
        """
        for item in ((report.get("hunt_plan") or {}).get("sources_selected") or [])
    )

    optional_rows = "".join(
        f"""
        <tr>
          <td>{esc(item.get("name"))}</td>
          <td>{esc(item.get("status"))}</td>
          <td>{esc(item.get("why"))}</td>
        </tr>
        """
        for item in ((report.get("hunt_plan") or {}).get("sources_optional") or [])
    )

    matched_rows = "".join(
        f"""
        <tr>
          <td>{esc(cluster.get("title"))}</td>
          <td>{esc(cluster.get("confidence"))}</td>
          <td>{esc(cluster.get("summary"))}</td>
          <td>{esc(' | '.join(list(cluster.get("evidence") or [])[:3]))}</td>
        </tr>
        """
        for cluster in (report.get("clusters") or [])
    )

    cluster_html = "".join(
        f"""
        <section class="card">
          <h3>{esc(cluster.get("title"))} {pill(f"{cluster.get('confidence')} confidence", "info")}</h3>
          <p class="summary">{esc(cluster.get("summary"))}</p>
          <div class="grid two">
            <div>
              <div class="label">What The Hunt Found</div>
              {bullets(list(cluster.get("evidence") or []))}
            </div>
            <div>
              <div class="label">What The Agent Looked For</div>
              {bullets(list(cluster.get("analyst_checks") or []))}
            </div>
          </div>
        </section>
        """
        for cluster in report.get("clusters") or []
    )

    chronology_html = "".join(
        f"<tr><td>{esc(item.get('ts'))}</td><td>{esc(item.get('event'))}</td></tr>"
        for item in (report.get("chronology") or [])
    )

    provenance_rows = "".join(
        f"""
        <tr>
          <td>{esc(item.get("finding"))}</td>
          <td>{esc(item.get("source"))}</td>
          <td class="mono">{esc(item.get("query"))}</td>
          <td>{esc(', '.join(item.get("matched_fields") or []))}</td>
          <td>{esc(item.get("time_range"))}</td>
          <td>{esc(item.get("result_count"))}</td>
        </tr>
        """
        for item in (report.get("query_provenance") or [])
    )

    confidence_cards = "".join(
        f"""
        <section class="subcard">
          <div class="row" style="justify-content:space-between; align-items:center;">
            <strong>{esc(key.replace('_', ' ').title())}</strong>
            {pill(f"{value.get('score')}/100", 'accent')}
          </div>
          <div class="small" style="margin-top:4px;">{esc(value.get("label"))}</div>
          <p class="summary" style="margin-top:8px;">{esc(value.get("why"))}</p>
        </section>
        """
        for key, value in (report.get("confidence_model") or {}).items()
    )

    ascii_flow = r"""
+---------------------+     +-------------------------+     +-----------------------+
| Current Email Case  | --> | Evidence Pack Builder   | --> | Human Approval Gate   |
| subject/sender/urls |     | exact pivots only       |     | run bounded hunt      |
+---------------------+     +-------------------------+     +-----------------------+
             |                            |                              |
             v                            v                              v
   +------------------+        +----------------------+       +-----------------------+
   | Lone Event Check |        | Correlation Plan     |       | Approved Sources Only |
   | no overlap yet   |        | what to query + why  |       | mail/SEG/SIEM/IAM     |
   +------------------+        +----------------------+       +-----------------------+
             |                            |                              |
             +------------+---------------+------------------------------+
                          |
                          v
              +-----------------------------+
              | Cluster + Negative Evidence |
              | matched + not matched       |
              +-----------------------------+
                          |
                          v
              +-----------------------------+
              | Analyst Decision            |
              | monitor / escalate / push   |
              +-----------------------------+

Agentic defense ethos:
- each agent scopes itself to approved telemetry
- each agent emits provenance and confidence
- each agent can be challenged by negative evidence
- each agent stops at human gates for consequential actions
""".strip()

    html_body = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Threat Hunt Report</title>
        <style>
          :root {{
            --bg:#eef4ff; --surface:#ffffff; --surface2:#f8fbff; --border:#cfd9ea;
            --fg:#142033; --fg2:#495a74; --muted:#70829a; --accent:#2c5fe6; --accent2:#e8501a;
          }}
          * {{ box-sizing:border-box; }}
          body {{ margin:0; font-family:Inter,"Segoe UI",system-ui,sans-serif; background:linear-gradient(180deg,#f5f9ff 0%, var(--bg) 100%); color:var(--fg); }}
          header {{ padding:18px 22px; background:#1c2948; color:#eef1f7; }}
          header h1 {{ margin:0; font-size:20px; }}
          header p {{ margin:6px 0 0; color:rgba(238,241,247,0.76); }}
          .wrap {{ padding:18px; max-width:1400px; margin:0 auto; }}
          .banner {{ border:1px solid #f59e0b; background:#fff7ed; color:#9a3412; border-radius:14px; padding:12px 14px; margin-bottom:16px; font-weight:700; }}
          .grid {{ display:grid; gap:14px; }}
          .grid.top {{ grid-template-columns:repeat(3, minmax(0, 1fr)); }}
          .grid.two {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }}
          .grid.three {{ grid-template-columns:repeat(3, minmax(0, 1fr)); }}
          .card {{ border:1px solid var(--border); border-radius:14px; background:linear-gradient(180deg,var(--surface),var(--surface2)); padding:14px; box-shadow:0 10px 24px rgba(28,41,72,0.06); margin-bottom:14px; }}
          .subcard {{ border:1px solid var(--border); border-radius:12px; background:#fff; padding:12px; }}
          .card h2,.card h3 {{ margin:0 0 8px; }}
          .label {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); font-weight:700; margin-bottom:6px; }}
          .pill {{ display:inline-flex; padding:4px 10px; border-radius:999px; border:1px solid #b9c8e3; background:#eef4ff; color:#36517e; font-size:11px; font-weight:700; }}
          .pill.accent {{ background:#dbeafe; color:#1d4ed8; border-color:#93c5fd; }}
          .pill.warn {{ background:#fff7ed; color:#c2410c; border-color:#fdba74; }}
          .pill.info {{ background:#ecfeff; color:#0f766e; border-color:#99f6e4; }}
          .summary {{ margin:0 0 10px; color:var(--fg2); }}
          .kv {{ display:grid; grid-template-columns:150px 1fr; gap:8px; margin:6px 0; }}
          .muted {{ color:var(--muted); }}
          ul {{ margin:0; padding-left:18px; }}
          li {{ margin:4px 0; }}
          table {{ width:100%; border-collapse:collapse; }}
          th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); vertical-align:top; }}
          th {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
          .toolbar {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }}
          .btn {{ display:inline-block; padding:9px 13px; border-radius:10px; border:1px solid #9bb1d1; background:#fff; color:var(--fg); text-decoration:none; font-weight:700; }}
          .btn.primary {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
          .mono {{ font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }}
          pre.ascii {{ margin:0; white-space:pre-wrap; overflow:auto; background:#0f172a; color:#dbeafe; border-radius:12px; padding:14px; border:1px solid #334155; }}
          @media (max-width: 980px) {{
            .grid.top, .grid.two, .grid.three {{ grid-template-columns:1fr; }}
            .kv {{ grid-template-columns:1fr; }}
          }}
        </style>
      </head>
      <body>
        <header>
          <h1>Evidence-Scoped Threat Hunt</h1>
          <p>Human-gated bounded hunt plan generated from current email evidence. Synthetic demo telemetry only.</p>
        </header>
        <div class="wrap">
          <div class="banner">Synthetic telemetry corpus. Deterministic seeded demo data. No live tenant data used. The point is to show how an agent can plan, scope, defend, and audit its own investigation.</div>
          <div class="toolbar">
            <a class="btn" href="/merchant/email-lab">Back To Email Lab</a>
            {pill(f"Seeded from trace {report.get('trace_id')}")}
            {pill(f"Corpus: {report.get('corpus_messages')} messages / {report.get('corpus_days')} days")}
            {pill(f"Estimated run: {report.get('estimated_queries')} bounded queries / {report.get('estimated_minutes')} min", "warn")}
          </div>
          <div class="grid top">
            <section class="card">
              <h2>Seed Evidence</h2>
              <div class="kv"><div class="label">Subject</div><div>{esc(report.get("subject"))}</div></div>
              <div class="kv"><div class="label">Sender</div><div>{esc(report.get("sender"))}</div></div>
              <div class="kv"><div class="label">Reply-To</div><div>{esc(report.get("reply_to"))}</div></div>
              <div class="kv"><div class="label">Route</div><div>{esc(report.get("route"))} / {esc(report.get("verdict_action"))}</div></div>
              <div class="kv"><div class="label">Reasons</div><div>{esc(", ".join(report.get("reasons") or []))}</div></div>
              <div class="kv"><div class="label">MITRE</div><div>{esc(", ".join(report.get("mitre_attack") or [])) or "No tags"}</div></div>
            </section>
            <section class="card">
              <h2>Human Gate</h2>
              <div class="kv"><div class="label">Approval</div><div>{esc((report.get("hunt_plan") or {}).get("approval_level"))}</div></div>
              <div class="kv"><div class="label">Time window</div><div>{esc((report.get("hunt_plan") or {}).get("time_window"))}</div></div>
              <div class="kv"><div class="label">Estimated cost</div><div>{esc((report.get("hunt_plan") or {}).get("estimated_cost"))}</div></div>
              <div class="kv"><div class="label">Why generated</div><div>{esc((report.get("hunt_plan") or {}).get("why_generated"))}</div></div>
            </section>
            <section class="card">
              <h2>Corpus Scope</h2>
              <div class="kv"><div class="label">Messages</div><div>{esc(report.get("corpus_messages"))}</div></div>
              <div class="kv"><div class="label">Identities</div><div>{esc(report.get("corpus_identities"))}</div></div>
              <div class="kv"><div class="label">Suppliers</div><div>{esc(report.get("corpus_suppliers"))}</div></div>
              <div class="kv"><div class="label">Geo / ASN</div><div>{esc(report.get("geo_country"))} / {esc(report.get("asn"))} ({esc(report.get("asn_org"))})</div></div>
              <div class="kv"><div class="label">Related incidents</div><div>{esc(report.get("related_incidents"))}</div></div>
            </section>
          </div>
          <div class="grid two">
            <section class="card">
              <h2>Deterministic Hunt Plan</h2>
              <div class="label">Exact pivots generated from current evidence</div>
              <table>
                <thead><tr><th>Pivot</th><th>Value</th><th>Status</th><th>Why included</th></tr></thead>
                <tbody>{pivot_rows}</tbody>
              </table>
              <div class="label" style="margin-top:12px;">Excluded pivots</div>
              {bullets(list((report.get("hunt_plan") or {}).get("excluded_pivots") or []))}
            </section>
            <section class="card">
              <h2>Source-Bounded Execution</h2>
              <div class="label">Approved sources selected</div>
              <table>
                <thead><tr><th>Source</th><th>Scope</th><th>Queries</th><th>Why touched</th></tr></thead>
                <tbody>{source_rows}</tbody>
              </table>
              <div class="label" style="margin-top:12px;">Optional sources only if connected</div>
              <table>
                <thead><tr><th>Source</th><th>Status</th><th>Use</th></tr></thead>
                <tbody>{optional_rows}</tbody>
              </table>
            </section>
          </div>
          <div class="grid two">
            <section class="card">
              <h2>Matched Signals</h2>
              <p class="summary">These are the strongest bounded correlations found in the synthetic corpus before any narrative interpretation.</p>
              <table>
                <thead><tr><th>Cluster</th><th>Confidence</th><th>What matched</th><th>Evidence highlights</th></tr></thead>
                <tbody>{matched_rows}</tbody>
              </table>
            </section>
            <section class="card">
              <h2>Negative Evidence</h2>
              {bullets(list(report.get("negative_evidence") or []))}
            </section>
          </div>
          <div class="grid three">
            <section class="card">
              <h2>Confidence Model</h2>
              <div class="grid">{confidence_cards}</div>
            </section>
            <section class="card">
              <h2>False-Positive Guardrails</h2>
              <div class="label">Would weaken the hypothesis</div>
              {bullets(list(((report.get("guardrails") or {}).get("would_weaken")) or []))}
              <div class="label" style="margin-top:12px;">Would confirm it</div>
              {bullets(list(((report.get("guardrails") or {}).get("would_confirm")) or []))}
              <div class="label" style="margin-top:12px;">Requires human verification</div>
              {bullets(list(((report.get("guardrails") or {}).get("requires_human")) or []))}
            </section>
            <section class="card">
              <h2>Analyst Narrative</h2>
              <p class="summary">The current email justifies a bounded hunt because the evidence suggests payment-change fraud or supplier impersonation. The agent scoped the hunt to approved synthetic sources, looked for repeated sender infrastructure, payment details, and trust-relationship drift, and found enough overlap to warrant further analyst attention.</p>
              <p class="summary">The hunt did not claim unrestricted tenant-wide visibility, and it surfaced both matching and non-matching signals so the analyst can decide whether this is an isolated event, a correlated campaign, or a legitimate business exception.</p>
            </section>
          </div>
          <div class="grid two">
            <section class="card">
              <h2>Structured Hunt Output</h2>
              <p class="summary">Long-form evidence summaries and analyst guidance follow the bounded results above.</p>
              {cluster_html}
            </section>
            <section class="card">
              <h2>Query Provenance</h2>
              <table>
                <thead><tr><th>Finding</th><th>Source</th><th>Query used</th><th>Matched fields</th><th>Window</th><th>Results</th></tr></thead>
                <tbody>{provenance_rows}</tbody>
              </table>
            </section>
          </div>
          <div class="grid two">
            <section class="card">
              <h2>Audit Trail</h2>
              {bullets(list(report.get("audit_trail") or []))}
            </section>
            <section class="card">
              <h2>Timeline</h2>
              <table>
                <thead><tr><th>Date</th><th>Synthetic Event</th></tr></thead>
                <tbody>{chronology_html}</tbody>
              </table>
            </section>
            <section class="card">
              <h2>Recommended Next Checks</h2>
              <div class="label">Where the agent would look next</div>
              {bullets(list(report.get("downstream") or []))}
              <div class="label" style="margin-top:12px;">Production-quality shape</div>
              {bullets(list(report.get("production") or []))}
              <div class="label" style="margin-top:12px;">Attachments in scope</div>
              {bullets(list(report.get("attachments") or []))}
            </section>
          </div>
          <section class="card">
            <h2>Agentic Investigation Flow</h2>
            <pre class="ascii">{esc(ascii_flow)}</pre>
          </section>
        </div>
      </body>
    </html>
    """
    return _merchant_html_response(request, html_body)


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
            --bg: #f4f7fb;
            --surface: #ffffff;
            --surface2: #f7faff;
            --surface3: #eef4ff;
            --border: #cfd9ea;
            --border-strong: #9bb1d1;
            --fg: #142033;
            --fg2: #43536d;
            --muted: #6f8098;
            --accent: #2c5fe6;
            --accent2: #e8501a;
            --success: #0f8a5e;
            --header-bg: #1c2948;
            --header-fg:#eef1f7;
            --card-shadow: 0 10px 28px rgba(28, 41, 72, 0.08);
            --radius: 12px;
          }
          *, *::before, *::after { box-sizing: border-box; }
          body { margin:0; font-family: Inter, "Segoe UI", system-ui, -apple-system, Arial, sans-serif; background: radial-gradient(circle at top right, rgba(44,95,230,0.08), transparent 22%), linear-gradient(180deg, #f7faff 0%, var(--bg) 100%); color: var(--fg); font-size: 13px; line-height: 1.5; }
          /* Header */
          header { padding: 0 18px; height: 52px; display:flex; justify-content:space-between; align-items:center; background: var(--header-bg); box-shadow: 0 2px 8px rgba(0,0,0,0.18); }
          .brand { font-weight: 700; font-size: 14px; color: var(--header-fg); letter-spacing: 0.2px; }
          .sub { color: rgba(238,241,247,0.6); font-size: 11px; margin-top: 2px; }
          /* Layout */
          .wrap { display:grid; grid-template-columns: 310px 1fr 390px; gap:0; height: calc(100vh - 52px); overflow: hidden; }
          .col { border-right: 1px solid rgba(155,177,209,0.35); overflow-y: auto; }
          .pane { padding: 12px 14px; }
          /* Cards */
          .card { border: 1px solid var(--border); border-radius: 14px; background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,255,0.98)); box-shadow: var(--card-shadow); margin-bottom: 12px; overflow: hidden; }
          .card h4 { margin: 0; padding: 11px 14px; border-bottom: 1px solid rgba(155,177,209,0.28); font-size: 12px; font-weight: 700; color: #54657f; text-transform: uppercase; letter-spacing: 0.5px; background: linear-gradient(180deg, var(--surface3), var(--surface2)); border-radius: var(--radius) var(--radius) 0 0; }
          .card .body { padding: 12px 14px; }
          /* Form controls */
          input, textarea, select { width: 100%; padding: 7px 10px; border-radius: 9px; border: 1px solid var(--border); background: rgba(255,255,255,0.98); color: var(--fg); font-size: 12px; outline: none; transition: border-color 0.15s; }
          input:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(44,95,230,0.12); }
          textarea { min-height: 160px; resize: vertical; }
          input[type=file] { border-style: dashed; padding: 10px; cursor: pointer; }
          /* Labels */
          .field-label { font-size: 11px; font-weight: 600; color: var(--fg2); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.4px; }
          /* Rows */
          .row { display:flex; gap:8px; align-items:center; }
          /* Buttons */
          .btn { padding: 7px 13px; border-radius: 9px; border: 1px solid var(--border-strong); background: linear-gradient(180deg, #ffffff, #f5f8ff); color: var(--fg); cursor: pointer; font-size: 12px; font-weight: 600; white-space: nowrap; transition: all 0.15s; box-shadow: 0 2px 8px rgba(28,41,72,0.05); }
          .btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
          .btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
          .btn-primary:hover { background: #1e4ac8; border-color: #1e4ac8; }
          .btn-danger { background: var(--accent2); color: #fff; border-color: var(--accent2); }
          .btn-danger:hover { background: #c43c10; border-color: #c43c10; }
          /* Pills / badges */
          .pill { display:inline-flex; align-items:center; gap:4px; padding: 3px 9px; border: 1px solid rgba(155,177,209,0.45); border-radius: 999px; background: linear-gradient(180deg, #ffffff, #eef4ff); font-size: 11px; color: var(--fg2); font-weight: 600; }
          /* Inbox items */
          .list { display:flex; flex-direction:column; gap:6px; max-height: 220px; overflow:auto; }
          .item { display:flex; flex-direction:column; gap:4px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 10px; cursor:pointer; background: linear-gradient(180deg, #ffffff, #f8fbff); transition: all 0.12s; }
          .item:hover { border-color: var(--accent); background: rgba(44,95,230,0.05); box-shadow: 0 8px 20px rgba(44,95,230,0.08); }
          .item .item-from { font-weight: 600; font-size: 12px; color: var(--fg); }
          .item .item-sub { font-size: 11px; color: var(--fg2); }
          .item .item-preview { font-size: 11px; color: var(--muted); }
          /* Verdict badge */
          #verdict { display: inline-block; font-weight: 700; font-size: 13px; }
          /* Small / muted */
          .small { font-size: 11px; color: var(--muted); }
          .mono { font-family: ui-monospace, "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace; font-size: 11px; }
          /* Trace / SSE stream */
          .trace { overflow:auto; padding: 8px; border: 1px solid var(--border); border-radius: 10px; background: linear-gradient(180deg, #fbfdff, #f4f8ff); }
          .ev { margin-bottom: 6px; padding: 7px 10px; border-left: 3px solid var(--accent); background: var(--surface); border-radius: 0 8px 8px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
          .ev .meta { font-size: 10px; color: var(--muted); margin-bottom: 3px; }
          /* Severity verdict bar states */
          .sev-error   { background: #fff1f0; border-left: 4px solid #ef4444; color: #b91c1c; }
          .sev-warning { background: #fffbeb; border-left: 4px solid #f59e0b; color: #92400e; }
          .sev-info    { background: #eff6ff; border-left: 4px solid #3b82f6; color: #1d4ed8; }
          .right-rail { overflow-y: auto; overflow-x: auto; max-height: calc(100vh - 60px); background: linear-gradient(180deg, rgba(247,250,255,0.92), rgba(241,246,255,0.96)); }
          .right-rail.detached {
            position: fixed;
            top: 72px;
            right: 16px;
            width: min(860px, 72vw);
            min-width: 560px;
            max-height: calc(100vh - 88px);
            z-index: 1000;
            background: rgba(243, 246, 251, 0.98);
            border: 1px solid var(--border);
            border-radius: 14px;
            box-shadow: 0 24px 64px rgba(15, 23, 42, 0.24);
            padding: 10px;
            resize: horizontal;
            overflow: auto;
          }
          .rail-toolbar { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }
          .card-grid { display:grid; grid-template-columns:1fr; gap:10px; }
          .summary-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
          .finding-list { margin:0; padding-left:16px; }
          .finding-list li { margin:4px 0; }
          .section-label { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:#64748b; margin-bottom:4px; font-weight:700; }
          .evidence-block { padding:12px; border:1px solid rgba(155,177,209,0.42); border-left:4px solid #5b7ee5; border-radius:12px; background:linear-gradient(180deg, #ffffff, #f8fbff); margin-top:8px; box-shadow: 0 8px 20px rgba(28,41,72,0.05); }
          .attachment-row { padding:12px; border:1px solid rgba(155,177,209,0.42); border-left:4px solid #f59e0b; border-radius:12px; background:linear-gradient(180deg, #ffffff, #fffaf1); margin-top:8px; box-shadow: 0 8px 20px rgba(28,41,72,0.05); }
          .thumb-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-top:8px; }
          .thumb-grid img { width:100%; border:1px solid var(--border); border-radius:8px; background:#fff; }
          .trace-toggle { display:flex; gap:6px; margin:8px 0; }
          .trace-toggle button.active { background:#1d4ed8; color:#fff; border-color:#1d4ed8; }
          .finding-drilldown { margin-top: 8px; border: 1px solid rgba(155,177,209,0.34); border-radius: 12px; background: linear-gradient(180deg, #ffffff, #f8fbff); }
          .finding-drilldown > summary { cursor: pointer; padding: 10px 12px; font-weight: 700; color: #334155; }
          .finding-drilldown-body { padding: 0 12px 12px; color: var(--fg2); }
          #evidence_sections, #actions_sections, #integrations_sections, #gov_sections, #graph_sections, #tones_sections, #attach_forensics, #pdf_diff_sections, #visual_diff_sections, #qr_findings, #infra_sections { display:grid; grid-template-columns:minmax(0, 1fr); gap:12px; }
          .right-rail.wide #evidence_sections, .right-rail.wide #actions_sections, .right-rail.wide #integrations_sections, .right-rail.wide #gov_sections, .right-rail.wide #graph_sections, .right-rail.wide #tones_sections, .right-rail.wide #attach_forensics, .right-rail.wide #pdf_diff_sections, .right-rail.wide #visual_diff_sections, .right-rail.wide #qr_findings, .right-rail.wide #infra_sections { grid-template-columns:repeat(2, minmax(0, 1fr)); align-items:start; }
          .right-rail.detached .card { min-width: 680px; }
          .right-rail.detached.wide .card { min-width: 0; }
          @media (max-width: 1200px) { .wrap { grid-template-columns: 270px 1fr 360px; } }
          @media (max-width: 980px) {
            .wrap { grid-template-columns: 1fr; height: auto; overflow: auto; }
            .col { border-right: 0; }
            .right-rail { max-height: none; }
            .summary-grid { grid-template-columns: 1fr; }
          }
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
            <span class="pill" id="api_health_badge" style="background:rgba(238,241,247,0.1);color:#eef1f7;border-color:rgba(238,241,247,0.2);" title="Checking backend status">API <span id="api_health" style="font-weight:700;">checking…</span></span>
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
                <textarea id="body" placeholder="Type email body..."></textarea>
                <div style="margin-top:10px" class="field-label">Attachments</div>
                <input type="file" id="files" multiple />
                <div id="att_list" class="small mono" style="margin-top:6px; white-space:pre-wrap;"></div>
                <div class="row" style="margin-top:12px; flex-wrap:wrap; gap:6px;">
                  <button class="btn btn-primary" aria-label="Analyze email and populate security matrix" onclick="analyze()">&#128269; Analyze</button>
                  <button class="btn btn-danger" aria-label="Analyze email and escalate to incident room" onclick="submitEscalate()">&#9888; Escalate</button>
                  <button class="btn" aria-label="Run a human-gated synthetic threat hunt in a new tab" onclick="runThreatHunt()" style="border-color:#f59e0b;background:linear-gradient(180deg,#fff7ed,#ffedd5);color:#9a3412;font-weight:700;">&#128270; Run Threat Hunt</button>
                  <button class="btn" aria-label="Load email lab demo assets" onclick="loadDemoAssets()">&#128196; Demo</button>
                  <button class="btn" aria-label="Simulate agent events in decision trace" onclick="simulateAgents()">&#129302; Agents</button>
                  <span class="small" style="color:#9a3412;">Human-gated new tab: bounded synthetic correlation hunt</span>
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
              <h4>Decision</h4>
              <div class="body">
                <div class="summary-grid">
                  <div>
                    <div class="section-label">Decision</div>
                    <div id="exec_what_happened" class="small"></div>
                  </div>
                  <div>
                    <div class="section-label">Business Risk</div>
                    <div id="exec_business_risk" class="small"></div>
                  </div>
                </div>
                <div style="margin-top:8px;">
                  <div class="section-label">What Triggered It</div>
                  <div id="exec_why_flagged" class="small"></div>
                </div>
                <div style="margin-top:8px;">
                  <div class="section-label">Do This Now</div>
                  <div id="exec_immediate_actions" class="small"></div>
                </div>
                <div style="margin-top:8px;">
                  <div class="section-label">Human Gate</div>
                  <div id="exec_next_steps" class="small"></div>
                </div>
              </div>
            </div>
            <!-- Security Overview Panel (populated after Analyze) -->
            <div class="card" id="sec_overview" style="display:none;">
              <h4>What Triggered It</h4>
              <div class="body">
                <div class="row" style="flex-wrap:wrap; gap:6px; margin-bottom:8px;" id="sec_badges"></div>
                <div id="sec_verdict_bar" style="padding:8px 10px; border-radius:8px; margin-bottom:8px; font-weight:600;"></div>
                <div class="small" id="sec_reasons_list"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="playbook_card">
              <h4>Parallel Agents Reasoning</h4>
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
              <h4>Top Evidence</h4>
              <div class="body">
                <div id="evidence_sections" class="small"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="actions_card">
              <h4>What To Do Now</h4>
              <div class="body">
                <div id="actions_sections" class="small"></div>
              </div>
            </div>
            <!-- BEC Kill Chain -->
            <div class="card" style="margin-top:10px; display:none;" id="bec_card">
              <h4>BEC Kill Chain</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open kill chain detail</summary>
                <div class="body" style="padding-top:0;">
                <div id="bec_stage" style="font-weight:700; color:#f97316; font-size:15px;"></div>
                <div id="bec_flow" class="small" style="margin-top:6px;"></div>
                <div class="row" style="margin-top:6px; gap:6px; flex-wrap:wrap;" id="bec_badges"></div>
                </div>
              </details>
            </div>
            <!-- Trust Case & Access Policy -->
            <div class="card" style="margin-top:10px; display:none;" id="trust_card">
              <h4>Trust Case & Access Policy</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open trust detail</summary>
                <div class="body" style="padding-top:0;">
                <div class="row" style="gap:10px; flex-wrap:wrap;">
                  <div><div class="small">Trust Score</div><div id="trust_score" style="font-size:22px; font-weight:700;">-</div></div>
                  <div><div class="small">Level</div><div id="trust_level" style="font-size:14px; font-weight:600;">-</div></div>
                  <div><div class="small">Access</div><div id="trust_access" style="font-size:14px; font-weight:600;">-</div></div>
                </div>
                <div class="small" style="margin-top:6px;" id="trust_actions"></div>
                <div class="small" style="margin-top:4px; color:#94a3b8;" id="trust_reasons"></div>
                </div>
              </details>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="infra_card">
              <h4>Related Incidents</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open related incident detail</summary>
                <div class="body" style="padding-top:0;">
                  <div id="infra_sections" class="small"></div>
                </div>
              </details>
            </div>
            <!-- Threat Correlation (MITRE/DREAD/CVSS/KEV/PASTA) -->
            <div class="card" style="margin-top:10px; display:none;" id="threat_card">
              <h4>Audit / Compliance</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open audit mapping</summary>
                <div class="body" style="padding-top:0;">
                <div class="row" style="gap:6px; flex-wrap:wrap;" id="threat_badges"></div>
                <div style="margin-top:8px; display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                  <div><div class="small">DREAD avg</div><div id="dread_avg" style="font-weight:700;">-</div></div>
                  <div><div class="small">CVSS</div><div id="cvss_score" style="font-weight:700;">-</div></div>
                  <div><div class="small">Kill Chain</div><div id="kc_stage" style="font-weight:700;">-</div></div>
                  <div><div class="small">PASTA Stage</div><div id="pasta_stage" style="font-weight:700;">-</div></div>
                </div>
                <div class="small" style="margin-top:6px;" id="kev_list"></div>
                </div>
              </details>
            </div>
            <!-- Sandbox / Detonation / IOC -->
            <div class="card" style="margin-top:10px; display:none;" id="sandbox_card">
              <h4>Sandbox & IOC Enrichment</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open sandbox and IOC detail</summary>
                <div class="body" style="padding-top:0;">
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                  <div><div class="small">Detonation</div><div id="det_result" style="font-weight:700;">-</div></div>
                  <div><div class="small">IOC Malicious</div><div id="ioc_hits" style="font-weight:700;">0</div></div>
                  <div><div class="small">IOC Resolution</div><div id="ioc_resolution" style="font-weight:600;">-</div></div>
                  <div><div class="small">Enrichment Latency</div><div id="enrich_latency" class="small">-</div></div>
                </div>
                <div class="small" style="margin-top:6px;" id="sandbox_findings"></div>
                </div>
              </details>
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
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open PDF diff detail</summary>
                <div class="body" style="padding-top:0;">
                <div id="pdf_diff_sections" class="small"></div>
                </div>
              </details>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="visual_diff_card">
              <h4>Supplier Baseline Visual Diff</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open visual diff detail</summary>
                <div class="body" style="padding-top:0;">
                <div id="visual_diff_sections" class="small"></div>
                </div>
              </details>
            </div>
            <!-- QR / OCR Findings -->
            <div class="card" style="margin-top:10px; display:none;" id="qr_card">
              <h4>QR / OCR Findings</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open QR and OCR detail</summary>
                <div class="body" style="padding-top:0;">
                <div id="qr_findings" class="small"></div>
                </div>
              </details>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="integrations_card">
              <h4>Notifications / Push</h4>
              <div class="body">
                <div id="integrations_sections" class="small"></div>
              </div>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="gov_card">
              <h4>Governance / Trust</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open governance and trust detail</summary>
                <div class="body" style="padding-top:0;">
                  <div id="gov_sections" class="small"></div>
                </div>
              </details>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="graph_card">
              <h4>Vendor Trust Graph</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open trust graph detail</summary>
                <div class="body" style="padding-top:0;">
                  <div id="graph_sections" class="small"></div>
                </div>
              </details>
            </div>
            <div class="card" style="margin-top:10px; display:none;" id="tones_card">
              <h4>Verdict In 3 Views</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open explanation detail</summary>
                <div class="body" style="padding-top:0;">
                <div id="tones_sections" class="small"></div>
                </div>
              </details>
            </div>
            <!-- Decision Trace (SSE stream) -->
            <div class="card" style="margin-top:10px;">
              <h4>Decision Trace & Security Matrix</h4>
              <div class="body" style="padding-bottom:0;">
                <div class="small">Trace ID: <span class="mono" id="trace_id">n/a</span></div>
              </div>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open raw and explain trace</summary>
                <div class="body" style="padding-top:0;">
                <div class="trace-toggle">
                  <button class="btn active" id="trace_btn_explain" type="button" onclick="setTraceMode('explain')">Explain</button>
                  <button class="btn" id="trace_btn_raw" type="button" onclick="setTraceMode('raw')">Raw</button>
                </div>
                <div class="trace" id="trace_human" style="max-height:280px;"></div>
                <div class="trace" id="trace" style="max-height:280px; display:none;"></div>
                </div>
              </details>
            </div>
            <!-- Related Incident -->
            <div class="card" style="margin-top:10px;">
              <h4>Related Incident</h4>
              <details>
                <summary class="body" style="cursor:pointer; font-weight:600;">Open related incident detail</summary>
                <div class="body" style="padding-top:0;">
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
              </details>
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
          function getCsrfToken(){
            try { return getCookie('ss_csrf') || ''; } catch(e){ return ''; }
          }
          function postHeaders(extra){
            const out = Object.assign({}, extra || {});
            const csrf = getCsrfToken();
            if(csrf) out['x-csrf-token'] = csrf;
            return out;
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
          function setApiHealthBadge(label, palette, titleText){
            const textEl = document.getElementById('api_health');
            const badgeEl = document.getElementById('api_health_badge');
            if(textEl) textEl.textContent = label;
            if(badgeEl){
              if(palette && palette.bg) badgeEl.style.background = palette.bg;
              if(palette && palette.color) badgeEl.style.color = palette.color;
              if(palette && palette.border) badgeEl.style.borderColor = palette.border;
              if(titleText) badgeEl.title = titleText;
            }
          }
          function collectHealthIssues(snapshot){
            try{
              const deps = snapshot && snapshot.dependencies && typeof snapshot.dependencies === 'object' ? snapshot.dependencies : {};
              return Object.entries(deps)
                .filter(([, info]) => info && typeof info === 'object' && !['healthy','ok','ready'].includes(String(info.status || '').toLowerCase()))
                .map(([name, info]) => `${name}: ${String(info.status || 'unknown')}`);
            }catch(e){
              return [];
            }
          }
          async function ping(){
            try {
              const live = await fetch('/healthz');
              if(!live.ok) throw new Error('healthz_failed');
              let detailed = null;
              try {
                const detailResp = await fetch('/health');
                if(detailResp.ok) detailed = await detailResp.json();
              } catch(e) {}
              const issues = collectHealthIssues(detailed);
              if(detailed && String(detailed.status || '').toLowerCase() === 'degraded'){
                setApiHealthBadge(
                  'live (limited)',
                  { bg:'rgba(245,158,11,0.18)', color:'#fde68a', border:'rgba(245,158,11,0.35)' },
                  issues.length ? `Backend is live with limited dependencies: ${issues.join(' | ')}` : 'Backend is live with some optional dependencies unavailable.'
                );
                return;
              }
              setApiHealthBadge(
                'live',
                { bg:'rgba(34,197,94,0.18)', color:'#dcfce7', border:'rgba(34,197,94,0.35)' },
                'Backend is live and core dependencies are healthy.'
              );
            } catch(e){
              setApiHealthBadge(
                'down',
                { bg:'rgba(220,38,38,0.18)', color:'#fecaca', border:'rgba(220,38,38,0.35)' },
                'Backend did not respond to liveness checks.'
              );
            }
          }
          ping();
          window.addEventListener('resize', updateRailLayout);
          window.addEventListener('load', updateRailLayout);
          function toUrlSafeBase64(payload){
            try{
              const json = JSON.stringify(payload || {});
              const utf8 = unescape(encodeURIComponent(json));
              return btoa(utf8).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
            }catch(e){
              return '';
            }
          }
          function buildThreatHuntContext(){
            const j = currentSecurityResult || {};
            const ev = j.evidence_snapshot || {};
            const thr = ev.threat_correlation || j.threat_correlation || {};
            const sa = ev.security_analysis || {};
            const infra = ev.sender_infrastructure || {};
            const geo = infra.originating_geo || {};
            const rel = infra.related_incidents || {};
            const atts = Array.isArray(ev.attachment_forensics) ? ev.attachment_forensics : [];
            return {
              trace_id: j.decision_trace_id || j.decision_id || currentDecisionId || 'trace-demo-email-hunt',
              subject: document.getElementById('subject')?.value || '',
              sender: document.getElementById('to')?.value || '',
              reply_to: j.reply_to || document.getElementById('to')?.value || '',
              severity: j.severity || '',
              verdict_action: j.verdict_action || '',
              route: j.route || '',
              risk_band: j.risk_band || '',
              reasons: Array.isArray(j.reasons) ? j.reasons.slice(0, 8) : [],
              mitre_attack: Array.isArray(sa.mitre_attack) && sa.mitre_attack.length ? sa.mitre_attack.slice(0, 8) : (Array.isArray(thr.mitre_attack) ? thr.mitre_attack.slice(0, 8) : []),
              geo_country: geo.country || '',
              asn: geo.asn || infra.originating_asn || '',
              asn_org: geo.asn_org || '',
              related_incident_count: rel.count || 0,
              reply_domain_mismatch: Boolean(infra.reply_domain_mismatch),
              attachments: atts.slice(0, 6).map(item => String(item.file_name || 'attachment')).filter(Boolean),
            };
          }
          function runThreatHunt(){
            if(!currentSecurityResult){
              document.getElementById('status').textContent = 'Analyze the email first to seed the hunt.';
              return;
            }
            const huntWindow = window.open('about:blank', '_blank', 'noopener');
            if(!huntWindow){
              document.getElementById('status').textContent = 'Popup blocked. Allow popups to open the threat hunt report.';
              return;
            }
            const token = toUrlSafeBase64(buildThreatHuntContext());
            huntWindow.location = `/merchant/email-lab/threat-hunt?ctx=${encodeURIComponent(token)}`;
            document.getElementById('status').textContent = 'Opened human-gated threat hunt report (synthetic demo telemetry).';
            pushTraceNotice('threat_hunt_opened', { trace_id: currentDecisionId || null, synthetic_demo: true });
          }
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
          function stripInlineMarkup(value){
            return String(value == null ? '' : value)
              .replace(/<[^>]*>/g, ' ')
              .replace(/\s+/g, ' ')
              .trim();
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
            const sa = ((j||{}).evidence_snapshot || {}).security_analysis || {};
            const stage = String(sa.validated_pasta_stage || sa.pasta_stage || (thr||{}).pasta_stage || '').trim();
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
            const biz = stripInlineMarkup(f.business_meaning || '');
            if(biz) return biz;
            const summary = stripInlineMarkup(f.summary || '');
            if(summary) return summary;
            const kind = String(f.finding_type || 'finding').replaceAll('_', ' ');
            const ev = Array.isArray(f.evidence) ? f.evidence.map(v => stripInlineMarkup(v)).filter(Boolean) : [];
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
          function ownerScopeBadgeHtml(scope){
            const normalized = String(scope || '').trim().toLowerCase();
            if(!normalized) return '';
            if(normalized === 'likely_internal_platform') return '<span class="pill" style="background:#dcfce7;color:#166534;border-color:#bbf7d0;">Owner: internal</span>';
            if(normalized === 'external_or_third_party') return '<span class="pill" style="background:#fee2e2;color:#991b1b;border-color:#fecaca;">Owner: external</span>';
            if(normalized === 'external_redirect_service') return '<span class="pill" style="background:#fef3c7;color:#92400e;border-color:#fde68a;">Owner: redirect / unknown</span>';
            return '<span class="pill" style="background:#e2e8f0;color:#334155;border-color:#cbd5e1;">Owner: unknown</span>';
          }
          function mitreBadgesHtml(tags){
            const rows = Array.isArray(tags) ? tags.filter(Boolean) : [];
            if(!rows.length) return '<div class="small" style="color:#94a3b8;">No MITRE tags were attached to this finding.</div>';
            return `<div class="row" style="gap:6px; flex-wrap:wrap;">${rows.map(tag => `<span class="pill">${escHtml(String(tag))}</span>`).join('')}</div>`;
          }
          function dreadDriversForComponent(dread, key){
            const dd = dread && typeof dread === 'object' ? dread : {};
            const evidence = Array.isArray(dd.evidence) ? dd.evidence : [];
            return evidence
              .filter(item => String((item || {}).component || '') === key)
              .slice(0, 4)
              .map(item => {
                const signal = String((item || {}).signal || 'signal').replaceAll('_', ' ');
                const contribution = item && item.contribution != null ? ` (+${item.contribution})` : '';
                return `${signal}${contribution}`;
              });
          }
          function dreadDimensionMeta(key){
            const defs = {
              damage: {
                label: 'Damage',
                meaning: 'How bad the business impact would be if the attack succeeds.',
                significance: 'High damage means the organization could lose money, trust, or operational integrity.'
              },
              reproducibility: {
                label: 'Reproducibility',
                meaning: 'How reliably the attack can be repeated.',
                significance: 'High reproducibility means the same attack pattern can be reused across more victims.'
              },
              exploitability: {
                label: 'Exploitability',
                meaning: 'How easy it is to launch or execute.',
                significance: 'High exploitability means the attacker needs little friction, tooling, or access.'
              },
              affected_users: {
                label: 'Affected Users',
                meaning: 'How broad the likely user or business impact is.',
                significance: 'Higher affected-users scores suggest broader blast radius across teams, suppliers, or customers.'
              },
              discoverability: {
                label: 'Discoverability',
                meaning: 'How easy it is to identify and exploit the weakness.',
                significance: 'High discoverability means the target pattern is easy for attackers to find and abuse.'
              },
            };
            return defs[key] || { label: key, meaning: 'Risk dimension', significance: 'Used to explain why the score matters.' };
          }
          function dreadBand(value){
            const num = parseFloat(value);
            if(Number.isNaN(num)) return 'Unknown';
            if(num >= 8) return 'High';
            if(num >= 5) return 'Moderate';
            return 'Low';
          }
          function dreadDisplayValue(dread, key){
            const dd = dread && typeof dread === 'object' ? dread : {};
            const value = dd[key];
            const drivers = dreadDriversForComponent(dd, key);
            if(value == null) return '-';
            if(drivers.length) return `${value}/10`;
            return `${dreadBand(value)} (heuristic)`;
          }
          function dreadEvidenceTableHtml(dreadOrDimensions, businessOutcome){
            const backendDimensions = dreadOrDimensions && typeof dreadOrDimensions === 'object' && !Array.isArray(dreadOrDimensions) && (dreadOrDimensions.damage && typeof dreadOrDimensions.damage === 'object' && ('band' in dreadOrDimensions.damage || 'drivers' in dreadOrDimensions.damage));
            const dd = dreadOrDimensions && typeof dreadOrDimensions === 'object' ? dreadOrDimensions : {};
            const defs = ['damage', 'reproducibility', 'exploitability', 'affected_users', 'discoverability'];
            const rows = defs.map((key) => {
              const meta = dreadDimensionMeta(key);
              const value = backendDimensions ? ((dd[key] || {}).score) : dd[key];
              const band = backendDimensions ? String((dd[key] || {}).band || 'unknown') : '';
              const drivers = backendDimensions ? (((dd[key] || {}).drivers) || []) : dreadDriversForComponent(dd, key);
              const evidenceRefs = backendDimensions ? (((dd[key] || {}).evidence_refs) || []) : [];
              const why = backendDimensions ? (((dd[key] || {}).why_it_matters) || businessOutcome || meta.significance) : (businessOutcome || meta.significance);
              return `<tr>
                <td><strong>${escHtml(meta.label)}</strong><div class="small">${escHtml(meta.meaning)}</div></td>
                <td>${backendDimensions ? escHtml(value != null ? `${value}/10` : `${band} (heuristic)`) : escHtml(dreadDisplayValue(dd, key))}</td>
                <td>${escHtml(drivers.length ? drivers.join(' | ') : 'No explicit component-level drivers were returned. Score downgraded to a heuristic band, not precise risk math.')}${evidenceRefs.length ? `<div class="small" style="margin-top:4px;">Refs: ${escHtml(evidenceRefs.join(', '))}</div>` : ''}</td>
                <td>${escHtml(why)}</td>
              </tr>`;
            }).join('');
            return `<table>
              <thead><tr><th>DREAD Dimension</th><th>Score</th><th>Evidence used</th><th>Why it matters</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>`;
          }
          const _ATLAS_CATALOG = {
            'AML.T0043':{name:'Craft Adversarial Data',desc:'Attacker creates inputs specifically designed to exploit ML pipeline weaknesses — includes hidden payloads, adversarial typography, or steganographic content that bypasses ML-based content filters.'},
            'AML.T0051':{name:'Prompt Injection',desc:'Malicious instructions embedded in user-controlled content that attempt to override the AI system\\'s intended behaviour, hijack its decisions, or extract sensitive context.'},
            'AML.T0048':{name:'Discover ML Artifacts',desc:'Adversary probes the system to identify ML model endpoints, embedding dimensions, or pipeline configuration to plan a targeted attack.'},
            'AML.T0040':{name:'ML Supply Chain Compromise',desc:'Attack targets ML dependencies, pre-trained model checkpoints, or data pipeline infrastructure to introduce malicious behaviour before deployment.'},
            'AML.T0044':{name:'Full ML Model Access',desc:'Adversary gains complete access to model architecture, weights, and parameters — enabling white-box adversarial attacks.'},
            'AML.T0054':{name:'LLM Jailbreak',desc:'Techniques designed to circumvent safety guidelines or alignment constraints of a large language model.'},
            'AML.T0020':{name:'Poison Training Data',desc:'Training data is corrupted to embed hidden behaviours activated only under specific trigger conditions.'},
            'AML.T0018':{name:'Backdoor ML Model',desc:'Hidden functionality implanted during training that remains dormant until a specific trigger input activates it.'},
            'AML.T0028':{name:'Poison Model',desc:'Post-deployment model compromise through tampered update mechanisms or supply chain infiltration.'},
            'AML.T0041':{name:'Spearphishing via ML Service',desc:'Using AI services as a vector for targeted phishing — the AI system is weaponised or impersonated to deceive users.'},
            'AML.T0034':{name:'Cost Harvesting',desc:'Exploiting AI system computational resources for financial or operational gain.'},
            'AML.T0000':{name:'Reconnaissance',desc:'Adversary gathers information about the AI system\\'s capabilities, endpoints, and configuration before launching an attack.'},
          };
          const _ATTACK_CATALOG = {
            'T1566':{name:'Phishing',desc:'Adversary sends malicious messages to elicit sensitive information or deliver malware.'},
            'T1566.001':{name:'Spearphishing Attachment',desc:'Targeted phishing email carrying a malicious or deceptive attachment intended to deceive a specific individual.'},
            'T1566.002':{name:'Spearphishing Link',desc:'Targeted phishing email containing a malicious or deceptive URL designed to harvest credentials or deliver malware.'},
            'T1534':{name:'Internal Spearphishing',desc:'Phishing messages sent from within the organisation after an internal account has been compromised.'},
            'T1586':{name:'Compromise Accounts',desc:'Adversary compromises legitimate accounts on email or other services for operational use.'},
            'T1589':{name:'Gather Victim Identity Information',desc:'Attacker harvests identity details — names, roles, email addresses — during reconnaissance to craft convincing lures.'},
            'T1598':{name:'Phishing for Information',desc:'Spearphishing campaign aimed at extracting credentials or sensitive operational information rather than delivering malware.'},
            'T1565':{name:'Data Manipulation',desc:'Adversary manipulates data — documents, records, instructions — to influence business processes or decision-making.'},
            'T1199':{name:'Trusted Relationship',desc:'Attacker exploits an existing trusted relationship (vendor, partner, internal employee) to gain access or execute fraud without raising suspicion.'},
            'T1078':{name:'Valid Accounts',desc:'Use of legitimate or stolen credentials to authenticate and operate within the environment without triggering anomaly detection.'},
            'T1204':{name:'User Execution',desc:'Attacker relies on the target user to execute a malicious action — clicking a link, opening an attachment, or following fraudulent payment instructions.'},
            'T1204.001':{name:'Malicious Link',desc:'User is deceived into clicking a link that leads to malicious content, credential harvesting, or a C2 callback.'},
            'T1204.002':{name:'Malicious File',desc:'User is deceived into opening a malicious attachment — may contain macros, tracking beacons, or payload droppers.'},
            'T1036':{name:'Masquerading',desc:'Attacker impersonates a trusted entity — a person, domain, brand, or internal system — to bypass user suspicion.'},
            'T1005':{name:'Data from Local System',desc:'Adversary collects sensitive data stored locally, potentially including cached credentials or financial records.'},
            'T1486':{name:'Data Encrypted for Impact',desc:'Adversary encrypts data on target systems (ransomware) to disrupt availability and extort payment.'},
            'T1071':{name:'Application Layer Protocol',desc:'Adversary uses standard application-layer protocols for C2 or exfiltration to blend with legitimate traffic.'},
            'T1071.003':{name:'Mail Protocols',desc:'Using email protocols (SMTP, IMAP) for command-and-control beaconing or data exfiltration.'},
          };
          const _ISO27001_CATALOG = {
            'A.5.7':{name:'Threat intelligence',why:'This incident should be fed into threat intelligence processes — attacker infrastructure (domain, bank account, PDF tracking beacons) may link to wider campaigns affecting other organisations.'},
            'A.5.8':{name:'Information security in project management',why:'The targeted business process (fund transfer approval) must have security controls embedded. This incident reveals a gap in process-level security for financial approvals.'},
            'A.5.16':{name:'Identity management',why:'The sender claims a trusted internal identity (Boris Petrov, Group Accounts Manager) but this identity was not cryptographically verified before a financial action was requested. Identity management controls must be activated before actioning any payment instruction.'},
            'A.5.17':{name:'Authentication information',why:'Sender authentication signals (SPF/DKIM/DMARC) were absent or failed. The email cannot be tied to the claimed sender domain with confidence. Authentication information management controls must enforce verification before trust is granted.'},
            'A.5.19':{name:'Information security in supplier relationships',why:'A request to change payment arrangements for a named external beneficiary (Harbourside Capital Partners, ANZ BSB 012-456, Account 8877 3421) was received without following the dual-control supplier payment-change verification workflow.'},
            'A.5.21':{name:'Managing information security in the ICT supply chain',why:'A named third-party financial institution appears as payment beneficiary. Changes to authorised payment counterparties require supply chain integrity verification — a baseline comparison against approved supplier records should be performed.'},
            'A.5.23':{name:'Information security for use of cloud services',why:'The email was delivered via external cloud mail infrastructure. Any forensic investigation must follow the organisation\\'s cloud service security controls for data handling, evidence chain-of-custody, and authorised access.'},
            'A.5.24':{name:'Information security incident management planning',why:'This confirmed fraud attempt must be classified and responded to per the documented incident management plan. A formal incident record should be opened immediately.'},
            'A.5.26':{name:'Response to information security incidents',why:'An active fraud incident has been confirmed. Response procedures — evidence preservation, supplier notification, finance team alert, and escalation to management — must be initiated.'},
            'A.5.34':{name:'Privacy and protection of PII',why:'The email contains personally identifiable information (employee name, title, division) that must be handled securely and in accordance with applicable privacy obligations during the investigation.'},
            'A.8.7':{name:'Protection against malware',why:'Attached files (Wire_Transfer_Authorization_Form.pdf) must be scanned or detonated for embedded malware, macro payloads, or tracking beacons before any user interaction. The PDF footer contains suspicious tracking URLs (balashnikovai-analytics.com, balashnikovai-cdn.com).'},
            'A.8.12':{name:'Data leakage prevention',why:'Financial account details (BSB 012-456, Account 8877 3421, SWIFT ANZBAU3M) present in the email and attachment must not be exfiltrated or exposed beyond authorised investigation channels.'},
            'A.8.16':{name:'Monitoring activities',why:'Security monitoring must log and alert on this incident. All triage actions, escalation decisions, hold confirmations, and analyst commentary must be captured in the audit trail.'},
          };
          const _ISO42001_CATALOG = {
            'Human oversight':{name:'Human Oversight (Clause 6.1.2 / Annex A.6)',why:'This fraud verdict was generated by AI-assisted analysis. ISO 42001 requires a human analyst to review, verify, and confirm any high-stakes AI-generated security verdict before a consequential action (payment hold, escalation, supplier notification) is taken.'},
            'Outcome monitoring':{name:'Outcome Monitoring (Clause 9.1)',why:'The accuracy and outcome of this AI fraud verdict must be logged and evaluated. A correct verdict validates model performance; an incorrect one must trigger a corrective feedback cycle to improve the model.'},
            'Risk treatment':{name:'Risk Treatment (Clause 6.1.3)',why:'AI-identified risks must be formally treated — documented with an owner, assigned a risk rating, and mitigated with controls proportionate to business impact.'},
            'Model governance':{name:'Model Governance (Clause 5.2 / Annex A.4)',why:'The AI model that generated this finding must have documented governance: deployment scope, version, training data lineage, and authorised use cases — so the finding can be independently assessed.'},
            'Prompt handling':{name:'Prompt Handling (Annex A.6.2.4)',why:'Controls for AI input integrity are required when user-supplied content (email body, attachments) is processed by AI models. Adversarial prompt injection risk must be mitigated to prevent the AI system\\'s verdict from being manipulated by the email content itself.'},
          };
          const _EU_AI_CATALOG = {
            'Article 9':{name:'Risk Management System',why:'Art. 9 requires high-risk AI applications — including AI-assisted security decisions with financial consequences — to operate under a documented, ongoing risk management system. This incident must be recorded within that system.'},
            'Article 14':{name:'Human Oversight',why:'Art. 14 requires that a natural person can understand, monitor, and where necessary override or halt the AI system\\'s output. This AI verdict must be confirmed by an authorised analyst before any consequential action is taken.'},
            'Article 15':{name:'Accuracy, Robustness and Cybersecurity',why:'Art. 15 requires AI systems to be resilient against adversarial manipulation. This incident tests whether the AI pipeline correctly identifies adversarial email content — if it was deceived, robustness controls must be reviewed and hardened.'},
          };
          const _PCI_DSS_CATALOG = {
            'Req 6':{name:'Develop and Maintain Secure Systems and Software',why:'Payment workflow software must have controls preventing unauthorised payment instruction changes — including input validation and change authorisation. This email attempted to inject fraudulent payment instructions; those controls must be confirmed as active.'},
            'Req 10':{name:'Log and Monitor All Access to System Components',why:'All actions related to this payment-change attempt — receipt, triage, escalation, hold confirmation, and final decision — must be logged with timestamps and actor identities to meet PCI DSS audit trail requirements.'},
            'Req 12':{name:'Support Information Security with Organisational Policies',why:'The organisation\\'s security policy must define the procedure for handling fraudulent payment-change requests, including escalation to finance security, management notification, and external reporting obligations.'},
          };
          const _GDPR_CATALOG = {
            'Article 5':{name:'Principles of Processing',why:'Personal data present in this email (employee name Boris Petrov, role, division, contact address finance@balashnikovai.com.au) must be processed lawfully, fairly, and with appropriate security controls during the investigation.'},
            'Article 32':{name:'Security of Processing',why:'The organisation must implement technical and organisational measures appropriate to the risk. This incident demonstrates the need for email authentication enforcement and dual-control payment verification — these are the measures Article 32 requires.'},
            'Article 33':{name:'Breach Notification',why:'If personal data was or could have been compromised as part of this fraud attempt, the relevant supervisory authority may need to be notified within 72 hours of becoming aware of the breach.'},
          };
          const _PASTA_STAGES = {
            'Stage1':'Stage 1 of 7 — Define Objectives: Identify business objectives and security requirements that must be protected.',
            'DefineObjectives':'Stage 1 of 7 — Define Objectives: Identify business objectives and security requirements that must be protected.',
            'Stage2':'Stage 2 of 7 — Define Technical Scope: Map the attack surface, infrastructure components, data flows, and trust boundaries.',
            'DefineTechnicalScope':'Stage 2 of 7 — Define Technical Scope: Map the attack surface, infrastructure components, data flows, and trust boundaries.',
            'Stage3':'Stage 3 of 7 — Application Decomposition: Analyse internal data flows, user roles, entry points, and system trust boundaries.',
            'ApplicationDecomposition':'Stage 3 of 7 — Application Decomposition: Analyse internal data flows, user roles, entry points, and system trust boundaries.',
            'Stage4':'Stage 4 of 7 — Threat Analysis: Enumerate threat actors and attack vectors against the identified attack surface using threat intelligence.',
            'ThreatAnalysis':'Stage 4 of 7 — Threat Analysis: Enumerate threat actors and attack vectors against the identified attack surface using threat intelligence.',
            'Stage5':'Stage 5 of 7 — Vulnerability & Weakness Analysis: Correlate identified threats to control gaps, known CVEs, and implementation weaknesses.',
            'VulnerabilityAnalysis':'Stage 5 of 7 — Vulnerability & Weakness Analysis: Correlate identified threats to control gaps, known CVEs, and implementation weaknesses.',
            'Stage6':'Stage 6 of 7 — Attack Modelling & Simulation [ACTIVE]: A complete, exploitable attack path has been modelled. Build attack trees and simulate the attack sequence to validate exploitability and confirm that countermeasures will interrupt the kill chain.',
            'ModellingAndSimulation':'Stage 6 of 7 — Attack Modelling & Simulation [ACTIVE]: A complete, exploitable attack path has been modelled. Build attack trees and simulate the attack sequence to validate exploitability and confirm that countermeasures will interrupt the kill chain.',
            'Stage7':'Stage 7 of 7 — Risk & Impact Analysis [ACTIVE]: Quantify the financial and operational business impact. Prioritise and implement countermeasures ordered by risk-reduction value.',
            'RiskAndImpactAnalysis':'Stage 7 of 7 — Risk & Impact Analysis [ACTIVE]: Quantify the financial and operational business impact. Prioritise and implement countermeasures ordered by risk-reduction value.',
          };
          function frameworkExplanation(framework, control, businessOutcome){
            const fw = String(framework || 'Framework').trim();
            const ctl = String(control || '-').trim();
            const upperCtl = ctl.toUpperCase();
            // Auto-correct ATLAS techniques that may be mislabelled as ATT&CK
            const isAtlas = upperCtl.startsWith('AML.');
            const resolvedFw = isAtlas ? 'MITRE ATLAS' : fw;
            const lowerFw = resolvedFw.toLowerCase();
            let displayControl = ctl;
            let what = 'Relevant control or analytic mapping.';
            let why = 'Included because the current evidence maps to this control or technique.';
            let significance = businessOutcome || 'Supports auditability and control justification for the incident.';
            let evidence = 'Mapped from current evidence pack and policy-aligned reasoning.';
            let source = 'Local control catalog';
            if(lowerFw.includes('atlas')){
              const meta = _ATLAS_CATALOG[upperCtl] || null;
              if(meta){
                displayControl = `${ctl} — ${meta.name}`;
                what = `MITRE ATLAS technique: ${meta.name}. ${meta.desc}`;
              } else {
                what = `MITRE ATLAS adversarial ML/AI attack technique. See atlas.mitre.org for the full technique definition.`;
              }
              why = `This ATLAS technique was matched from signals in the email content, metadata, or attachments. MITRE ATLAS documents adversarial attacks targeting AI and ML systems specifically.`;
              evidence = `Signals in the message or attachment evidence mapped to this ATLAS technique via the local threat-model catalog. See the full evidence pack for specific signal matches.`;
              source = 'MITRE ATLAS (atlas.mitre.org)';
              significance = businessOutcome || `Enables analysts to understand how the AI pipeline itself may have been targeted and to hunt for related adversarial activity.`;
            } else if(lowerFw.includes('att&ck') || lowerFw.includes('attack')){
              const meta = _ATTACK_CATALOG[upperCtl] || _ATTACK_CATALOG[ctl] || null;
              if(meta){
                displayControl = `${ctl} — ${meta.name}`;
                what = `MITRE ATT&CK technique: ${meta.name}. ${meta.desc}`;
                why = `The email pattern matches ${meta.name}: ${meta.desc.charAt(0).toLowerCase() + meta.desc.slice(1)}`;
              } else {
                what = `MITRE ATT&CK technique or tactic describing observed adversary behaviour.`;
                why = `The observed signals match a documented ATT&CK technique, enabling threat hunting against known attacker tradecraft.`;
              }
              evidence = `Urgency framing, authority impersonation (Boris Petrov, Group Accounts Manager), payment-change instruction, confidentiality suppression ("DO NOT discuss"), and attachment lure (WTA-2026-0847) map to this technique.`;
              source = 'MITRE ATT&CK (attack.mitre.org)';
              significance = businessOutcome || `Allows analysts to compare this email to known attacker campaigns and hunt for related activity using the ATT&CK navigator.`;
            } else if(lowerFw.includes('pasta')){
              const stageName = ctl.includes(':') ? ctl.split(':').slice(1).join(':') : ctl;
              const stageId = ctl.includes(':') ? ctl.split(':')[0] : '';
              const stageDesc = _PASTA_STAGES[stageName] || _PASTA_STAGES[stageId] || _PASTA_STAGES[ctl] || 'PASTA threat modelling stage active.';
              displayControl = ctl;
              what = `PASTA (Process for Attack Simulation and Threat Analysis) is a 7-stage, risk-centric threat modelling methodology. The active stage reflects how far the attack has progressed. ${stageDesc}`;
              why = `Active signal count, incident severity, kill-chain position, and DREAD weighted score were used to determine the current PASTA stage. Higher stages indicate a more complete and exploitable attack path.`;
              evidence = `Severity level, DREAD average, and active threat signals placed this incident at the determined PASTA stage. See the DREAD Evidence Table for the specific score drivers.`;
              source = 'PASTA Threat Modelling methodology (VerSprite / threat-modeling.com)';
              significance = businessOutcome || `At Stage 6 or 7, the threat has moved beyond theoretical risk — a realistic attack path exists and immediate countermeasures are required.`;
            } else if(lowerFw.includes('iso42001') || lowerFw.includes('iso 42001')){
              const meta = _ISO42001_CATALOG[ctl] || null;
              if(meta){
                displayControl = `${ctl} — ${meta.name}`;
                what = `ISO/IEC 42001:2023 AI Management System: ${meta.name}.`;
                why = meta.why;
              } else {
                what = `ISO/IEC 42001:2023 AI management system control for oversight, monitoring, and accountable AI operations.`;
                why = `The AI-assisted analysis pipeline processed this email and generated a verdict. ISO 42001 controls apply to any AI system contributing to consequential operational decisions.`;
              }
              evidence = `The AI fraud analysis pipeline processed this email, generated a severity verdict, and produced this framework mapping. All three activities are in-scope for ISO 42001 governance.`;
              source = 'ISO/IEC 42001:2023 — Information Technology: Artificial Intelligence Management Systems';
              significance = businessOutcome || `Required to demonstrate that AI-assisted security decisions remain supervised, auditable, and governable under an AI management system.`;
            } else if(lowerFw.includes('eu ai')){
              const meta = _EU_AI_CATALOG[ctl] || null;
              if(meta){
                displayControl = `${ctl} — ${meta.name}`;
                what = `EU AI Act (Regulation EU 2024/1689) obligation: ${meta.name}.`;
                why = meta.why;
              } else {
                what = `EU AI Act governance obligation for oversight, transparency, or accountability.`;
                why = `AI was used to generate or support this security verdict, triggering EU AI Act oversight and transparency obligations.`;
              }
              evidence = `AI-assisted reasoning was applied during triage and scoring of this email. Where AI contributes to operational security decisions with financial consequences, EU AI Act obligations apply.`;
              source = 'EU Artificial Intelligence Act — Regulation (EU) 2024/1689';
              significance = businessOutcome || `Ensures AI-assisted verdicts are transparent, supervised, and challengeable by authorised human reviewers before consequential action is taken.`;
            } else if(lowerFw.includes('pci')){
              const meta = _PCI_DSS_CATALOG[ctl] || null;
              if(meta){
                displayControl = `${ctl} — ${meta.name}`;
                what = `PCI DSS v4.0 requirement: ${meta.name}.`;
                why = meta.why;
              } else {
                what = `PCI DSS requirement relevant to payment-process integrity, logging, or security governance.`;
                why = `The email attempts to influence a payment workflow, triggering PCI DSS controls for payment process integrity and audit.`;
              }
              evidence = `Wire transfer instructions (AUD $85,000, BSB 012-456, SWIFT ANZBAU3M) and the attached form WTA-2026-0847 directly implicate payment workflow integrity. The PDF also contains tracking beacon URLs in the footer.`;
              source = 'PCI DSS v4.0 (PCI Security Standards Council)';
              significance = businessOutcome || `Demonstrates the payment-change request was handled with proper controls, logging, and security governance to protect cardholder data environment integrity.`;
            } else if(lowerFw.includes('gdpr')){
              const meta = _GDPR_CATALOG[ctl] || null;
              if(meta){
                displayControl = `${ctl} — ${meta.name}`;
                what = `GDPR (Regulation EU 2016/679) obligation: ${meta.name}.`;
                why = meta.why;
              } else {
                what = `GDPR principle or article related to secure data processing and integrity.`;
                why = `Personal data is involved in a potentially fraudulent process change and must be handled in accordance with GDPR obligations.`;
              }
              evidence = `The email contains personal data: Boris Petrov (name, role, division, email finance@balashnikovai.com.au). GDPR processing obligations apply to how this data is used during the investigation.`;
              source = 'EU General Data Protection Regulation — GDPR 2016/679';
              significance = businessOutcome || `Demonstrates that personal data involved in this incident was handled lawfully, fairly, and with appropriate security measures.`;
            } else if(lowerFw.includes('iso')){
              const meta = _ISO27001_CATALOG[ctl] || null;
              if(meta){
                displayControl = `${ctl} — ${meta.name}`;
                what = `ISO/IEC 27001:2022 information security control ${ctl}: ${meta.name}.`;
                why = meta.why;
              } else {
                what = `ISO/IEC 27001:2022 information security management control.`;
                why = `This control was triggered because the incident affects the domain covered by this ISO 27001 clause.`;
              }
              evidence = `Supplier identity, payment-change workflow, and sender authentication signals from this email triggered the ISO 27001 mapping. See the signal evidence pack for the specific indicators.`;
              source = 'ISO/IEC 27001:2022 — Information Security Management Systems';
              significance = businessOutcome || `Relevant for auditors and control owners validating that supplier verification, identity management, and incident-response obligations are met.`;
            }
            return { framework: resolvedFw, control: displayControl, what, why, significance, evidence, source };
          }
          function frameworkRowsHtml(rows){
            const items = Array.isArray(rows) ? rows.filter(Boolean) : [];
            if(!items.length) return '<div class="small" style="color:#94a3b8;">No framework mappings were returned.</div>';
            return `<table>
              <thead><tr><th>Framework</th><th>Tag / Control</th><th>Why triggered</th><th>Business impact</th></tr></thead>
              <tbody>${items.map((row, idx) => `<tr>
                <td>${escHtml(row.framework || '')}</td>
                <td>${escHtml(row.control_or_tag || row.control || '')}${row.mapping_confidence ? ` <span class="pill" style="margin-left:6px;">${escHtml(String(row.mapping_confidence))}</span>` : ''}</td>
                <td>${escHtml(row.why_triggered || row.why || '')}</td>
                <td>${escHtml(row.business_significance || row.significance || '')}</td>
              </tr>
              <tr>
                <td colspan="4" style="background:#f8fbff;">
                  <details>
                    <summary>Explain mapping ${idx + 1}</summary>
                    <div style="margin-top:8px;">
                      <div><strong>Canonical name:</strong> ${escHtml(row.canonical_name || row.control_or_tag || row.control || '')}</div>
                      <div style="margin-top:6px;"><strong>What it is:</strong> ${escHtml(row.what || row.canonical_name || row.control_or_tag || '')}</div>
                      <div style="margin-top:6px;"><strong>Evidence refs:</strong> ${escHtml(Array.isArray(row.evidence_refs) ? row.evidence_refs.join(', ') : 'No evidence refs')}</div>
                      <div style="margin-top:6px;"><strong>Evidence used:</strong>${listHtml(Array.isArray(row.evidence_summary) ? row.evidence_summary : (row.evidence ? [row.evidence] : []))}</div>
                      <div style="margin-top:6px;"><strong>Source of mapping:</strong> ${escHtml(row.mapping_source || row.source || '')}</div>
                      <div style="margin-top:6px;"><strong>Version:</strong> ${escHtml(row.mapping_version || '')}${row.rule_id ? ` · ${escHtml(row.rule_id)}` : ''}</div>
                      <div style="margin-top:6px;"><strong>Analyst review required:</strong> ${escHtml(String(row.analyst_review_required !== false))}</div>
                    </div>
                  </details>
                </td>
              </tr>`).join('')}</tbody>
            </table>`;
          }
          function frameworkRowsForFinding(mitre, atlas, pasta, compliance, businessOutcome){
            const rows = [];
            const hasCanonical = Array.isArray(compliance) && compliance.some(item => item && (item.evidence_refs || item.control_or_tag || item.mapping_source));
            if(hasCanonical){
              for(const item of compliance){
                if(!item || (!item.evidence_refs && !item.control_or_tag)) continue;
                const controls = Array.isArray(item.controls) ? item.controls : [item.control_or_tag || item.control || '-'];
                for(const control of controls){
                  rows.push({
                    framework: item.framework,
                    control_or_tag: control,
                    canonical_name: item.canonical_name || control,
                    why_triggered: item.rationale || item.why_triggered || 'Triggered from finding-level evidence.',
                    business_significance: item.business_significance || businessOutcome,
                    evidence_refs: Array.isArray(item.evidence_refs) ? item.evidence_refs : [],
                    evidence_summary: Array.isArray(item.evidence_summary) ? item.evidence_summary : [],
                    mapping_source: item.mapping_source || 'email_security._finding_compliance_mapping',
                    mapping_version: item.mapping_version || '',
                    mapping_confidence: item.mapping_confidence || '',
                    analyst_review_required: item.analyst_review_required !== false,
                    rule_id: item.rule_id || '',
                  });
                }
              }
              if(rows.length) return rows;
            }
            if(pasta) rows.push(frameworkExplanation('PASTA', pasta, businessOutcome));
            for(const tag of (Array.isArray(mitre) ? mitre : [])){
              rows.push(frameworkExplanation('MITRE ATT&CK', tag, businessOutcome));
            }
            for(const tag of (Array.isArray(atlas) ? atlas : [])){
              rows.push(frameworkExplanation('MITRE ATLAS', tag, businessOutcome));
            }
            for(const item of (Array.isArray(compliance) ? compliance : [])){
              const framework = String((item || {}).framework || 'Framework');
              const controls = Array.isArray((item || {}).controls) ? item.controls : [];
              if(!controls.length){
                rows.push(frameworkExplanation(framework, '-', businessOutcome));
              } else {
                for(const control of controls) rows.push(frameworkExplanation(framework, control, businessOutcome));
              }
            }
            return rows;
          }
          function complianceSummaryHtml(securityAnalysis, businessOutcome){
            const frameworks = Array.isArray((((securityAnalysis || {}).compliance || {}).frameworks)) ? (((securityAnalysis || {}).compliance || {}).frameworks) : [];
            const confirmed = Array.isArray(securityAnalysis?.framework_rows) ? securityAnalysis.framework_rows : frameworkRowsForFinding(Array.isArray(securityAnalysis?.mitre_attack) ? securityAnalysis.mitre_attack : [], Array.isArray(securityAnalysis?.mitre_atlas) ? securityAnalysis.mitre_atlas : [], '', frameworks, businessOutcome);
            const possible = Array.isArray(securityAnalysis?.possible_framework_rows) ? securityAnalysis.possible_framework_rows : [];
            return `${frameworkRowsHtml(confirmed)}${possible.length ? `<div style="margin-top:10px;"><div class="section-label">Possible mappings awaiting stronger evidence</div>${frameworkRowsHtml(possible)}</div>` : ''}`;
          }
          function findingProvenanceChips(f){
            if(!f || typeof f !== 'object') return '';
            const chips = [];
            if(f.source_type) chips.push(provenanceChipHtml(f.source_type));
            if(f.evidence_kind) chips.push(`<span class="pill">${escHtml(String(f.evidence_kind))}</span>`);
            if(f.confidence_band) chips.push(`<span class="pill">${escHtml(String(f.confidence_band))} confidence</span>`);
            const ownerScope = (f.linked_artifact && f.linked_artifact.linked_owner_scope) || ((f.retrieval_context || {}).linked_owner_scope);
            if(ownerScope) chips.push(ownerScopeBadgeHtml(ownerScope));
            return chips.join(' ');
          }
          function findingDrilldownHtml(f){
            if(!f || typeof f !== 'object') return '';
            const d = f.drilldown || {};
            const evidence = Array.isArray(f.evidence) ? f.evidence.filter(Boolean) : [];
            const mitre = Array.isArray(f.mitre_attack) && f.mitre_attack.length ? f.mitre_attack : (Array.isArray(((f.threat_context||{}).mitre_attack)) ? (f.threat_context||{}).mitre_attack : []);
            const atlasRefs = Array.isArray(f.evidence_refs) ? f.evidence_refs : [];
            const atlasAllowed = atlasRefs.some(ref => /prompt|agent|model|atlas/i.test(String(ref || '')));
            const atlas = atlasAllowed ? (Array.isArray(f.mitre_atlas) && f.mitre_atlas.length ? f.mitre_atlas : (Array.isArray(((f.threat_context||{}).mitre_atlas)) ? (f.threat_context||{}).mitre_atlas : [])) : [];
            const comp = Array.isArray(f.compliance_mapping) ? f.compliance_mapping : [];
            const pasta = String(f.pasta_stage || ((f.threat_context||{}).pasta_stage || '')).trim();
            const dread = (f.threat_context || {}).dread || {};
            const businessOutcome = String(f.business_outcome || d.business_risk || '').trim();
            const claimStatus = String(f.claim_status || '').trim().toLowerCase();
            const findingGroup = String(f.finding_group || '').trim().toLowerCase();
            const frameworkRows = (claimStatus === 'suppressed' || findingGroup === 'detection_artifact_patterns')
              ? []
              : frameworkRowsForFinding(mitre, atlas, pasta, comp, businessOutcome || findingToPlainEnglish(f));
            const linkedArtifact = f.linked_artifact && typeof f.linked_artifact === 'object' ? f.linked_artifact : {};
            const ownerScope = String(linkedArtifact.linked_owner_scope || ((f.retrieval_context||{}).linked_owner_scope || '')).trim();
            const ownerReason = String(linkedArtifact.linked_owner_reason || '').trim();
            const exposureScope = String(linkedArtifact.linked_exposure_scope || ((f.retrieval_context||{}).linked_exposure_scope || '')).trim();
            const severityHint = String(linkedArtifact.linked_breach_severity_hint || ((f.retrieval_context||{}).linked_breach_severity_hint || '')).trim();
            const provenanceRows = Array.isArray(f.artifact_provenance) ? f.artifact_provenance : [];
            const evidencePosture = [
              claimStatus ? `Claim status: ${escHtml(claimStatus)}` : null,
              findingGroup ? `Finding group: ${escHtml(findingGroup.replaceAll('_', ' '))}` : null,
              `Observed evidence: ${escHtml(String(f.evidence_kind || 'inferred'))}`,
              `Source: ${escHtml(String(f.source_type || 'policy'))}`,
              f.finding_category ? `Classification: ${escHtml(String(f.finding_category).replaceAll('_', ' '))}` : null
            ].filter(Boolean);
            const blocks = [
              `<div><strong>What we found:</strong> ${escHtml(findingToPlainEnglish(f))}</div>`,
              businessOutcome ? `<div><strong>Why it matters:</strong> ${escHtml(businessOutcome)}</div>` : '',
              (claimStatus === 'possible' || (Array.isArray(f.runtime_evidence_required) && f.runtime_evidence_required.length))
                ? `<div><strong>Why this is not confirmed:</strong> Passive evidence only. Runtime confirmation is still required, and no process-tree/network evidence has been observed yet for this claim.</div>`
                : '',
              evidence.length ? `<div><strong>Evidence:</strong>${listHtml(evidence)}</div>` : '',
              Array.isArray(f.next_steps) && f.next_steps.length ? `<div><strong>What to investigate next:</strong>${listHtml(f.next_steps)}</div>` : (Array.isArray(d.forensic_checks) && d.forensic_checks.length ? `<div><strong>What to investigate next:</strong>${listHtml(d.forensic_checks)}</div>` : ''),
              d.affected_scope ? `<div><strong>Affected scope:</strong> ${escHtml(d.affected_scope)}</div>` : '',
              Array.isArray(d.privacy_scope) && d.privacy_scope.length ? `<div><strong>Privacy scope:</strong>${listHtml(d.privacy_scope)}</div>` : '',
              Array.isArray(d.human_verification) && d.human_verification.length ? `<div><strong>Human verification:</strong>${listHtml(d.human_verification)}</div>` : '',
              ownerScope ? `<div><strong>Owner scope:</strong> ${ownerScopeBadgeHtml(ownerScope)}${ownerReason ? ` <span class="small" style="color:#64748b;">${escHtml(ownerReason)}</span>` : ''}</div>` : '',
              exposureScope ? `<div><strong>Exposure scope:</strong> ${escHtml(exposureScope.replaceAll('_', ' '))}</div>` : '',
              severityHint ? `<div><strong>Severity hint:</strong> ${escHtml(severityHint)}</div>` : '',
              evidencePosture.length ? `<div><strong>Evidence posture:</strong>${listHtml(evidencePosture)}</div>` : '',
              atlasRefs.length ? `<div><strong>Evidence refs:</strong>${listHtml(atlasRefs)}</div>` : '',
              provenanceRows.length ? `<div><strong>Artifact provenance:</strong>${listHtml(provenanceRows.map(row => `${row.source_file || 'artifact'} • ${row.extraction_method || 'extraction'} • ${row.match_ref || 'match'} • ${row.confidence || 'unknown'} confidence${row.reason ? ' • ' + row.reason : ''}`))}</div>` : '',
              frameworkRows.length ? `<div><strong>Framework mapping:</strong>${frameworkRowsHtml(frameworkRows)}</div>` : '',
              dread.damage!=null ? `<div><strong>DREAD scoring evidence:</strong>${dreadEvidenceTableHtml(dread, businessOutcome || 'Explains why this finding was treated as materially risky.')}</div>` : ''
            ].filter(Boolean);
            const rawBlocks = [
              Array.isArray(d.hunt_queries) && d.hunt_queries.length ? `<div><strong>Threat hunting:</strong>${listHtml(d.hunt_queries)}</div>` : '',
              Array.isArray(d.crisis_actions) && d.crisis_actions.length ? `<div><strong>Crisis / comms:</strong>${listHtml(d.crisis_actions)}</div>` : '',
              `<div><strong>Raw technical detail:</strong> ${escHtml(findingContextLine(f) || 'Additional technical context available.')}</div>`
            ].filter(Boolean);
            if(!blocks.length && !rawBlocks.length) return '';
            return `<details class="finding-drilldown"><summary>Drill down</summary><div class="finding-drilldown-body">${blocks.join('')}${rawBlocks.length ? `<details style="margin-top:8px;"><summary>Raw technical detail</summary><div style="margin-top:8px;">${rawBlocks.join('')}</div></details>` : ''}</div></details>`;
          }
          function rankedEvidenceHtml(findings){
            const items = Array.isArray(findings) ? findings.filter(Boolean) : [];
            if(!items.length){
              return '<div class="small" style="color:#94a3b8;">No ranked evidence available yet.</div>';
            }
            return items.map(f => {
              const chips = findingProvenanceChips(f);
              const context = findingContextLine(f);
              return `<div class="attachment-row">
                <div style="font-weight:600; color:#0f172a;">${escHtml(findingToPlainEnglish(f))}</div>
                ${chips ? `<div class="row" style="margin-top:6px; gap:6px; flex-wrap:wrap;">${chips}</div>` : ''}
                ${context ? `<div class="small" style="margin-top:6px; color:#64748b;">${escHtml(context)}</div>` : ''}
                ${findingDrilldownHtml(f)}
              </div>`;
            }).join('');
          }
          function threatHunterLeadHtml(lead){
            if(!lead || typeof lead !== 'object') return '';
            const stage = String(lead.likely_kill_chain_stage || '').trim();
            const targetChecklists = lead.target_checklists && typeof lead.target_checklists === 'object' ? lead.target_checklists : {};
            const body = [
              Array.isArray(lead.what_we_observed) && lead.what_we_observed.length ? `<div><strong>What we found:</strong>${listHtml(lead.what_we_observed)}</div>` : '',
              lead.why_it_matters ? `<div><strong>Why it matters:</strong> ${escHtml(String(lead.why_it_matters))}</div>` : '',
              Array.isArray(lead.what_to_hunt_next) && lead.what_to_hunt_next.length ? `<div><strong>What to check next:</strong>${listHtml(lead.what_to_hunt_next)}</div>` : '',
              Array.isArray(lead.confirmation_signals) && lead.confirmation_signals.length ? `<div><strong>What would confirm it:</strong>${listHtml(lead.confirmation_signals)}</div>` : '',
              Array.isArray(lead.disproving_signals) && lead.disproving_signals.length ? `<div><strong>What would weaken it:</strong>${listHtml(lead.disproving_signals)}</div>` : '',
              Array.isArray(lead.where_to_check) && lead.where_to_check.length ? `<div><strong>Where to check:</strong>${listHtml(lead.where_to_check)}</div>` : '',
              Array.isArray(lead.push_downstream) && lead.push_downstream.length ? `<div><strong>What to push downstream:</strong>${listHtml(lead.push_downstream)}</div>` : '',
              lead.analyst_guidance ? `<div><strong>Analyst guidance:</strong> ${escHtml(String(lead.analyst_guidance))}</div>` : ''
            ].filter(Boolean);
            const checklistHtml = Object.keys(targetChecklists).length
              ? `<details style="margin-top:8px;"><summary>Target-specific hunt checklist</summary><div style="margin-top:8px;">${Object.entries(targetChecklists).map(([target, checks]) => `<div style="margin-bottom:8px;"><strong>${escHtml(String(target))}:</strong>${listHtml(Array.isArray(checks) ? checks : [])}</div>`).join('')}</div></details>`
              : '';
            const technical = [
              stage ? `Likely next stage: ${stage}` : null,
              Array.isArray(lead.evidence_refs) && lead.evidence_refs.length ? `Evidence refs: ${lead.evidence_refs.join(', ')}` : null,
              lead.business_guidance ? `Scope note: ${lead.business_guidance}` : null
            ].filter(Boolean);
            return `<details class="finding-drilldown"><summary>${escHtml(String(lead.title || 'Threat hunter lead'))} <span class="pill">${escHtml(String(lead.confidence_band || 'medium'))} confidence</span></summary><div class="finding-drilldown-body"><div style="margin-bottom:8px;"><button class="btn" type="button" onclick="runThreatHunt()" style="border-color:#f59e0b;background:linear-gradient(180deg,#fff7ed,#ffedd5);color:#9a3412;font-weight:700;">Open Hunt Investigation</button><span class="small" style="margin-left:8px;">Human-gated new tab using the current case evidence.</span></div>${body.join('')}${checklistHtml}${technical.length ? `<details style="margin-top:8px;"><summary>Raw technical detail</summary><div style="margin-top:8px;">${listHtml(technical)}</div></details>` : ''}</div></details>`;
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
            const ap = ev.action_policy || j.action_policy || {};
            const hg = ev.human_gate || j.human_gate || ap.human_gate || {};
            const ranked = Array.isArray(ev.top_ranked_findings) ? ev.top_ranked_findings : (Array.isArray(card.top_ranked_findings) ? card.top_ranked_findings : []);
            const why = ranked.length
              ? ranked.map(f => findingToPlainEnglish(f))
              : (Array.isArray(card.why_flagged) ? card.why_flagged.map(reasonToPlainEnglish) : (j.reasons||[]).map(reasonToPlainEnglish));
            const decision = `${String(j.risk_band || 'medium').replaceAll('_', ' ')} confidence · ${String(ap.lane_label || ap.lane || 'auto escalated').replaceAll('_', ' ')}`;
            let what = 'Security review required.';
            if(why.some(item => /bank|payment|remittance/i.test(item))) what = 'Likely supplier payment fraud.';
            else if(why.some(item => /supplier|baseline|document/i.test(item))) what = 'Likely supplier impersonation or supplier document fraud.';
            else if(why.some(item => /sender|reply|auth|dmarc/i.test(item))) what = 'Likely sender trust or supplier identity issue.';
            const immediate = [
              'Do not pay',
              'Verify supplier via approved contact',
              'Quarantine and notify finance/security'
            ];
            const next = [];
            if(hg.business_hold_message) next.push(hg.business_hold_message);
            else if(Array.isArray(ap.human_approval_actions) && ap.human_approval_actions.length) next.push('Approval required before accepting new bank details or supplier trust changes.');
            else next.push('No extra approval is required before routine evidence review.');
            return {
              what: `${what} ${decision}`.trim(),
              why,
              impact: severityToBusinessRisk(j, thr),
              immediate,
              next: Array.from(new Set(next)).slice(0, 3),
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
          function updateRailLayout(){
            const rail = document.getElementById('right_rail');
            if(!rail) return;
            rail.classList.toggle('wide', rail.clientWidth >= 760);
          }
          function renderEvidenceSummary(j){
            const ev = j.evidence_snapshot || {};
            const atts = Array.isArray(ev.attachment_forensics) ? ev.attachment_forensics : [];
            const ranked = Array.isArray(ev.top_ranked_findings) ? ev.top_ranked_findings : [];
            const structured = Array.isArray(ev.structured_findings) ? ev.structured_findings : [];
            const grouped = ev.finding_groups && typeof ev.finding_groups === 'object' ? ev.finding_groups : {};
            const gate = ev.pre_agent_gate || {};
            const agentRuns = Array.isArray(ev.agent_runs) ? ev.agent_runs : [];
            const hunterLeads = Array.isArray(ev.threat_hunter_leads) ? ev.threat_hunter_leads : [];
            const sa = (j.security_analysis && typeof j.security_analysis === 'object') ? j.security_analysis : {};
            const qrSan = (ev.ocr_qr_sanitization && typeof ev.ocr_qr_sanitization === 'object') ? ev.ocr_qr_sanitization : {};
            const businessOutcome = String(j.business_risk || j.summary || j.reason || 'Supports auditability, investigation quality, and business-safe response decisions.').trim();
            const sections = [];
            const facts = [];
            const evidenceQuality = sa.evidence_quality && typeof sa.evidence_quality === 'object' ? sa.evidence_quality : {};
            facts.push(`Evidence quality: ${String(evidenceQuality.label || evidenceQuality.band || 'Not available')}`);
            if(evidenceQuality.ocr_confidence!=null) facts.push(`OCR confidence: ${Number(evidenceQuality.ocr_confidence).toFixed(2)}`);
            else if(qrSan.ocr_confidence!=null) facts.push(`OCR confidence: ${Number(qrSan.ocr_confidence).toFixed(2)}`);
            if(qrSan.ocr_engine || sa.ocr_engine) facts.push(`OCR engine: ${String(qrSan.ocr_engine || sa.ocr_engine)}`);
            if(qrSan.ocr_word_count!=null || sa.ocr_word_count!=null) facts.push(`OCR word count: ${String(qrSan.ocr_word_count ?? sa.ocr_word_count)}`);
            if(Array.isArray(sa.runtime_evidence_present) && sa.runtime_evidence_present.length) facts.push(`Runtime evidence present: ${sa.runtime_evidence_present.join(', ')}`);
            if(Array.isArray(sa.runtime_evidence_required) && sa.runtime_evidence_required.length) facts.push(`Runtime evidence still required: ${sa.runtime_evidence_required.join(', ')}`);
            if(atts.length){
              facts.push(...atts.slice(0,4).map(item => {
                const labels = [];
                if(item.attachment_class) labels.push(String(item.attachment_class).replaceAll('_',' '));
                if(item.supports_sender_claim === false || (Array.isArray(item.brand_supplier_mismatch_signals) && item.brand_supplier_mismatch_signals.length)) labels.push('baseline drift');
                if(item.bank_fields_present || (Array.isArray(item.suspicious_instructions) && item.suspicious_instructions.some(x => /bank|payment|remittance/i.test(String(x||''))))) labels.push('bank change');
                if(Array.isArray(item.embedded_urls) && item.embedded_urls.length) labels.push('QR or URL');
                if((item.steg && item.steg.suspicious) || (Array.isArray(item.evidence_excerpt_lines) && item.evidence_excerpt_lines.some(x => /hidden|steg|prompt|beacon|exfil/i.test(String(x||''))))) labels.push('hidden payload');
                if(!labels.length) labels.push('review required');
                return `${item.file_name || 'attachment'}: ${Array.from(new Set(labels)).join(', ')}`;
              }));
            }
            sections.push(`<div class="evidence-block"><div class="section-label">Facts</div>${listHtml(facts)}</div>`);
            sections.push(`<div class="evidence-block"><div class="section-label">Derived Findings / Top Ranked Evidence</div>${rankedEvidenceHtml(ranked)}</div>`);
            const findingGroupHtml = (title, items, statusTone) => {
              const arr = Array.isArray(items) ? items.filter(Boolean) : [];
              if(!arr.length) return '';
              return `<div class="evidence-block"><div class="section-label">${escHtml(title)}</div>${arr.slice(0,4).map(f => {
                const tone = statusTone === 'warn'
                  ? "background:#fff7ed;border:1px solid #fdba74;color:#9a3412;"
                  : statusTone === 'muted'
                    ? "background:#f8fafc;border:1px solid #cbd5e1;color:#475569;"
                    : "background:#ecfeff;border:1px solid #67e8f9;color:#155e75;";
                const refs = Array.isArray(f.evidence_refs) && f.evidence_refs.length ? `<div class="small" style="margin-top:6px;color:#64748b;">Refs: ${escHtml(f.evidence_refs.join(', '))}</div>` : '';
                return `<div class="attachment-row"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;"><div style="font-weight:600;color:#0f172a;">${escHtml(findingToPlainEnglish(f))}</div><span class="pill" style="${tone}">${escHtml(String(f.claim_status || 'inferred'))}</span></div>${refs}${findingDrilldownHtml(f)}</div>`;
              }).join('')}</div>`;
            };
            sections.push(findingGroupHtml('Active Findings', grouped.active_findings || structured.filter(f => String((f||{}).finding_group||'') === 'active_findings' && ['observed','inferred'].includes(String((f||{}).claim_status||''))), 'info'));
            sections.push(findingGroupHtml('Detection Artifact Patterns', grouped.detection_artifact_patterns || structured.filter(f => String((f||{}).finding_group||'') === 'detection_artifact_patterns'), 'muted'));
            sections.push(findingGroupHtml('Unconfirmed Higher-Order Hypotheses', grouped.unconfirmed_higher_order_hypotheses || structured.filter(f => String((f||{}).finding_group||'') === 'unconfirmed_higher_order_hypotheses'), 'warn'));
            const suppressedFrameworkRows = Array.isArray(sa.suppressed_framework_rows) ? sa.suppressed_framework_rows : [];
            sections.push(`<div class="evidence-block"><div class="section-label">Framework Mappings</div>${complianceSummaryHtml(sa, businessOutcome)}${suppressedFrameworkRows.length ? `<details style="margin-top:8px;"><summary>Suppressed framework rows pending evidence</summary><div style="margin-top:8px;">${listHtml(suppressedFrameworkRows.slice(0,8).map(row => `${row.framework || 'Framework'} ${row.control_or_tag || row.control || '-'} • ${row.suppressed_reason || 'suppressed'}`))}</div></details>` : ''}</div>`);
            const byAgent = {};
            for(const finding of structured){
              const agent = String((finding || {}).agent_origin || '').trim();
              if(!agent) continue;
              if(!byAgent[agent]) byAgent[agent] = [];
              byAgent[agent].push(finding);
            }
            const agentEvidenceBuckets = (agentName) => {
              const items = Array.isArray(byAgent[agentName]) ? byAgent[agentName] : [];
              const direct = items.filter(f => String((f||{}).evidence_kind || '') === 'direct').slice(0, 2).map(f => findingToPlainEnglish(f)).filter(Boolean);
              const inferred = items.filter(f => String((f||{}).evidence_kind || '') !== 'direct' && !['contextual_test_artifact','reference_spec_material','benign_reference_material'].includes(String((f||{}).finding_category || ''))).slice(0, 1).map(f => findingToPlainEnglish(f)).filter(Boolean);
              const contextual = items.filter(f => ['contextual_test_artifact','reference_spec_material','benign_reference_material'].includes(String((f||{}).finding_category || ''))).slice(0, 1).map(f => findingToPlainEnglish(f)).filter(Boolean);
              return { direct, inferred, contextual };
            };
            const verdictImpactHtml = (impact) => {
              const normalized = String(impact || '').trim().toLowerCase();
              if(normalized === 'material') return `<span class="pill" style="background:#fee2e2;color:#991b1b;border-color:#fecaca;">Verdict impact: material</span>`;
              if(normalized === 'supporting') return `<span class="pill" style="background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe;">Verdict impact: supporting</span>`;
              return `<span class="pill" style="background:#f8fafc;color:#475569;border-color:#cbd5e1;">Verdict impact: context only</span>`;
            };
            const agentSummaryHtml = agentRuns.map(r => {
              const agentName = String(r.agent_name || 'agent');
              const labelMap = {
                sender_auth_agent: 'Sender/Auth Agent',
                attachment_forensics_agent: 'Attachment Agent',
                baseline_agent: 'Baseline Agent',
                correlation_agent: 'Correlation Agent',
                explanation_agent: 'Explanation Agent',
                playbook_agent: 'Playbook Agent',
                threat_hunter_agent: 'Threat Hunter Agent'
              };
              const label = labelMap[agentName] || String(agentName).replaceAll('_', ' ');
              const buckets = agentEvidenceBuckets(agentName);
              let directText = buckets.direct[0] || '';
              let inferredText = buckets.inferred[0] || '';
              let contextualText = buckets.contextual[0] || '';
              let impact = 'supporting';
              let inspected = 'Evidence and policy-aligned context relevant to the current email.';
              let playbookName = '';
              let playbookActions = [];
              let contribution = 'Supporting evidence only.';
              if(agentName === 'sender_auth_agent'){
                directText = directText || 'Checked sender identity, reply behavior, and message hygiene against a normal supplier pattern.';
                inferredText = inferredText || 'Suggested a spoof narrative only where sender trust signals were inconsistent.';
                inspected = 'Sender address, reply behavior, auth alignment, and message hygiene.';
                contribution = 'Contributed sender-trust and impersonation evidence.';
                impact = directText ? 'material' : 'supporting';
              } else if(agentName === 'attachment_forensics_agent'){
                directText = directText || 'Looked for direct payment changes, hidden content, and risky instructions in the attachments.';
                inferredText = inferredText || 'Only widened the story when extracted content supported a payment or lure hypothesis.';
                inspected = 'OCR text, filenames, attachment text, embedded URLs, and hidden payload signals.';
                contribution = 'Contributed attachment-derived payment, macro, and hidden-payload evidence.';
                impact = directText ? 'material' : 'supporting';
              } else if(agentName === 'baseline_agent'){
                directText = directText || 'Compared the files against known-good supplier layout, logo, and bank-reference expectations.';
                inferredText = inferredText || 'Raised document-drift meaning only where baseline mismatch was actually observed.';
                inspected = 'Supplier baseline templates, visual layout, remittance expectations, and brand cues.';
                contribution = 'Contributed supplier baseline drift and template mismatch evidence.';
                impact = directText ? 'material' : 'supporting';
              } else if(agentName === 'correlation_agent'){
                directText = directText || 'Correlated observed sender and artifact signals against related incidents and infrastructure.';
                inferredText = inferredText || 'Only widened campaign scope when overlap was supported by sender or infrastructure evidence.';
                inspected = 'Related incidents, sender infrastructure, and overlapping supplier or artifact signals.';
                contribution = 'Contributed overlap and campaign-correlation evidence.';
                impact = inferredText ? 'material' : 'supporting';
              } else if(agentName === 'explanation_agent'){
                directText = directText || 'Turned the strongest evidence into plain-English business outcomes and next steps.';
                inferredText = inferredText || 'Separated direct evidence, inferred meaning, and contextual material to reduce noise.';
                inspected = 'Top-ranked evidence, business outcome mapping, and human next-step framing.';
                contribution = 'Did not add new evidence; reframed existing evidence for operator use.';
                impact = 'supporting';
              } else if(agentName === 'playbook_agent'){
                const pb = ev.playbook_run || j.playbook_run || j.playbook || {};
                playbookName = String(pb.playbook_id || pb.title || pb.id || 'Supplier Payment Change Verification');
                playbookActions = Array.isArray(pb.actions_completed) ? pb.actions_completed : (Array.isArray(pb.actions) ? pb.actions : ['hold_payment', 'verify_supplier_via_trusted_contact', 'notify_finance_security']);
                directText = directText || `Selected playbook: ${playbookName}.`;
                inferredText = inferredText || 'Only added hunting or response guidance when the evidence justified it.';
                inspected = 'Current verdict, action policy, business workflow, and allowed downstream actions.';
                contextualText = `Would run actions: ${playbookActions.slice(0,4).map(a => String(a).replaceAll('_',' ')).join(', ')}.`;
                contribution = `Selected playbook ${playbookName} and translated evidence into response actions.`;
                impact = 'supporting';
              }
              if(!contextualText) contextualText = 'No context-only material was used as primary evidence.';
              const drilldownBody = [];
              drilldownBody.push(`<div><strong>Inspected:</strong> ${escHtml(inspected)}</div>`);
              drilldownBody.push(`<div><strong>Contribution:</strong> ${escHtml(contribution)}</div>`);
              if(buckets.direct.length > 1) drilldownBody.push(`Additional direct evidence:${listHtml(buckets.direct.slice(1))}`);
              if(buckets.inferred.length > 1) drilldownBody.push(`Additional inferred meaning:${listHtml(buckets.inferred.slice(1))}`);
              if(buckets.contextual.length > 1) drilldownBody.push(`Additional context-only items:${listHtml(buckets.contextual.slice(1))}`);
              if(playbookName){
                drilldownBody.push(`<div><strong>Playbook actions:</strong>${listHtml(playbookActions.slice(0,6).map(a => String(a).replaceAll('_',' ')))}</div>`);
              }
              return `<div class="finding-drilldown-body" style="margin-bottom:10px; border:1px solid rgba(148,163,184,0.16); border-radius:12px; padding:10px;">
                <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:6px;"><div style="font-weight:600;">${escHtml(label)}</div>${verdictImpactHtml(impact)}</div>
                <div><strong>Input seen:</strong> ${escHtml(inspected)}</div>
                <div><strong>Direct:</strong> ${escHtml(directText)}</div>
                <div><strong>Inferred:</strong> ${escHtml(inferredText || 'No extra inferred meaning was needed beyond the direct evidence.')}</div>
                <div><strong>Verdict effect:</strong> ${escHtml(impact)}</div>
                <div><strong>Context only:</strong> ${escHtml(contextualText)}</div>
                ${drilldownBody.length ? `<details style="margin-top:8px;"><summary>Drill down</summary><div style="margin-top:8px;">${drilldownBody.join('')}</div></details>` : ''}
              </div>`;
            });
            if(hunterLeads.length){
              const firstLead = hunterLeads[0] || {};
              agentSummaryHtml.push(`<div class="finding-drilldown-body" style="margin-bottom:10px; border:1px solid rgba(148,163,184,0.16); border-radius:12px; padding:10px;">
                <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:6px;"><div style="font-weight:600;">Threat Hunter Agent</div>${verdictImpactHtml('supporting')}</div>
                <div><strong>Input seen:</strong> Related incidents, overlapping infrastructure, supplier context, and bounded hunt pivots.</div>
                <div><strong>Direct:</strong> ${escHtml(Array.isArray(firstLead.what_we_observed) && firstLead.what_we_observed.length ? firstLead.what_we_observed[0] : 'No direct artifact or infrastructure lead was strong enough to widen the hunt.')}</div>
                <div><strong>Inferred:</strong> ${escHtml(firstLead.why_it_matters || 'Used only evidence-backed overlap to suggest likely next checks.')}</div>
                <div><strong>Verdict effect:</strong> supporting</div>
                <div><strong>Context only:</strong> ${escHtml('Did not widen the hunt based on contextual guides, specs, or generator files alone.')}</div>
                <div class="small" style="margin-top:6px;color:#64748b;">Passive evidence only. Runtime confirmation is still required, and no process-tree/network evidence has been observed yet for execution or C2 hypotheses.</div>
                <details style="margin-top:8px;"><summary>Drill down</summary><div style="margin-top:8px;">${hunterLeads.slice(0,3).map(threatHunterLeadHtml).join('')}</div></details>
              </div>`);
            }
            sections.push(`<div class="evidence-block"><div class="section-label">Audit / What Agents Found</div>${agentSummaryHtml.length ? agentSummaryHtml.join('') : '<div class="small" style="color:#94a3b8;">5 agents completed successfully.</div>'}${(gate.artifact_text_untrusted || gate.ocr_text_sanitized || agentRuns.length) ? `<details style="margin-top:8px;"><summary>Agent audit</summary><div style="margin-top:8px;">${listHtml([
              gate.artifact_text_untrusted ? 'Attachment and OCR text were treated as untrusted before model-facing analysis.' : null,
              gate.ocr_text_sanitized ? 'OCR and extracted text were sanitized before explanation and reasoning.' : null,
              gate.blocked_attachment_count!=null ? `Blocked attachments before model access: ${gate.blocked_attachment_count}` : null,
              gate.blocked_qr_url_count!=null ? `Blocked QR URLs before model access: ${gate.blocked_qr_url_count}` : null,
              Array.isArray(gate.blocked_tool_intents) && gate.blocked_tool_intents.length ? `Blocked tool intents: ${gate.blocked_tool_intents.join(', ')}` : null,
              agentRuns.length ? `Scoped agents executed: ${agentRuns.map(r => r.agent_name).join(', ')}` : null
            ])}</div></details>` : ''}</div>`);
            if(hunterLeads.length){
              sections.push(`<div class="evidence-block"><div class="section-label">Audit - Threat Hunter Leads</div>${hunterLeads.slice(0,3).map(threatHunterLeadHtml).join('')}</div>`);
            }
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
            const hunterLeads = Array.isArray(ev.threat_hunter_leads) ? ev.threat_hunter_leads : [];
            const immediate = [
              'Do not pay',
              'Verify supplier via approved contact',
              'Quarantine and notify finance/security'
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
            const hunterSummary = hunterLeads.slice(0, 3).map(lead => `${String(lead.title || 'Threat hunter lead')}: ${Array.isArray(lead.what_to_hunt_next) ? lead.what_to_hunt_next[0] : ''}`).filter(Boolean);
            const gating = [
              ap.lane ? `${String(ap.lane_label || ap.lane).replaceAll('_',' ')}` : null,
              hg.business_hold_message ? hg.business_hold_message : null,
              Array.isArray(ap.human_approval_actions) && ap.human_approval_actions.length ? 'Approval required before accepting new bank details or supplier trust changes.' : null
            ];
            const html = [
              `<div class="evidence-block"><div class="section-label">Human Gate Thresholds</div>${listHtml(gating)}</div>`,
              `<div class="evidence-block"><div class="section-label">Do This Now</div>${listHtml(immediate)}</div>`,
              `<details class="evidence-block" style="display:block;"><summary>Finance and business actions</summary><div style="margin-top:8px;">${listHtml(owner)}</div></details>`,
              `<details class="evidence-block" style="display:block;"><summary>SOC actions</summary><div style="margin-top:8px;">${listHtml([
                ...Array.from(new Set(analyst)).slice(0,8),
                ...recovery,
                Array.isArray(ap.threshold_reasons) && ap.threshold_reasons.length ? `Threshold reasons: ${ap.threshold_reasons.join(' | ')}` : null,
                Array.isArray(ap.auto_allowed_actions) && ap.auto_allowed_actions.length ? `Auto-allowed: ${ap.auto_allowed_actions.join(', ')}` : null,
                Array.isArray(ap.human_approval_actions) && ap.human_approval_actions.length ? `Human approval required: ${ap.human_approval_actions.join(', ')}` : null,
                Array.isArray(ap.blocked_actions) && ap.blocked_actions.length ? `Blocked by policy: ${ap.blocked_actions.join(', ')}` : null
              ])}</div></details>`,
              hunterLeads.length ? `<details class="evidence-block" style="display:block;"><summary>Threat hunter leads</summary><div style="margin-top:8px;">${listHtml(hunterSummary)}${hunterLeads.slice(0,3).map(threatHunterLeadHtml).join('')}</div></details>` : ''
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
            const summary = [
              rel.count ? `${rel.count} related incidents found` : 'No related incidents found',
              infra.reply_domain_mismatch ? 'Sender trust looks inconsistent with normal supplier behavior.' : null,
              hf.message_id_domain_mismatch ? 'Message-ID domain does not match the sender domain.' : null,
            ];
            const relatedHtml = Array.isArray(rel.matches) && rel.matches.length
              ? `<div class="evidence-block"><div class="section-label">Related Incidents</div>${listHtml(rel.matches.map(m => `${m.incident_id} (${m.severity || 'unknown'}) via ${(m.match_on || []).join(', ')}`))}</div>`
              : '';
            document.getElementById('infra_card').style.display = 'block';
            document.getElementById('infra_sections').innerHTML = `<div class="evidence-block"><div class="section-label">Related Incidents</div>${listHtml(summary)}</div>${relatedHtml}<details class="evidence-block" style="display:block;"><summary>Sender and infrastructure detail</summary><div style="margin-top:8px;">${listHtml([
              infra.sender_address ? `Sender: ${infra.sender_address}` : null,
              infra.reply_to ? `Reply-To: ${infra.reply_to}` : null,
              infra.originating_ip ? `Originating IP: ${infra.originating_ip}` : null,
              geo.country ? `GeoIP country: ${geo.country}` : null,
              geo.asn ? `ASN: ${geo.asn}${geo.asn_org ? ` (${geo.asn_org})` : ''}` : null,
              infra.reputation && infra.reputation.risk_score!=null ? `Infrastructure risk score: ${infra.reputation.risk_score}` : null,
              Array.isArray(infra.reputation?.flags) && infra.reputation.flags.length ? `Reputation flags: ${infra.reputation.flags.join(', ')}` : null,
              hf.mailer_fingerprint ? `Mailer fingerprint: ${hf.mailer_fingerprint}` : null,
              hf.message_id_reuse ? 'Message-ID reuse was detected.' : null
            ])}</div></details>`;
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
              document.getElementById('status').textContent = 'Replaying SIEM/XDR handoff...';
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
              document.getElementById('status').textContent = 'Recording analyst outcome...';
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
            const reliability = hc.reliability || {};
            const byTarget = Array.isArray(reliability.by_target) ? reliability.by_target : [];
            const dlqItems = Array.isArray(((hc.dlq || {}).items)) ? (hc.dlq || {}).items : [];
            const shouldPush = !!(j.route === 'security_review' || j.severity === 'error' || (Array.isArray(st.failed) && st.failed.length));
            const shouldHold = Array.isArray((j.action_policy || {}).human_approval_actions) && (j.action_policy || {}).human_approval_actions.length > 0;
            const shouldRouteMail = !!(Array.isArray(j.reasons) && j.reasons.some(r => /auth|reply|spoof|supplier|bimi|dmarc/i.test(String(r || ''))));
            const pushBadge = shouldHold
              ? `<span class='pill' style='background:#f9731622;color:#9a3412;'>Hold push until human review</span>`
              : (Array.isArray(st.sent) && st.sent.length
                ? `<span class='pill' style='background:#22c55e22;color:#166534;'>Already pushed</span>`
                : (shouldPush
                  ? `<span class='pill' style='background:#dc262622;color:#991b1b;'>Push to SIEM/XDR now</span>`
                  : `<span class='pill'>Passive monitoring only</span>`));
            const mailBadge = shouldRouteMail
              ? `<span class='pill' style='background:#2563eb22;color:#1d4ed8;'>Push to Proofpoint/Mimecast recommended</span>`
              : '';
            const approvalBadge = shouldHold
              ? `<span class='pill' style='background:#f59e0b22;color:#92400e;'>Approval required before trust or payment changes</span>`
              : `<span class='pill' style='background:#22c55e22;color:#166534;'>No extra human approval needed for routine push</span>`;
            const pushSummary = [
              shouldPush ? 'Push this incident to SIEM/XDR now for correlation and case tracking.' : 'Passive telemetry only is sufficient right now unless new evidence appears.',
              shouldHold ? 'Human review should happen before sending a stronger trust or enforcement signal downstream.' : null,
              shouldRouteMail ? 'Email security middleware push is recommended because sender trust or impersonation signals are present.' : null,
              Array.isArray(st.sent) && st.sent.length ? `Already sent to: ${st.sent.join(', ')}` : null,
              Array.isArray(st.failed) && st.failed.length ? `Push failed for: ${st.failed.join(', ')}` : null,
              Array.isArray(st.retrying) && st.retrying.length ? `Retrying: ${st.retrying.join(', ')}` : null
            ];
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
            const connectorRows = byTarget.length
              ? byTarget.map(t => `${t.target}: sent ${t.sent||0}, retrying ${t.retrying||0}, DLQ ${t.dlq||0}, skipped ${t.skipped||0}, success ${(parseFloat(t.success_rate||0)*100).toFixed(0)}%`)
              : ['No connector registry data available yet.'];
            const deliveryRows = dlqItems.length
              ? dlqItems.slice(0, 8).map(item => `${item.target || 'target'}: ${item.reason || item.status || 'delivery issue'} (${item.created_at || 'time unavailable'})`)
              : ['No failed deliveries are currently queued in the DLQ.'];
            document.getElementById('integrations_card').style.display = 'block';
            document.getElementById('integrations_sections').innerHTML = `<div class="evidence-block"><div class="section-label">Push Recommendation</div><div class="row" style="margin-bottom:8px; gap:6px; flex-wrap:wrap;">${pushBadge}${approvalBadge}${mailBadge}</div>${listHtml(pushSummary)}<div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap;"><button class="btn" type="button" onclick="replaySiemHandoff()">Push To SIEM / XDR</button><button class="btn" type="button" onclick="refreshConnectorHealth()">Refresh Connector Health</button></div></div><details class="evidence-block" style="display:block;"><summary>Connector registry and delivery history</summary><div style="margin-top:8px;"><div class="section-label">Connector Registry</div>${listHtml(connectorRows)}<div class="section-label" style="margin-top:10px;">Delivery History</div>${listHtml(deliveryRows)}</div></details><details class="evidence-block" style="display:block;"><summary>Push state and analyst workflow</summary><div style="margin-top:8px;">${listHtml(statusLines)}${listHtml(['Use these controls after review to improve precision and governance.', 'Mark Legit lowers false-positive risk. Mark Malicious reinforces true-positive coverage. Baseline Update requests human review before trust changes.'])}<div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap;"><button class="btn" type="button" onclick="submitFeedbackOutcome('analyst_review','false_positive','marked_legit')">Mark Legit</button><button class="btn" type="button" onclick="submitFeedbackOutcome('analyst_review','true_positive','confirmed_malicious')">Mark Malicious</button><button class="btn" type="button" onclick="submitFeedbackOutcome('business_exception','approved_exception','business_approved')">Approved Exception</button><button class="btn" type="button" onclick="submitFeedbackOutcome('baseline_review','approved_exception','baseline_update_requested')">Request Baseline Update</button></div></div></details>`;
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
              `Trust state: ${String(gov.governance_state || 'stable').replaceAll('_',' ')}`,
              pending.length ? `Pending supplier review: ${pending.length} item(s)` : 'No pending supplier governance updates.'
            ];
            const detailRows = [
              Array.isArray(gov.approved_domains) && gov.approved_domains.length ? `Approved domains: ${gov.approved_domains.join(', ')}` : null,
              Array.isArray(gov.observed_domains) && gov.observed_domains.length ? `Observed domains: ${gov.observed_domains.join(', ')}` : null,
              Array.isArray(gov.approved_bank_fingerprints) && gov.approved_bank_fingerprints.length ? `Approved bank fingerprints: ${gov.approved_bank_fingerprints.join(', ')}` : null,
              Array.isArray(gov.observed_bank_fingerprints) && gov.observed_bank_fingerprints.length ? `Observed bank fingerprints: ${gov.observed_bank_fingerprints.join(', ')}` : null,
              Array.isArray(gov.history) && gov.history.length ? `Recent decisions: ${gov.history.slice(-6).join(' | ')}` : null
            ];
            document.getElementById('gov_card').style.display = 'block';
            document.getElementById('gov_sections').innerHTML = `<div class="evidence-block"><div class="section-label">Governance Snapshot</div>${listHtml(sections)}</div><div class="evidence-block"><div class="section-label">Pending Approvals</div>${pendingHtml}</div><details class="evidence-block" style="display:block;"><summary>Trust and governance detail</summary><div style="margin-top:8px;">${listHtml(detailRows)}</div></details>`;
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
              `Related incidents: ${graph.incident_count || (incidentGraph.incident_count || 0)}`,
              Array.isArray(graph.risk_notes) && graph.risk_notes.length ? `Risk notes: ${graph.risk_notes.join(', ')}` : null
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
            document.getElementById('graph_sections').innerHTML = `<div class="evidence-block"><div class="section-label">Related Incident Summary</div>${listHtml(sections)}</div>${relationshipHtml}${timelineHtml}<details class="evidence-block" style="display:block;"><summary>Trust graph detail</summary><div style="margin-top:8px;">${listHtml([
              `Nodes: ${graph.node_count || nodes.length || 0}`,
              `Edges: ${graph.edge_count || edges.length || 0}`,
              nodes.length ? `Entities: ${nodes.slice(0,8).map(n => `${n.label} (${n.type})`).join(' | ')}` : null,
              edges.length ? `Relationships: ${edges.slice(0,8).map(e => `${e.source.split(':').slice(-1)[0]} -> ${e.target.split(':').slice(-1)[0]} (${e.relation})`).join(' | ')}` : null
            ])}</div></details>`;
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
              const summaryTags = [];
              if(item.attachment_class) summaryTags.push(String(item.attachment_class).replaceAll('_', ' '));
              if(item.supports_sender_claim === false || (Array.isArray(item.brand_supplier_mismatch_signals) && item.brand_supplier_mismatch_signals.length)) summaryTags.push('baseline drift');
              if(item.bank_fields_present || (Array.isArray(item.suspicious_instructions) && item.suspicious_instructions.some(x => /bank|payment|remittance/i.test(String(x||''))))) summaryTags.push('bank change');
              if(Array.isArray(item.embedded_urls) && item.embedded_urls.length) summaryTags.push('QR or URL');
              if((item.steg && item.steg.suspicious) || (Array.isArray(item.evidence_excerpt_lines) && item.evidence_excerpt_lines.some(x => /hidden|steg|prompt|beacon|exfil/i.test(String(x||''))))) summaryTags.push('hidden payload');
              if(!summaryTags.length) summaryTags.push('review required');
              rows.push(
                `<div class="attachment-row">
                  <div class="row" style="justify-content:space-between; align-items:flex-start; gap:8px; flex-wrap:wrap;">
                    <div><strong>${escHtml(item.file_name || 'attachment')}</strong><div class="small">${escHtml(item.file_type || 'unknown')}</div><div style="margin-top:6px;">${attachmentProvenanceChips(item)}</div></div>
                    <div class="small mono">${escHtml((item.sha256 || '').slice(0,20))}${item.sha256 ? '…' : ''}</div>
                  </div>
                  <div class="small" style="margin-top:6px;">${escHtml(Array.from(new Set(summaryTags)).join(', '))}</div>
                  <details style="margin-top:8px;"><summary>Attachment detail</summary><div style="margin-top:8px;" class="small">${escHtml(item.text_summary || 'No text extracted from this attachment.')}<div style="margin-top:6px;"><strong>Supports sender claim:</strong> ${escHtml(String(item.supports_sender_claim || 'neutral').replaceAll('_',' '))}</div>${listHtml([
                    item.attachment_class ? `Attachment class: ${String(item.attachment_class).replaceAll('_',' ')}` : null,
                    item.authority_level ? `Evidence authority: ${item.authority_level}` : null,
                    item.bank_fields_present ? 'Attachment contains bank or remittance fields.' : null,
                    item.embedded_urls && item.embedded_urls.length ? `Embedded URLs: ${item.embedded_urls.join(', ')}` : null,
                    item.suspicious_instructions && item.suspicious_instructions.length ? item.suspicious_instructions.join(' ') : null,
                    item.brand_supplier_mismatch_signals && item.brand_supplier_mismatch_signals.length ? item.brand_supplier_mismatch_signals.join(' ') : null,
                    item.evidence_excerpt_lines && item.evidence_excerpt_lines.length ? `Evidence excerpts: ${item.evidence_excerpt_lines.join(' | ')}` : null,
                    pdf.producer ? `PDF producer: ${pdf.producer}` : null,
                    (pdf.embedded_files_count||0) > 0 ? `Embedded files: ${pdf.embedded_files_count}` : null,
                    (pdf.object_stream_count||0) > 0 ? `Object streams: ${pdf.object_stream_count}` : null,
                    sim.template_aligned === false ? 'Template similarity check failed against the baseline.' : null,
                    sim.logo_layout_aligned === false ? 'Logo or layout similarity check failed against the baseline.' : null,
                    sim.known_good_template_hash ? `Known-good template hash: ${sim.known_good_template_hash}` : null,
                    sim.known_good_bank_fingerprint ? `Known-good bank fingerprint: ${sim.known_good_bank_fingerprint}` : null
                  ])}</div></details>
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
                <div class="small" style="margin-top:6px;"><strong>Text similarity:</strong> ${escHtml(String(item.text_similarity ?? '-'))} · <strong>Visual drift:</strong> ${escHtml(String(item.mean_pixel_diff ?? '-'))} · <strong>Drift box:</strong> ${escHtml(bbox)}</div>
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
            updateRailLayout();
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
              updateRailLayout();
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
              vBar.textContent = `Plain-English triggers`;
              const plainReasons = (j.reasons||[]).map(reasonToPlainEnglish).filter(Boolean);
              const rawReasonRows = (j.reasons||[]).map(r=>`<div style='margin:2px 0;'>• ${r}</div>`).join('');
              document.getElementById('sec_reasons_list').innerHTML = `${listHtml(plainReasons.slice(0,6))}${rawReasonRows ? `<details style="margin-top:8px;"><summary>Raw policy reasons</summary><div style="margin-top:8px;">${rawReasonRows}</div></details>` : ''}`;

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
                document.getElementById('trust_actions').innerHTML = `<div>Trust degraded</div>${acts.length || (tc.reasons || []).length ? `<details style="margin-top:8px;"><summary>Trust detail</summary><div style="margin-top:8px;">${listHtml([
                  ...acts.map(a => String(a).replaceAll('_',' ')),
                  ...(tc.reasons || []).map(reasonToPlainEnglish)
                ])}</div></details>` : ''}`;
                const reasons = tc.reasons || [];
                document.getElementById('trust_reasons').textContent = reasons.length ? 'Audit mapping available' : '';
              }

              /* ── Threat Correlation (MITRE / DREAD / CVSS / KEV / PASTA) ── */
              const thr = ev.threat_correlation || j.threat_correlation || {};
              const sa = ev.security_analysis || {};
              if(thr.mitre_attack || thr.dread || thr.cvss || thr.kev || thr.kill_chain_stage){
                const tc2 = document.getElementById('threat_card'); tc2.style.display='block';
                const mitre = Array.isArray(sa.mitre_attack) && sa.mitre_attack.length ? sa.mitre_attack : (Array.isArray(thr.mitre_attack) ? thr.mitre_attack : []);
                const atlas = Array.isArray(sa.mitre_atlas) && sa.mitre_atlas.length ? sa.mitre_atlas : [];
                const kev = Array.isArray(thr.kev) ? thr.kev : [];
                const businessOutcome = String(j.business_risk || j.summary || j.reason || 'Supports auditability, investigation quality, and business-safe response decisions.').trim();
                document.getElementById('threat_badges').innerHTML = `<span class='pill'>Audit mapping available</span>${mitre.slice(0,4).map(tag => `<span class='pill'>${escHtml(String(tag))}</span>`).join('')}`;
                const dread = thr.dread || {};
                document.getElementById('dread_avg').textContent = dread.avg!=null ? dread.avg : (thr.dread_avg!=null ? thr.dread_avg : '-');
                const cvss = thr.cvss || {};
                document.getElementById('cvss_score').textContent = cvss.score!=null ? `${cvss.score} (${cvss.severity||''})` : '-';
                document.getElementById('kc_stage').textContent = thr.kill_chain_stage || '-';
                document.getElementById('pasta_stage').textContent = sa.pasta_stage || thr.pasta_stage || ev.pasta_stage || '-';
                const frameworkRows = Array.isArray(sa.framework_rows) && sa.framework_rows.length ? sa.framework_rows : frameworkRowsForFinding(mitre, atlas, sa.pasta_stage || thr.pasta_stage || ev.pasta_stage || '', Array.isArray(((sa || {}).compliance || {}).frameworks) ? sa.compliance.frameworks : [], businessOutcome);
                const possibleFrameworkRows = Array.isArray(sa.possible_framework_rows) ? sa.possible_framework_rows : [];
                document.getElementById('kev_list').innerHTML = `
                  <div class="evidence-block">
                    <div class="section-label">Framework Mappings</div>
                    ${frameworkRowsHtml(frameworkRows)}
                    ${possibleFrameworkRows.length ? `<div style="margin-top:10px;"><div class="section-label">Possible mappings awaiting stronger runtime evidence</div>${frameworkRowsHtml(possibleFrameworkRows)}</div><div class="small" style="margin-top:8px;color:#64748b;">Passive evidence only. Runtime confirmation is still required, and no process-tree/network evidence has been observed yet for these mappings.</div>` : ''}
                  </div>
                  <div class="evidence-block">
                    <div class="section-label">DREAD Evidence Table</div>
                    <div class="small" style="margin-bottom:8px;">Each DREAD score must be traceable to evidence and a business consequence, not treated as a magic number.</div>
                    ${dreadEvidenceTableHtml(sa.dread_dimensions || dread, businessOutcome)}
                  </div>
                  <details class="evidence-block" style="display:block;">
                    <summary>Framework detail</summary>
                    <div style="margin-top:8px;">${listHtml([
                      kev.length ? `KEV: ${kev.join(', ')}` : null,
                      dread.avg!=null ? `DREAD average: ${dread.avg}` : null,
                      cvss.score!=null ? `CVSS: ${cvss.score} ${cvss.severity || ''}` : null,
                      thr.kill_chain_stage ? `Kill chain: ${thr.kill_chain_stage}` : null,
                      (thr.pasta_stage || ev.pasta_stage) ? `PASTA: ${thr.pasta_stage || ev.pasta_stage}` : null,
                      Array.isArray(sa.stride_categories) && sa.stride_categories.length ? `STRIDE: ${sa.stride_categories.join(', ')}` : null,
                    ])}</div>
                  </details>`;
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
                document.getElementById('sandbox_findings').innerHTML = `<details><summary>Sandbox / IOC detail</summary><div style="margin-top:8px;">${Array.isArray(findings) ? findings.slice(0,6).map(f=>`<div>• ${typeof f==='string'?f:JSON.stringify(f)}</div>`).join('') : ''}</div></details>`;
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

          async function analyze(){ resetPlaybookRunCard(); document.getElementById('status').textContent='Preparing attachments...'; const to = document.getElementById('to').value.trim(); const subj = document.getElementById('subject').value.trim(); const body = document.getElementById('body').value.trim(); let atts = []; try { atts = await collectAllAttachments(); } catch(attErr){ const msg = 'Attachment encoding failed: ' + String(attErr && attErr.message ? attErr.message : attErr); document.getElementById('status').textContent = msg; pushTraceNotice('attachment_encoding_failed', { error: msg }); return; } document.getElementById('status').textContent = `Analyzing ${atts.length} attachment${atts.length===1?'':'s'}... this can take 30-60s locally`; const payload = { message_id: 'lab-'+Math.random().toString(36).slice(2), from_addr: to, reply_to: to, subject: subj, body: body, attachments: atts, external_sender: true, dmarc_fail: false, spf_result: 'neutral', dkim_result: 'neutral', dmarc_result: 'quarantine', dmarc_policy: 'reject', vendor_domain: 'ingramfake.com.au' };
            try {
              let r = await fetch('/api/v1/email_security/evaluate', { method:'POST', credentials:'include', headers: postHeaders({ 'Content-Type':'application/json', 'x-api-key': getApiKey() }), body: JSON.stringify(payload) });
              if (r.status === 401 || r.status === 403) {
                r = await fetch('/api/v1/email_security/evaluate', { method:'POST', credentials:'include', headers: postHeaders({ 'Content-Type':'application/json', 'x-api-key': getOwnerKey() }), body: JSON.stringify(payload) });
              }
              const j = await r.json().catch(()=>null); if(!r.ok || !j){ const err=(j && (j.detail||j.error) ? (j.detail||j.error) : 'no details'); document.getElementById('status').textContent='Analyze failed ('+r.status+'): '+err; pushTraceNotice('analyze_failed', { status: r.status, error: err, endpoint: '/api/v1/email_security/evaluate' }); return; }
              const sevCls = {'error':'sev-error','warning':'sev-warning'}.hasOwnProperty(j.severity||'') ? 'sev-'+j.severity : 'sev-info';
              document.getElementById('verdict').textContent = (j.verdict_action || 'unknown').toUpperCase() + ' · ' + (j.severity || 'info').toUpperCase();
              document.getElementById('verdict').className = 'pill ' + sevCls;
              document.getElementById('reasons').textContent = (j.reasons||[]).slice(0,6).join(' · ');
              const ex = []; try { const ev = j.evidence_snapshot||{}; const ioc = ev.ioc_counts||{}; ex.push(`IOC: url=${ioc.url||0} domain=${ioc.domain||0} hash=${ioc.hash||0}`); if(ev.sender_trust && ev.sender_trust.sender_trust_score!=null){ ex.push(`Trust=${parseFloat(ev.sender_trust.sender_trust_score).toFixed(2)}`); } } catch(e) {}
              document.getElementById('extract').textContent = ex.join(' | ');
              document.getElementById('status').textContent='Rendering evidence panels...';
              renderSecurityPanels(j);
              const tid = j.decision_trace_id || j.decision_id || payload.message_id;
              pushTraceNotice('analysis_ready', { trace_id: tid, verdict_action: j.verdict_action || 'unknown', severity: j.severity || 'info', reasons: (j.reasons||[]).slice(0,3), attachment_count: Array.isArray(atts) ? atts.length : 0 });
              if (tid) { attachTrace(tid); }
              document.getElementById('status').textContent='✓ Analysis complete';
            } catch(e) { document.getElementById('status').textContent='Analyze error'; pushTraceNotice('analyze_error', { endpoint: '/api/v1/email_security/evaluate', error: String(e && e.message ? e.message : e) }); }
          }
          async function submitEscalate(){
            resetPlaybookRunCard();
            document.getElementById('status').textContent='Preparing attachments for escalation...';
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
            document.getElementById('status').textContent = `Analyzing ${atts.length} attachment${atts.length===1?'':'s'} and escalating... this can take 30-60s locally`;
            try {
              let r = await fetch('/api/v1/email_security/evaluate', { method:'POST', credentials:'include', headers: postHeaders({ 'Content-Type':'application/json', 'x-api-key': getApiKey() }), body: JSON.stringify(payload) });
              if (r.status === 401 || r.status === 403) {
                r = await fetch('/api/v1/email_security/evaluate', { method:'POST', credentials:'include', headers: postHeaders({ 'Content-Type':'application/json', 'x-api-key': getOwnerKey() }), body: JSON.stringify(payload) });
              }
              const j = await r.json().catch(()=>null);
              if(!r.ok || !j){ const err=(j && (j.detail||j.error) ? (j.detail||j.error) : 'no details'); document.getElementById('status').textContent='Analyze failed ('+r.status+')'; pushTraceNotice('submit_analyze_failed', { status: r.status, error: err, endpoint: '/api/v1/email_security/evaluate' }); return; }
              document.getElementById('verdict').textContent = (j.verdict_action || 'unknown') + ' / ' + (j.severity || 'info');
              document.getElementById('reasons').textContent = (j.reasons||[]).slice(0,6).join(', ');
              const tid = j.decision_trace_id || j.decision_id || payload.message_id;
              pushTraceNotice('analysis_ready', { trace_id: tid, verdict_action: j.verdict_action || 'unknown', severity: j.severity || 'info', reasons: (j.reasons||[]).slice(0,3), attachment_count: Array.isArray(atts) ? atts.length : 0 });
              if (tid) { attachTrace(tid); }
              renderSecurityPanels(j);
              // Now escalate: create an incident via the public escalation endpoint
              try {
                const escPayload = { case_id: j.decision_trace_id || j.decision_id || payload.message_id, trace_id: j.decision_trace_id, reason: 'email_lab_manual_escalation', context: { subject: subj, verdict: j.verdict_action, severity: j.severity, reasons: (j.reasons||[]).slice(0,6) } };
                const escR = await fetch('/api/v1/incidents/escalate', { method:'POST', credentials:'include', headers: postHeaders({ 'Content-Type':'application/json' }), body: JSON.stringify(escPayload) });
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
                const t = await fetch(`/api/v1/admin/incidents/${encodeURIComponent(roomIncidentId)}/room/token`, { method:'POST', credentials:'include', headers:postHeaders({ 'x-api-key': getOwnerKey() }) });
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
              let r = await fetch('/api/v1/trace/events', { method:'POST', credentials:'include', headers:postHeaders({ 'Content-Type':'application/json', 'x-api-key': getApiKey() }), body: JSON.stringify(batch) });
              if(r.status === 401 || r.status === 403){
                r = await fetch('/api/v1/trace/events', { method:'POST', credentials:'include', headers:postHeaders({ 'Content-Type':'application/json', 'x-api-key': getOwnerKey() }), body: JSON.stringify(batch) });
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
    resp = _merchant_html_response(request, html)
    resp.set_cookie("shopsquire_api_key", _owner_key, httponly=False, samesite="strict", secure=_is_https_request(request))
    return resp

