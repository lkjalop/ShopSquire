
import os
import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response, JSONResponse
from sqlalchemy import text

from src.app.security.guardrails import guardrail_profile_for_user

router = APIRouter(prefix="/ui", tags=["ui"])


def _features_from_specs(specs: dict | None) -> list[str]:
    if not isinstance(specs, dict):
        return []
    feats: list[str] = []
    def add(label: str, value: str | None):
        if value:
            feats.append(f"{label}: {value}")
    add("CPU", specs.get("cpu"))
    add("Graphics", specs.get("graphics") or specs.get("gpu"))
    add("RAM", specs.get("ram") or (f"{specs.get('ram_gb')}GB" if specs.get("ram_gb") else None))
    add("Storage", specs.get("storage") or specs.get("ssd"))
    add("Wi-Fi", specs.get("wifi"))
    ports = specs.get("ports")
    if isinstance(ports, list):
        add("Ports", ", ".join([str(p) for p in ports if p]))
    else:
        add("Ports", ports)
    return feats


def _load_products_from_db() -> list[dict]:
    try:
        from src.app.models.db import db_session
        with db_session() as db:
            rows = db.execute(
                text(
                    "SELECT p.sku, p.name, p.price_cents, p.currency, p.image_url, p.specs, i.stock "
                    "FROM products p LEFT JOIN inventory i ON p.id = i.product_id"
                )
            ).fetchall()
        products: list[dict] = []
        for row in rows or []:
            specs = None
            try:
                specs = json.loads(row[5]) if row[5] else None
            except Exception:
                specs = None
            feats = _features_from_specs(specs)
            price = int(row[2] / 100) if row[2] is not None else None
            products.append(
                {
                    "sku": row[0],
                    "name": row[1],
                    "price": price,
                    "currency": row[3] or "USD",
                    "image_url": row[4] or "/static/images/placeholder.svg",
                    "features": feats,
                    "specs": specs or {},
                    "stock": row[6],
                }
            )
        return products
    except Exception:
        return []


def _get_products() -> list[dict]:
    # Production path only: catalog must come from the database.
    return _load_products_from_db()


def _load_product_by_sku_from_db(sku: str) -> dict | None:
    try:
        from src.app.models.db import db_session
        with db_session() as db:
            row = db.execute(
                text(
                    "SELECT p.sku, p.name, p.price_cents, p.currency, p.image_url, p.specs, i.stock "
                    "FROM products p LEFT JOIN inventory i ON p.id = i.product_id WHERE p.sku = :sku LIMIT 1"
                ),
                {"sku": sku},
            ).fetchone()
        if not row:
            return None
        specs = None
        try:
            specs = json.loads(row[5]) if row[5] else None
        except Exception:
            specs = None
        feats = _features_from_specs(specs)
        price = int(row[2] / 100) if row[2] is not None else None
        return {
            "sku": row[0],
            "name": row[1],
            "price": price,
            "currency": row[3] or "USD",
            "image_url": row[4] or "/static/images/placeholder.svg",
            "features": feats,
            "specs": specs or {},
            "stock": row[6],
        }
    except Exception:
        return None


def _find_product_by_sku(sku: str) -> dict | None:
    db_hit = _load_product_by_sku_from_db(sku)
    if db_hit:
        return db_hit
    for p in _get_products():
        if str(p.get("sku")) == str(sku):
            return p
    return None


@router.get("/widget.js")
def widget_js() -> Response:
    try:
        candidates = [
            Path(__file__).resolve().parents[2] / "frontend" / "widget" / "shopsquire-widget.js",
            Path.cwd() / "src" / "frontend" / "widget" / "shopsquire-widget.js",
            Path(__file__).resolve().parents[3] / "frontend" / "widget" / "shopsquire-widget.js",
        ]
        for p in candidates:
            try:
                if p.exists():
                    content = p.read_text(encoding="utf-8")
                    return Response(content, media_type="application/javascript", status_code=200)
            except Exception:
                continue
    except Exception:
        pass
    return Response("/* widget bundle not found */", media_type="application/javascript", status_code=503)


