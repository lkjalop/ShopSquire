# Alembic Quickstart (Optional)

This repository includes raw SQL migrations for immediate needs. If you prefer managed migrations, use Alembic.

## Setup

1. Install Alembic:
   ```bash
   pip install alembic
   ```
2. Initialize in the repo (once):
   ```bash
   alembic init alembic
   ```
3. Configure `alembic.ini` and `alembic/env.py`:
   - Set `sqlalchemy.url` to your database (e.g., `sqlite:///./dev.sqlite` or Postgres URL).
   - In `env.py`, import your models/metadata, e.g.:
     ```python
     from src.app.models.sa_models import Base  # if defined
     target_metadata = Base.metadata
     ```

## Create a Revision

```bash
alembic revision -m "add policygraph tables"
```

Edit the generated script to add tables (or use autogenerate if models exist):
```bash
alembic revision --autogenerate -m "sync schema"
```

## Apply Migrations

```bash
alembic upgrade head
```

## Notes

- Autogenerate requires SQLAlchemy models; current repo uses DDL SQL for many tables, so manual scripting may be preferred.
- Keep test DB separate from dev/prod.
- For TimescaleDB, include extension creation in migrations:
  ```sql
  CREATE EXTENSION IF NOT EXISTS timescaledb;
  SELECT create_hypertable('dl_timeseries','time');
  ```
