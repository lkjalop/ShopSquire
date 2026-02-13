# ShopSquire Frontend Handoff

Single source of truth (homepage + chat overlay):
- `src/frontend/storefront-react/src/App.jsx`

Styles:
- `src/frontend/storefront-react/src/styles.css`

API host:
- `VITE_API_BASE` env var (preferred)
- Default: `http://localhost:8000/api/v1`
- If API runs on `http://localhost:8080`, set:
  - `VITE_API_BASE=http://localhost:8080/api/v1`

---

## Agreed Wireframes (ASCII)

### A) Homepage + Floating Chat Launcher
+--------------------------------------------------------------------------------+
| ShopSquire                                                      [Search] [Cart] |
+--------------------------------------------------------------------------------+
| Hero banner / category title                                                    |
|                                                                                |
| Filters                 Product Grid (35+)                                      |
| +------------+       +-----------+ +-----------+ +-----------+                  |
| | Price      |       | Card 1    | | Card 2    | | Card 3    |                  |
| | RAM        |       +-----------+ +-----------+ +-----------+                  |
| | GPU        |       +-----------+ +-----------+ +-----------+                  |
| | Stock      |       | Card 4    | | Card 5    | | Card 6    |                  |
| +------------+       +-----------+ +-----------+ +-----------+                  |
|                                                                                |
|                                                       (Floating Chat Button)   |
|                                                                [?]             |
+--------------------------------------------------------------------------------+

### B) Chat Overlay (modal / slide-over) with Right Panel
+--------------------------------------------------------------------------------+
| ShopSquire Assistant                      [Gear] [Close]                        |
+--------------------------------------------------------------------------------+
| Chat (left 30%)                     Right Panel (40%)                           |
| +------------------+               +--------------------------------------+      |
| | user/assistant   |               | Products / List / Compare            |      |
| | messages         |               | (scrollable content)                 |      |
| |                  |               |                                      |      |
| +------------------+               +--------------------------------------+      |
| [camera] [input...............] [mic] [send]                                   |
+--------------------------------------------------------------------------------+

### C) Right Panel Modes

Grid (price range):
+----------------------------------------+
| Products (Grid)                        |
| [Card] [Card] [Card]                   |
| [Card] [Card] [Card]                   |
| [Card] [Card] [Card]                   |
+----------------------------------------+

List (details/specs):
+----------------------------------------+
| Product List                           |
| [Img]  Name + Specs + Price            |
| [Img]  Name + Specs + Price            |
| [Img]  Name + Specs + Price            |
+----------------------------------------+

Compare:
+----------------------------------------+
| Comparison Table                       |
| Product | Price | Key Specs            |
| ...                                    |
+----------------------------------------+

---

## Behavior Rules (Agreed)

### Right Panel Mode Selection
- Compare intent: query contains `compare`, `vs`, `versus`
  - Mode: `compare`
- Detailed request: query contains `detail`, `details`, `specs`, `list`
  - Mode: `list`
- Price range: query contains `price`, `under`, `below`, `$X - $Y`, `between X and Y`
  - Mode: `grid`
- Default: `grid`

Backend can override with:
- `view_mode`
- `view_reason`

### Responsive Grid Layout
- >= ~1280px: 3 columns x 4 rows visible (3x4)
- 1024-1279px: 3 columns x 3 rows visible (3x3)
- < 1024px: 2 columns

---

## Decision Trace (Gear)

### Where it appears
- Gear icon in chat overlay header
- Top-bar gear appears only if a trace exists

### Why it might look empty
- `lastTrace` is only set after `/api/v1/recommend/suggest` returns
- If API host is wrong or request fails, trace stays empty

---

## CV Upload Flow

1) User attaches images via camera icon
2) On send, form POST to:
   - `/api/v1/support/complaints/submit`
3) Right panel switches to CV Analysis
4) Status card shows case_id, confidence, severity, decision
5) Polling pulls `/api/v1/support/complaints/{case_id}/status`

---

## Backend Connectors
- Recommendations: `GET /api/v1/recommend/suggest?uid=&query=`
- Decision trace: `GET /api/v1/decisions/{trace_id}`
- Product detail: `GET /api/v1/products/{sku}`
- Cart: `/api/v1/cart/*`
- CV complaints: `/api/v1/support/complaints/submit`

---

## Files to Edit
Homepage + chat overlay:
- `src/frontend/storefront-react/src/App.jsx`

Styles (if needed):
- `src/frontend/storefront-react/src/styles.css`