@router.get("/storefront")
def storefront() -> HTMLResponse:
    api_key = os.getenv("MERCHANT_API_KEY", "")
    products = _get_products()

    def _detail_link(p: dict) -> str:
        sku = p.get("sku")
        return f'<a class="detail" href="/ui/product/{sku}">View details</a>' if sku else ""

    def _meta(p: dict) -> str:
        feats = p.get("features") or _features_from_specs(p.get("specs") if isinstance(p, dict) else None)
        if feats:
            display = feats[:6]
            return f'<p class="meta">{" | ".join(display)}</p>'
        return ""

    cards = "".join(
        [
            (
                f"<article class=\"card\" data-sku=\"{p.get('sku','')}\">"
                f"<h3 class=\"title\">{p['name']}</h3>"
                f"<p class=\"price\">${p['price']}</p>"
                f"{_meta(p)}"
                f"<div class=\"actions\"><button class=\"btn add add-to-cart\" data-add=\"{p.get('sku','')}\">Add to cart</button>{_detail_link(p)}</div>"
                f"</article>"
            )
            for p in products
        ]
    )

    products_json = json.dumps(products)
    profile = guardrail_profile_for_user(None, None)
    html = """
    <!doctype html>
    <html lang='en'>
    <head>
      <meta charset='utf-8' />
      <meta name='viewport' content='width=device-width, initial-scale=1' />
      <title>ShopSquire Storefront</title>
      <style>
        body { margin:0; font-family: system-ui, sans-serif; }
        header { padding: 18px 24px; background:#15171b; color:#fff; display:flex; justify-content:space-between; align-items:center; }
        main { padding: 24px; }
        .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:12px; }
        .card { background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:12px; }
        .price { font-weight:700; }
        .actions { display:flex; gap:8px; }
        .btn { background:#cc5b2c; color:#fff; border:none; padding:8px 10px; border-radius:10px; }
        shopsquire-widget { display:block; }
      </style>
    </head>
    <body>
      <header>
        <div>ShopSquire Storefront</div>
        <div>Cart: <span class="cart-count">0</span></div>
      </header>
      <main>
        <section class="grid" id="product-grid">__CARDS__</section>
        __EMPTY_STATE__
      </main>
      <shopsquire-widget data-api-base="" data-api-key="__API_KEY__" data-uid="guest-user" data-signed-in="false"></shopsquire-widget>
      <script src="/ui/widget.js"></script>
      <script>
        window.__GUARDRAILS__ = __GUARDRAILS__;
        window.__PRODUCTS__ = __PRODUCTS__;
      </script>
    </body>
    </html>
    """
    html = (
        html.replace("__CARDS__", cards)
        .replace("__EMPTY_STATE__", "<p>No catalog products are currently available.</p>" if not products else "")
        .replace("__API_KEY__", api_key)
        .replace("__GUARDRAILS__", json.dumps(profile))
        .replace("__PRODUCTS__", products_json)
    )
    return HTMLResponse(content=html)


@router.get("/checkout")
def checkout() -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang='en'>
    <head><meta charset='utf-8' /><title>ShopSquire Checkout</title></head>
    <body>
      <h1>Checkout</h1>
      <form id="checkout-form" novalidate>
        <label>Name <input name="name" required /></label>
        <label>Email <input name="email" type="email" required /></label>
        <label>Address <input name="address" required /></label>
        <label>Card Number <input name="card" required /></label>
        <div id="form-error" style="display:none;color:#b42318;">Please fill in all required fields.</div>
        <button type="submit">Place Order</button>
      </form>
      <script>
        const form = document.getElementById('checkout-form');
        const error = document.getElementById('form-error');
        if (form) {
          form.addEventListener('submit', (e) => {
            e.preventDefault();
            if (error) error.style.display = 'block';
          });
        }
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/forensics")
def forensics_console() -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang='en'>
    <head><meta charset='utf-8' /><title>ShopSquire Forensics</title></head>
    <body>
      <h1>Forensics Console</h1>
      <p id="forensics-status">Ready for CV evidence and decision-trace review.</p>
      <ul id="forensics-capabilities">
        <li>Image integrity checks</li>
        <li>Trace timeline correlation</li>
        <li>Manual reviewer handoff queue</li>
      </ul>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/products.json")
def products_json() -> JSONResponse:
    return JSONResponse(_get_products())


