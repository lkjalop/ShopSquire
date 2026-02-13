# ShopSquire Admin (React + Vite + TS)

Minimal scaffold mirroring Overview/Decisions/Security/Approvals.

## Setup

```powershell
cd D:\AI\agentLumen\ShopSquire\src\frontend\admin-react
npm install
set VITE_API_BASE=http://localhost:8080
npm run dev
```

Open http://localhost:5173 (the app will call FastAPI at %VITE_API_BASE%)

## Notes
- Decisions and Approvals are wired to FastAPI endpoints.
- Security Events page is wired to /api/v1/admin/security/events.
- Ported flows from static shell and recommendation/security docs.
- Add charts/tables libraries (Recharts, TanStack Table) as next step.
