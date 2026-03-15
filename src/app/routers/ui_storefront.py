
import os
import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response, JSONResponse
from sqlalchemy import text

from src.app.security.guardrails import guardrail_profile_for_user

router = APIRouter(prefix="/ui", tags=["ui"])

def _coerce_specs(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


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
    def _rows_from_sqlite_env() -> list[tuple]:
        db_url = str(os.getenv("DATABASE_URL") or "")
        if not db_url.startswith("sqlite:///"):
            return []
        db_path = db_url.replace("sqlite:///", "", 1)
        if not db_path:
            return []
        con = sqlite3.connect(db_path)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT p.sku, p.name, p.price_cents, p.currency, p.image_url, p.specs, i.stock "
                "FROM products p LEFT JOIN inventory i ON p.id = i.product_id"
            )
            return list(cur.fetchall() or [])
        finally:
            con.close()

    try:
        from src.app.models.db import db_session
        with db_session() as db:
            try:
                rows = db.execute(
                    text(
                        "SELECT p.sku, p.name, p.price_cents, p.currency, p.image_url, p.specs, i.stock "
                        "FROM products p LEFT JOIN inventory i ON p.id = i.product_id"
                    )
                ).fetchall()
            except Exception:
                rows = db.execute(
                    text(
                        "SELECT p.sku, p.name, p.price_cents, p.currency, NULL as image_url, p.specs, i.stock "
                        "FROM products p LEFT JOIN inventory i ON p.id = i.product_id"
                    )
                ).fetchall()
        if not rows:
            rows = _rows_from_sqlite_env()
        products: list[dict] = []
        for row in rows or []:
            specs = _coerce_specs(row[5])
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
                    "specs": specs,
                    "stock": row[6],
                }
            )
        return products
    except Exception:
        try:
            rows = _rows_from_sqlite_env()
            products: list[dict] = []
            for row in rows or []:
                specs = _coerce_specs(row[5])
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
                        "specs": specs,
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
    def _row_from_sqlite_env(target_sku: str) -> tuple | None:
        db_url = str(os.getenv("DATABASE_URL") or "")
        if not db_url.startswith("sqlite:///"):
            return None
        db_path = db_url.replace("sqlite:///", "", 1)
        if not db_path:
            return None
        con = sqlite3.connect(db_path)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT p.sku, p.name, p.price_cents, p.currency, p.image_url, p.specs, i.stock "
                "FROM products p LEFT JOIN inventory i ON p.id = i.product_id WHERE p.sku = ? LIMIT 1",
                (target_sku,),
            )
            return cur.fetchone()
        finally:
            con.close()

    try:
        from src.app.models.db import db_session
        with db_session() as db:
            try:
                row = db.execute(
                    text(
                        "SELECT p.sku, p.name, p.price_cents, p.currency, p.image_url, p.specs, i.stock "
                        "FROM products p LEFT JOIN inventory i ON p.id = i.product_id WHERE p.sku = :sku LIMIT 1"
                    ),
                    {"sku": sku},
                ).fetchone()
            except Exception:
                row = db.execute(
                    text(
                        "SELECT p.sku, p.name, p.price_cents, p.currency, NULL as image_url, p.specs, i.stock "
                        "FROM products p LEFT JOIN inventory i ON p.id = i.product_id WHERE p.sku = :sku LIMIT 1"
                    ),
                    {"sku": sku},
                ).fetchone()
        if not row:
            row = _row_from_sqlite_env(sku)
        if not row:
            return None
        specs = _coerce_specs(row[5])
        feats = _features_from_specs(specs)
        price = int(row[2] / 100) if row[2] is not None else None
        return {
            "sku": row[0],
            "name": row[1],
            "price": price,
            "currency": row[3] or "USD",
            "image_url": row[4] or "/static/images/placeholder.svg",
            "features": feats,
            "specs": specs,
            "stock": row[6],
        }
    except Exception:
        try:
            row = _row_from_sqlite_env(sku)
            if not row:
                return None
            specs = _coerce_specs(row[5])
            feats = _features_from_specs(specs)
            price = int(row[2] / 100) if row[2] is not None else None
            return {
                "sku": row[0],
                "name": row[1],
                "price": price,
                "currency": row[3] or "USD",
                "image_url": row[4] or "/static/images/placeholder.svg",
                "features": feats,
                "specs": specs,
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
    import os, re as _re
    raw_pk = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    # Only inject pk_test_ / pk_live_ keys — never secret keys
    stripe_pk = raw_pk if _re.match(r"^pk_(test|live)_[A-Za-z0-9]+$", raw_pk) else ""
    html = f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>ShopSquire — Checkout</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;color:#111;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:1rem}}
    .card{{background:#fff;border-radius:12px;padding:2rem;width:100%;max-width:480px;box-shadow:0 4px 24px rgba(0,0,0,.09)}}
    h1{{font-size:1.35rem;margin-bottom:1.5rem;color:#111}}
    .section{{margin-bottom:1.15rem}}
    label{{display:block;font-size:.83rem;color:#555;margin-bottom:.35rem;font-weight:500}}
    input{{display:block;width:100%;padding:.65rem .85rem;border:1px solid #d1d5db;border-radius:8px;font-size:.95rem;outline:none;transition:border-color .15s}}
    input:focus{{border-color:#7c3aed;box-shadow:0 0 0 3px rgba(124,58,237,.15)}}
    .demo-strip{{background:#ede9fe;border-radius:8px;padding:.7rem 1rem;margin-bottom:1.2rem;font-size:.82rem;color:#5b21b6;display:flex;align-items:center;gap:.5rem}}
    .summary-row{{display:flex;justify-content:space-between;font-size:.88rem;padding:.22rem 0;color:#374151}}
    .summary-row.total{{font-weight:700;border-top:1px solid #e5e7eb;padding-top:.5rem;margin-top:.35rem;font-size:.95rem}}
    .summary-section{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:.75rem 1rem;margin-bottom:1.2rem}}
    .summary-title{{font-size:.78rem;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.04em;margin-bottom:.5rem}}
    .payment-box{{border:1px dashed #c4b5fd;border-radius:8px;padding:1rem;background:#faf5ff;margin-bottom:1.2rem;font-size:.85rem;color:#6d28d9;text-align:center}}
    #stripe-element-container{{min-height:44px}}
    .btn{{display:block;width:100%;padding:.8rem;background:#7c3aed;color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;transition:background .15s}}
    .btn:hover{{background:#6d28d9}}
    .btn:disabled{{background:#c4b5fd;cursor:not-allowed}}
    #form-error{{color:#b42318;font-size:.83rem;margin-top:.5rem;display:none}}
    #success-box{{display:none;text-align:center;padding:2rem 1rem}}
    #success-box h2{{color:#059669;font-size:1.5rem;margin-bottom:.75rem}}
    #success-box p{{color:#555;font-size:.9rem}}
    .order-id{{font-family:monospace;background:#f0fdf4;padding:.4rem .8rem;border-radius:6px;color:#065f46;display:inline-block;margin:.75rem 0;font-size:.88rem}}
    .back-link{{display:inline-block;margin-top:1.25rem;color:#7c3aed;text-decoration:none;font-size:.88rem}}
    .back-link:hover{{text-decoration:underline}}
    .spinner{{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.5);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
  </style>
</head>
<body>
  <div class="card">
    <div id="checkout-form-wrap">
      <h1>&#x1F6D2; Complete Your Order</h1>

      <div class="demo-strip">
        <span>&#x26A1;</span>
        <span id="demo-mode-label">Demo mode — no real payment will be processed.</span>
      </div>

      <div class="summary-section" id="order-summary-section" style="display:none">
        <div class="summary-title">Order Summary</div>
        <div id="order-summary-rows"></div>
      </div>

      <form id="checkout-form" novalidate>
        <div class="section">
          <label for="inp-name">Full Name</label>
          <input id="inp-name" name="name" autocomplete="name" required placeholder="Jane Smith" />
        </div>
        <div class="section">
          <label for="inp-email">Email Address</label>
          <input id="inp-email" name="email" type="email" autocomplete="email" required placeholder="jane@example.com" />
        </div>
        <div class="section">
          <label for="inp-addr">Shipping Address</label>
          <input id="inp-addr" name="address" autocomplete="street-address" required placeholder="123 Main St, City, Country" />
        </div>

        <div class="payment-box">
          <div id="stripe-element-container"></div>
          <div id="demo-payment-hint">&#x1F512; Payment details are handled securely by Stripe.<br/><small style="color:#9ca3af">(Stripe Payment Element loads here when configured)</small></div>
        </div>

        <div id="form-error"></div>
        <button class="btn" type="submit" id="submit-btn">
          <span id="btn-label">Place Order</span>
        </button>
      </form>
    </div>

    <div id="success-box">
      <div style="font-size:3rem">&#x2705;</div>
      <h2>Order Confirmed!</h2>
      <p>Thank you for your order. A confirmation will be sent to your email.</p>
      <div class="order-id" id="order-id-display"></div>
      <br/>
      <a href="/ui" class="back-link">&#x2190; Continue Shopping</a>
    </div>

    <a href="/ui" class="back-link" id="back-link-form">&#x2190; Back to Shopping</a>
  </div>

  <script>
    var STRIPE_PK = '{stripe_pk}';
    var stripe = null;

    // Read cart snapshot stored by CartPanel before navigating here
    var cartSummary = null;
    try {{
      var _raw = sessionStorage.getItem('shopsquire_checkout_cart');
      if (_raw) cartSummary = JSON.parse(_raw);
    }} catch(e) {{}}

    // Populate order summary
    if (cartSummary && cartSummary.items && cartSummary.items.length > 0) {{
      var sec = document.getElementById('order-summary-section');
      var rows = document.getElementById('order-summary-rows');
      cartSummary.items.forEach(function(item) {{
        var row = document.createElement('div');
        row.className = 'summary-row';
        var price = item.price_cents ? '$' + (item.price_cents / 100).toLocaleString() : '';
        row.innerHTML = '<span>' + (item.name || item.sku) + ' &times;' + item.quantity + '</span><span>' + price + '</span>';
        rows.appendChild(row);
      }});
      var bundle = cartSummary.bundle_savings || null;
      if (bundle) {{
        var laptopRow = document.createElement('div');
        laptopRow.className = 'summary-row';
        laptopRow.innerHTML = '<span>Laptop price</span><span>$' + (((bundle.laptop_subtotal_cents || 0) / 100).toLocaleString()) + '</span>';
        rows.appendChild(laptopRow);

        var accRow = document.createElement('div');
        accRow.className = 'summary-row';
        accRow.innerHTML = '<span>Accessories</span><span>$' + (((bundle.accessories_subtotal_cents || 0) / 100).toLocaleString()) + '</span>';
        rows.appendChild(accRow);

        var discountRow = document.createElement('div');
        discountRow.className = 'summary-row';
        var discountLabel = bundle.approval_required ? 'Bundle discount (pending review)' : 'Bundle discount (laptop only)';
        discountRow.innerHTML = '<span>' + discountLabel + '</span><span>- $' + ((((bundle.approval_required ? bundle.discount_cents : (bundle.applied_discount_cents || bundle.discount_cents)) || 0) / 100).toLocaleString()) + '</span>';
        rows.appendChild(discountRow);
      }}
      var total = document.createElement('div');
      total.className = 'summary-row total';
      var totalCents = bundle ? (bundle.final_total_cents || cartSummary.subtotal_cents || 0) : (cartSummary.subtotal_cents || 0);
      var sub = totalCents ? '$' + (totalCents / 100).toLocaleString() : '';
      total.innerHTML = '<span>' + ((bundle && bundle.approval_required) ? 'Current total' : 'Final total') + '</span><span>' + sub + '</span>';
      rows.appendChild(total);
      if (bundle && bundle.approval_required) {{
        var est = document.createElement('div');
        est.className = 'summary-row';
        est.innerHTML = '<span>Estimated total after approval</span><span>$' + (((bundle.estimated_final_total_cents || 0) / 100).toLocaleString()) + '</span>';
        rows.appendChild(est);
      }}
      if (sec) sec.style.display = 'block';
    }}

    // Load Stripe.js when a publishable key is available
    if (STRIPE_PK) {{
      var s = document.createElement('script');
      s.src = 'https://js.stripe.com/v3/';
      s.onload = function() {{
        stripe = window.Stripe(STRIPE_PK);
        document.getElementById('demo-payment-hint').style.display = 'none';
        document.getElementById('demo-mode-label').textContent = 'Secured by Stripe — your card is tokenized, never stored.';
      }};
      document.head.appendChild(s);
    }}

    var form = document.getElementById('checkout-form');
    var errorDiv = document.getElementById('form-error');
    var submitBtn = document.getElementById('submit-btn');
    var btnLabel = document.getElementById('btn-label');

    function showError(msg) {{
      if (errorDiv) {{ errorDiv.textContent = msg; errorDiv.style.display = 'block'; }}
    }}
    function setLoading(v) {{
      if (submitBtn) submitBtn.disabled = v;
      if (btnLabel) btnLabel.innerHTML = v ? '<span class="spinner"></span>Processing\u2026' : 'Place Order';
    }}
    function showSuccess(orderId) {{
      var wrap = document.getElementById('checkout-form-wrap');
      var box = document.getElementById('success-box');
      var bl = document.getElementById('back-link-form');
      if (wrap) wrap.style.display = 'none';
      if (box) box.style.display = 'block';
      if (bl) bl.style.display = 'none';
      var oid = document.getElementById('order-id-display');
      if (oid) oid.textContent = 'Order #' + orderId;
      try {{ sessionStorage.removeItem('shopsquire_checkout_cart'); }} catch(e) {{}}
    }}

    if (form) {{
      form.addEventListener('submit', function(e) {{
        e.preventDefault();
        if (errorDiv) errorDiv.style.display = 'none';
        var name = document.getElementById('inp-name').value.trim();
        var email = document.getElementById('inp-email').value.trim();
        var addr = document.getElementById('inp-addr').value.trim();
        if (!name || !email || !addr) {{
          showError('Please fill in all required fields.');
          return;
        }}
        if (!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email)) {{
          showError('Please enter a valid email address.');
          return;
        }}
        setLoading(true);
        var amountCents = (cartSummary && cartSummary.bundle_savings && cartSummary.bundle_savings.final_total_cents)
          ? cartSummary.bundle_savings.final_total_cents
          : ((cartSummary && cartSummary.subtotal_cents) ? cartSummary.subtotal_cents : 0);
        fetch('/api/v1/payments/checkout-initiate', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            amount_cents: amountCents,
            currency: (cartSummary && cartSummary.currency) || 'USD',
            customer_name: name,
            customer_email: email,
            shipping_address: addr,
            cart_id: (cartSummary && cartSummary.cart_id) || null
          }})
        }})
        .then(function(r) {{ return r.json().then(function(d) {{ return {{ok: r.ok, data: d}}; }}); }})
        .then(function(res) {{
          if (!res.ok) {{
            showError((res.data && res.data.detail) || 'Checkout failed. Please try again.');
            setLoading(false);
            return;
          }}
          showSuccess(res.data.order_id || 'DEMO');
          setLoading(false);
        }})
        .catch(function() {{
          showError('Network error. Please check your connection and try again.');
          setLoading(false);
        }});
      }});
    }}
  </script>
</body>
</html>"""
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
    specs = _coerce_specs(p.get("specs") if isinstance(p, dict) else None)

    def spec_row(label: str, value: str | None) -> str:
        return f"<tr><th style='text-align:left;width:160px'>{label}</th><td>{value or '?'}" + "</td></tr>"

    def find_feat(key: str) -> str | None:
        for f in feats:
            if key.lower() in f.lower():
                return f
        return None

    def _spec_value(*keys: str) -> str | None:
        for k in keys:
            value = specs.get(k)
            if value:
                if isinstance(value, list):
                    return ", ".join([str(v) for v in value if v])
                return str(value)
        return None

    spec_rows = "".join(
        [
            spec_row("CPU", _spec_value("cpu") or find_feat("cpu")),
            spec_row("GPU", _spec_value("graphics", "gpu") or find_feat("graphics") or find_feat("gpu")),
            spec_row("RAM", _spec_value("ram") or (f"{specs.get('ram_gb')}GB" if specs.get("ram_gb") else None) or find_feat("ram")),
            spec_row("Storage", _spec_value("storage", "ssd") or find_feat("storage")),
            spec_row("Wi-Fi", _spec_value("wifi") or find_feat("wi-fi")),
            spec_row("Ports", _spec_value("ports") or find_feat("ports")),
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
