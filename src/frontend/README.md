# Frontend Ownership

Supported surfaces:
- Storefront: `C:\AI\ShopSquire\frontend` (Vite on `127.0.0.1:5173`)
- Admin: `C:\AI\ShopSquire\src\frontend\admin-react` (Vite on `localhost:3001`)

Archived surface:
- `C:\AI\ShopSquire\src\frontend\storefront-react` is deprecated and script-locked.

Policy:
- New features and bug fixes must only land in the supported surfaces.
- Keep deprecated storefront code for reference only; do not wire it into CI or release flows.
