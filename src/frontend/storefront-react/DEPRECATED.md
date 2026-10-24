# Archived storefront source

Use `frontend/` as the single supported storefront and `src/frontend/admin-react/` for administration.

This directory retains historical source only. Its obsolete `package.json` and `package-lock.json` were retired on 25 October 2026, removing the unsupported install/build dependency tree. Do not reinstall it, add features or wire it into CI/release flows.

The prior manifests remain in Git history at repair commit `f83c072d`; their removal does not claim that the archived source was modernized or production-qualified. The active [storefront package](../../../frontend/package.json) and [admin package](../admin-react/package.json) own current dependencies.