@router.get("/product/{sku}")
def product_detail(sku: str) -> HTMLResponse:
    p = _find_product_by_sku(sku)
    if not p:
        html = """
        <!doctype html>
        <html><head><meta charset='utf-8'><title>Product Not Found</title></head>
        <body>
          <h2>Product not found</h2>
          <p>SKU: {sku}</p>
        </body></html>
        """
        return HTMLResponse(content=html.format(sku=sku), status_code=200)

    name = p.get("name", f"Product {sku}")
    price = p.get("price")
    feats = p.get("features") or _features_from_specs(p.get("specs") if isinstance(p, dict) else None)

    def spec_row(label: str, value: str | None) -> str:
        return f"<tr><th style='text-align:left;width:160px'>{label}</th><td>{value or '?'}" + "</td></tr>"

    def find_feat(key: str) -> str | None:
        for f in feats:
            if key.lower() in f.lower():
                return f
        return None

    spec_rows = "".join(
        [
            spec_row("CPU", find_feat("cpu")),
            spec_row("GPU", find_feat("graphics") or find_feat("gpu")),
            spec_row("RAM", find_feat("ram")),
            spec_row("Storage", find_feat("storage")),
            spec_row("Wi-Fi", find_feat("wi-fi")),
            spec_row("Ports", find_feat("ports")),
        ]
    ) or "<tr><td>No specs available</td></tr>"

    price_display = ("$" + str(price)) if price is not None else ""
    api_key = os.getenv("MERCHANT_API_KEY", "")
    html = """
    <!doctype html>
    <html lang='en'>
    <head>
      <meta charset='utf-8' />
      <title>__NAME__ - Details</title>
      <style>
        body { font-family: system-ui, sans-serif; }
        shopsquire-widget { display:block; }
      </style>
    </head>
    <body>
      <header>
        <span>__NAME__</span> Cart: <span class='cart-count'>0</span>
        <button data-test='decision-gear' id='decision-gear'>Trace</button>
      </header>
      <main>
        <h1>__NAME__</h1>
        <p>__PRICE__</p>
        <button class='add-to-cart'>Add to Cart</button>
        <table><tbody>__SPEC_ROWS__</tbody></table>
      </main>
      <shopsquire-widget data-api-base='' data-api-key='__API_KEY__' data-uid='detail-user' data-signed-in='false'></shopsquire-widget>
      <script src='/ui/widget.js'></script>
      <script>
        const cartCount = document.querySelector('.cart-count');
        const addBtn = document.querySelector('.add-to-cart');
        function setCount(v){ if (cartCount) cartCount.textContent = String(v); }
        const stored = parseInt(localStorage.getItem('cart_count') || '0', 10);
        setCount(isNaN(stored) ? 0 : stored);
        if (addBtn) {
          addBtn.addEventListener('click', () => {
            const cur = parseInt(localStorage.getItem('cart_count') || '0', 10) || 0;
            const next = cur + 1;
            localStorage.setItem('cart_count', String(next));
            setCount(next);
          });
        }
                const modal = document.createElement('div');
                modal.id = 'decision-modal';
                modal.style.display = 'none';
                modal.innerHTML = `
                    <div style="max-width:640px;margin:6% auto;background:#fff;border-radius:12px;padding:12px;border:1px solid #e5e7eb;">
                        <div style="display:flex;justify-content:space-between;align-items:center;padding-bottom:8px;border-bottom:1px solid #f3f4f6;">
                            <div style="font-weight:700;">Decision Trace</div>
                            <button id="decision-close" style="border:none;background:#fff;padding:6px 10px;border:1px solid #e5e7eb;border-radius:8px;cursor:pointer;">Close</button>
                        </div>
                        <div style="padding:8px 0;display:flex;gap:8px;align-items:center;">
                            <button id="decision-summary-btn" data-test="decision-summary-btn" style="padding:6px 10px;border-radius:8px;border:1px solid #e5e7eb;background:#fff;cursor:pointer;font-weight:600;">Summary</button>
                            <button id="decision-trace-btn" data-test="decision-trace-btn" style="padding:6px 10px;border-radius:8px;border:1px solid #e5e7eb;background:transparent;cursor:pointer;">Live Trace</button>
                        </div>
                        <div id="decision-modal-body" style="padding-top:8px;">
                            <div id="decision-summary" data-test="decision-summary">
                                <div style="margin-bottom:8px;"><div style="font-weight:600;">Model Selection</div><div class="meta">Selected model: rules</div></div>
                                <div style="font-weight:600; margin-top:6px;">Contract & Quality</div>
                                <div style="font-size:12px;color:#6b7280;">No Contract NLP analysis available.</div>
                            </div>
                            <div id="decision-trace" data-test="decision-trace" style="display:none;"></div>
                        </div>
                    </div>`;
                document.body.appendChild(modal);
                document.getElementById('decision-gear')?.addEventListener('click', () => { modal.style.display = 'block'; });
                try {
                    const sBtn = modal.querySelector('#decision-summary-btn');
                    const tBtn = modal.querySelector('#decision-trace-btn');
                    const sPanel = modal.querySelector('#decision-summary');
                    const tPanel = modal.querySelector('#decision-trace');
                    if (sBtn && tBtn && sPanel && tPanel) {
                        sBtn.addEventListener('click', () => { sPanel.style.display = 'block'; tPanel.style.display = 'none'; sBtn.style.background = '#fff'; tBtn.style.background = 'transparent'; });
                        tBtn.addEventListener('click', () => { sPanel.style.display = 'none'; tPanel.style.display = 'block'; tBtn.style.background = '#fff'; sBtn.style.background = 'transparent'; });
                    }
                } catch (e) {}
                try {
                    modal.querySelectorAll('.event').forEach((el) => {
                        el.addEventListener('click', () => {
                            const payload = el.querySelector('.eventPayload');
                            if (payload) payload.style.display = 'block';
                        });
                    });
                } catch (e) {}
      </script>
    </body>
    </html>
    """
    html = (
        html.replace("__NAME__", name)
        .replace("__PRICE__", price_display)
        .replace("__SPEC_ROWS__", spec_rows)
        .replace("__API_KEY__", api_key)
    )
    return HTMLResponse(content=html)
