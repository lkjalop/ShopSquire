# ShopSquire Admin (React + Vite + TS)

Minimal scaffold mirroring Overview/Decisions/Security/Approvals.

## Setup

From the repository root:

```powershell
Set-Location src/frontend/admin-react
npm ci
$env:VITE_API_BASE = 'http://127.0.0.1:8080'
npm run dev
```

Open http://127.0.0.1:3001. This configures an API origin; authenticated operator access still requires the declared deployment/session setup. Do not place owner secrets in a buyer bundle.

Ownership:

- Supported storefront: `frontend/`.
- Supported admin: `src/frontend/admin-react/`.
- Historical source only: `src/frontend/storefront-react/`; its obsolete install manifests are retired.

## Notes
- Decisions and Approvals are wired to FastAPI endpoints.
- Security Events page is wired to /api/v1/admin/security/events.
- Ported flows from static shell and recommendation/security docs.
- Add charts/tables libraries (Recharts, TanStack Table) as next step.
