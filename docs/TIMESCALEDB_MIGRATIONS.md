# TimescaleDB Migrations

This project includes TimescaleDB migrations to create hypertables and example continuous aggregates for decision logs and security events.

Prerequisites:
- A PostgreSQL instance with the TimescaleDB extension available.
- `DATABASE_URL` set to your Postgres connection string (e.g., `postgresql+psycopg2://user:pass@host:5432/db`).

Apply migrations:

1. Ensure the TimescaleDB extension is installed and enabled for your database.
   - If you're using Docker locally, you can use the drop-in override: `docker-compose.timescaledb.yml`.
   - Note: switching an existing `pgdata` volume from Postgres to Timescale is not recommended; use a fresh volume.
2. Apply Alembic migrations first (Alembic is the schema source of truth):

```bash
poetry run alembic -c alembic.ini upgrade head
```

3. Run the init script (optional):

```bash
# Windows PowerShell
$env:DATABASE_URL = "postgresql+psycopg2://user:pass@localhost:5432/shopsquire"
python scripts/timescale_init.py
```

Files applied:
- `db/timescale/002_hypertables.sql`
- `db/timescale/003_continuous_aggregates.sql`

Validation:

- Check hypertables:
```sql
SELECT hypertable_name, table_name FROM timescaledb_information.hypertables;
```
- Check continuous aggregates:
```sql
SELECT view_name FROM timescaledb_information.continuous_aggregates;
```

Notes:
- The script attempts `CREATE EXTENSION IF NOT EXISTS timescaledb` — ensure your role has privileges.
- The SQL files in `db/timescale/*.sql` are examples and may need adjustment (schema qualification) depending on your deployment.
- To customize policies, edit the SQL in the migrations folder.
