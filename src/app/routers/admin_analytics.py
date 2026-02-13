from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
import os
import pathlib

from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/grc")
def grc_dashboard(request: Request, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    return RedirectResponse(url="/static/admin/index.html?tab=grc")


@router.get("/analytics", response_class=HTMLResponse)
def analytics_dashboard(request: Request, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    """Admin dashboard: prefer the built Vite app if available, otherwise render a lightweight fallback.

    When a built frontend exists at `static/admin/index.html` we redirect there so the app serves
    the compiled UI. We also attach a conservative CSP header to mitigate injection risks.
    """
    built_index = pathlib.Path("static") / "admin" / "index.html"
    csp = "default-src 'self'; frame-src 'self' http://localhost:3000 http://127.0.0.1:3000; style-src 'self' 'unsafe-inline'"
    # Default to the lightweight fallback in tests/CI to avoid relying on external CDNs.
    # Opt-in to serving the static SPA with `ADMIN_ANALYTICS_USE_STATIC=1`.
    use_static = os.getenv("ADMIN_ANALYTICS_USE_STATIC", "0").strip().lower() in ("1", "true", "yes", "on")
    if use_static and built_index.exists():
        # Redirect to the built static admin index; add CSP header
        return RedirectResponse(url="/static/admin/index.html", headers={"Content-Security-Policy": csp})

    # Fallback: render a small inline dashboard useful during development
    grafana_url = os.getenv("GRAFANA_URL", "http://localhost:3000")
    grafana_uid = os.getenv("GRAFANA_DASHBOARD_UID", "shopsquire")
    grafana_panel = os.getenv("GRAFANA_PANEL_ID", "1")
    grafana_proxy_base = "/admin/grafana_proxy/d/"
    grafana_dashboards = [
        ("Executive Overview", "shopsquire-exec-overview"),
        ("Agent Confidence", "shopsquire-agent-confidence"),
        ("CV Latency", "shopsquire-cv-latency"),
        ("Escalation Rates", "shopsquire-escalation-rates"),
        ("RAGAS Over Time", "shopsquire-ragas"),
        ("Model Selection", "shopsquire-model-selection"),
        ("Query Cluster Drift", "shopsquire-query-cluster-drift"),
        ("Human Review Queue", "shopsquire-human-review"),
    ]
    api_dashboards = [
        ("Calibration Alerts API", "/api/v1/admin/drift/calibration/alerts"),
        ("LTR Snapshot API", "/api/v1/admin/drift/recommendation/ltr_snapshot"),
    ]
    dashboard_links = "".join(
        [
            f'<li><a href="{grafana_proxy_base}{uid}?orgId=1&theme=dark&var-theme=dark" target="_blank">{name}</a></li>'
            for name, uid in grafana_dashboards
        ] + [
            f'<li><a href="{url}" target="_blank">{name}</a></li>'
            for name, url in api_dashboards
        ]
    )
    html = """
    <html>
      <head>
        <title>ShopSquire Admin Analytics</title>
        <meta http-equiv="Content-Security-Policy" content="__CSP__" />
        <style>
          :root { --bg:#f8fafc; --panel:#ffffff; --text:#0f172a; --accent:#0b5fff; --border:#dbe4ee; }
          body { font-family: "Segoe UI", Arial, sans-serif; margin: 16px; background: var(--bg); color: var(--text); }
          .cards { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:12px; }
          .card { border:1px solid var(--border); background:var(--panel); padding:12px; border-radius:10px; width:240px; box-shadow:0 1px 3px rgba(2,6,23,0.08) }
          .grc { border-left: 4px solid var(--accent); }
          iframe { width:100%; height:520px; border:1px solid var(--border); border-radius:10px; background:#fff }
          a { color: var(--accent); text-decoration:none; }
          a:hover { text-decoration:underline; }
        </style>
      </head>
      <body>
        <h2>Admin Analytics</h2>
        <div class="cards">
          <div class="card" id="top-asns">Top ASNs<br/><small>Loading...</small></div>
          <div class="card" id="heatmap">Country heatmap<br/><small>Loading...</small></div>
          <div class="card" id="velocity">Velocity anomalies<br/><small>Loading...</small></div>
        </div>
        <h3>Grafana panels</h3>
        <iframe src="__GRAFANA_IFRAME__" title="Grafana panel"></iframe>
        <p><a href="__GRAFANA_URL__" target="_blank">Open full Grafana dashboard (new tab)</a></p>
        <h3>Professional Dashboards</h3>
        <ul>
          __DASHBOARD_LINKS__
        </ul>
        <h3>GRC Consultant Workspace</h3>
        <div class="cards">
          <div class="card grc">
            <strong>Adaptive Risk Register</strong><br/>
            <small>Cross-domain risk scoring for email, supplier, inventory, insider, and traceability.</small><br/>
            <a href="/api/v1/admin/grc/risk-register?days=30" target="_blank">Open risk register JSON</a>
          </div>
          <div class="card grc">
            <strong>Compliance Report</strong><br/>
            <small>Control status mapped to ISO27001, GDPR, EU AI Act, NIST AI RMF, ISO42001, ISO19011.</small><br/>
            <a href="/api/v1/admin/grc/report?days=30" target="_blank">Open report bundle</a>
          </div>
          <div class="card grc">
            <strong>Evidence Export</strong><br/>
            <small>Decision/security evidence artifacts for audit and external review.</small><br/>
            <a href="/api/v1/admin/compliance/reports/evidence?days=30" target="_blank">Open evidence report</a>
          </div>
        </div>
        <script>
          async function loadCard(path, el){
            try{
              const r = await fetch(path);
              const j = await r.json();
              const count = j.top_asns ? j.top_asns.length : (j.countries ? j.countries.length : (j.velocity_anomalies || 0));
              document.getElementById(el).innerHTML = "<strong>" + count + "</strong>";
            }catch(e){ document.getElementById(el).innerHTML = '<small>error</small>' }
          }
          loadCard('/api/v1/analytics/fraud/geo/top_asns', 'top-asns');
          loadCard('/api/v1/analytics/fraud/geo/country_heatmap', 'heatmap');
          loadCard('/api/v1/analytics/fraud/geo/velocity_anomalies', 'velocity');
        </script>
      </body>
    </html>
    """
    html = (
        html.replace("__CSP__", csp)
        .replace("__GRAFANA_IFRAME__", f"{grafana_proxy_base}{grafana_uid}/security-geo?orgId=1&panelId={grafana_panel}")
        .replace("__GRAFANA_URL__", f"{grafana_url}/d/{grafana_uid}")
        .replace("__DASHBOARD_LINKS__", dashboard_links)
    )
    return HTMLResponse(content=html, headers={"Content-Security-Policy": csp})
