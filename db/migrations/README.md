## Legacy SQL migrations (reference only)

This repository uses **Alembic** (`alembic/versions/`) as the **only** source of truth for the OLTP schema.

The `.sql` files in this folder are kept for historical/reference purposes (and for optional TimescaleDB
examples), but they are **not** applied by default in CI/CD or at runtime.

If you need TimescaleDB helpers, prefer `db/timescale/` and `scripts/timescale_init.py`.

