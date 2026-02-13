# DB Setup (Alembic-first)

ShopSquire uses **Alembic** as the schema source of truth. SQLite remains supported for lightweight local tests.

## Local dev (Docker Postgres)

1) Start Postgres (and Redis if needed):

```bash
docker compose up -d db redis
```

2) Apply migrations (choose one):

```bash
# Poetry (recommended if you use Poetry for deps)
poetry run alembic -c alembic.ini upgrade head
```

```powershell
# Windows PowerShell helper (uses .venv\Scripts\alembic.exe or `poetry run`)
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/shopsquire"
.\scripts\apply_migrations.ps1
```

3) Run tests:

```bash
poetry run pytest -q
```

## Optional: TimescaleDB

Only use TimescaleDB if you need hypertables / continuous aggregates.

1) Start TimescaleDB (drop-in override):

```bash
# First time only: use a fresh volume (Timescale requires the extension at init)
docker compose down -v
docker compose -f docker-compose.yml -f docker-compose.timescaledb.yml up -d db
```

2) Apply Alembic migrations:

```bash
poetry run alembic -c alembic.ini upgrade head
```

3) (Optional) Apply Timescale helper SQL:

```bash
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/shopsquire"
python scripts/timescale_init.py
```

