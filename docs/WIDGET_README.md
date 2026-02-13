# ShopSquire Widget (Web Component)

Embed on any storefront:

```html
<script src="https://cdn.shopsquire.dev/widget.js" defer></script>
<shopsquire-widget></shopsquire-widget>
<script>
  // Initialize API base and uid (session/user id)
  window.ShopSquireWidget.init({ apiBase: 'https://api.shopsquire.dev', uid: 'user-123' });
  // The widget calls GET /api/v1/recommend/suggest?uid=&query=...
</script>
```

Local demo (no build step):
- Open src/frontend/widget/demo.html in your browser.

Features in this MVP:
- Floating action button → fullscreen overlay on mobile, panel on desktop.
- Parse simple constraints (top N, price range, RAM ≥N).
- Show 5 product cards with Add, Details, Compare, Why recommended.
- Cart overlay with accessory upsells, subtotal/tax/total.
- Discount requests (pending → approved/denied states).
- Malicious input handling: NFKC normalization, control char stripping, friendly restricted notice.

Notes:
- The widget now calls the FastAPI recommend endpoint (GET /api/v1/recommend/suggest).
- If the backend is unreachable, it falls back to local mock recommendations.
- Cart operations remain local in this MVP; wire to backend later as needed.
