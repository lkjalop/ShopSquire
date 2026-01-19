from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/")
def index() -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang=\"en\">
    <head>
      <meta charset=\"utf-8\">
      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
      <title>ShopSquire</title>
      <style>
        body { font-family: system-ui, sans-serif; margin: 0; padding: 0; }
        header { padding: 12px; background: #111; color: #fff; }
        main { padding: 12px; }
        .card { border: 1px solid #eee; border-radius: 8px; padding: 12px; margin: 8px 0; }
        @media (min-width: 768px) { .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; } }
      </style>
    </head>
    <body>
      <header>ShopSquire</header>
      <main>
        <div class=\"grid\">
          <div class=\"card\">
            <h2>Session Summary</h2>
            <p>Use /api/v1/session/{uid}/summary</p>
          </div>
          <div class=\"card\">
            <h2>Pricing</h2>
            <p>Try /api/v1/pricing/suggest?uid=u1&cart_total_cents=12000</p>
          </div>
        </div>
      </main>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
