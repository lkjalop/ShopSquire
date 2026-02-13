# Frontend Quickstart

This repo includes a minimal, static scaffold for:
- Customer widget (Web Component) demo: src/frontend/widget/demo.html
- Admin dashboard shell: src/frontend/admin/index.html

Run locally
- Open the HTML files directly in your browser, or serve the `src/frontend` directory with any static server.

Examples (PowerShell):
```powershell
# Serve with Python (if available)
python -m http.server 8080 -d "D:\AI\agentLumen\ShopSquire\src\frontend"

# Or open files directly
Start-Process "D:\AI\agentLumen\ShopSquire\src\frontend\widget\demo.html"
Start-Process "D:\AI\agentLumen\ShopSquire\src\frontend\admin\index.html"
```

Next steps
- Replace mock recommendation with backend POST /api/v1/chat/recommend.
- Add WebSocket for live activity feed.
- Scaffold React admin later for richer UX; this static shell mirrors flows and can be ported.
