# ShopSquire Frontend (Mobile-first React + CSS Modules)

- Dev server: Vite React on port 3000 (proxy to backend 8081)
- Styling: CSS Modules (no Tailwind)
- Data: Consumes `/ui/products.json` and `/api/v1/decisions/{trace_id}`

## Quick start

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and:
- Use the header input or "Ask AI" to open the chat and run queries.
- Compare mode triggers on queries with "compare" or when multiple results.
- Click the gear (in a real flow) to open the Decision Trace; this demo fetches `/api/v1/decisions/{trace_id}`.

## Config
- Vite dev proxy forwards `/api` and `/ui` to the backend at http://127.0.0.1:8081.

## Notes
- MVP uses client-side filtering for demo queries; wire to `/api/v1/chat/query` when available.
- Decision trace endpoint is implemented in backend `src/app/routers/decisions.py`.
