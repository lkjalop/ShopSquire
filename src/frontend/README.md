# Frontend ownership

Paths are relative to the repository root.

Supported surfaces:

- Storefront: `frontend/` (Vite on `127.0.0.1:5173`).
- Admin: `src/frontend/admin-react/` (Vite on `127.0.0.1:3001`).

`src/frontend/storefront-react/` contains archived reference source. Its install/build manifests have been retired; do not restore it as a second supported app. New features, fixes and CI/release wiring belong in the two supported surfaces. Historical references are preserved in Git history.
