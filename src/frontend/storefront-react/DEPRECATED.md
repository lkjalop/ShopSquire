This storefront is deprecated.

Use `frontend/` as the single supported storefront codepath.

Migration notes:
- Supported app: `frontend/src/App.tsx`
- Active admin app: `src/frontend/admin-react/`
- Legacy app here is archived for reference only.
- Package scripts in this folder are intentionally locked and exit with an error.
- Do not add new features, bug fixes, or CI wiring under `src/frontend/storefront-react/`.
