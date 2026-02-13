"""Compatibility UI router.

The project has a richer UI implementation in `ui_storefront.py`. Historically,
`main.py` preferred that router and fell back to `ui.py` if unavailable.

This file re-exports `ui_storefront.router` when present so `/ui/*` routes remain
available even if import order changes, and keeps a tiny fallback index if not.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

try:
    from src.app.routers.ui_storefront import router as router  # type: ignore
except Exception:
    router = APIRouter(prefix="/ui", tags=["ui"])

    @router.get("/")
    def index() -> HTMLResponse:
        html = """
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>ShopSquire</title>
          <style>
            body { font-family: system-ui, sans-serif; margin: 0; padding: 0; }
            header { padding: 12px; background: #111; color: #fff; }
            main { padding: 12px; }
            .card { border: 1px solid #eee; border-radius: 8px; padding: 12px; margin: 8px 0; }
          </style>
        </head>
        <body>
          <header>ShopSquire</header>
          <main>
            <div class="card">
              <h2>UI routes unavailable</h2>
              <p>The richer UI router could not be imported. Check server logs.</p>
            </div>
          </main>
        </body>
        </html>
        """
        return HTMLResponse(content=html)

