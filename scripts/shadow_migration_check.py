"""Shadow migration checker (sanity-focused).

Alembic is the schema source of truth. This script validates:
  1) the database is upgraded to Alembic head
  2) required tables/columns exist (fast, low-noise)

Usage:
  python scripts/shadow_migration_check.py --db-url <DATABASE_URL>
"""
import argparse
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy import inspect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", required=False, help="Database URL to check against")
    args = parser.parse_args()
    db_url = args.db_url or os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL required")
        sys.exit(2)

    if str(db_url).lower().startswith("sqlite"):
        print("SQLite DATABASE_URL detected; skipping Alembic head check.")
        sys.exit(0)

    # 1) Ensure DB is at Alembic head
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
    except Exception as exc:
        print(f"Failed to load Alembic config: {exc}")
        sys.exit(3)

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    except Exception as exc:
        print(f"Failed to read Alembic current revision: {exc}")
        sys.exit(3)

    if head and current != head:
        print(f"Database is not at Alembic head: current={current!r} head={head!r}")
        sys.exit(4)

    # 2) Minimal schema invariants (low-noise)
    insp = inspect(engine)

    def _find_schema(table_name: str) -> str | None:
        # Try common schemas first, then fall back to enumerating schemas.
        for schema in (None, "public", "oltp", "audit", "security"):
            try:
                if insp.has_table(table_name, schema=schema):
                    # `None` means "default schema"; returning `None` would be
                    # indistinguishable from "not found" to our callers.
                    return "" if schema is None else schema
            except Exception:
                continue
        try:
            for schema in insp.get_schema_names() or []:
                if schema in ("information_schema", "pg_catalog"):
                    continue
                try:
                    if insp.has_table(table_name, schema=schema):
                        return schema
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _colset(table_name: str, schema: str | None) -> set[str]:
        schema_arg = None if schema == "" else schema
        cols = insp.get_columns(table_name, schema=schema_arg)
        return {c.get("name") for c in cols if c and c.get("name")}

    required_tables: dict[str, set[str]] = {
        "evidence_bundles": {"id", "case_id", "bundle_json", "created_at"},
        "human_review_tasks": {"id", "case_id", "decision_id", "ticket_id", "status", "reviewer_id", "rationale", "created_at", "updated_at"},
        "inventory_atp_fact": {
            "id", "tenant_id", "deduplication_id", "sku", "location_id",
            "confirmed_quantity", "source_system", "observed_at", "status",
        },
        "marketing_event_fact": {
            "id", "tenant_id", "deduplication_id", "event_type", "sku",
            "consent_state", "source_system", "occurred_at", "status",
        },
        "forecast_actual_pair": {
            "id", "tenant_id", "pair_key", "subject_id", "forecast_value",
            "actual_value", "model_id", "model_version", "sealed_by", "status",
        },
        "executive_metric_snapshot": {
            "id", "tenant_id", "metric_name", "subject_type", "subject_id",
            "status", "definition_version", "visibility",
        },
    }

    failures: list[str] = []
    for table_name, required_cols in required_tables.items():
        schema = _find_schema(table_name)
        if schema is None:
            failures.append(f"missing table: {table_name}")
            continue
        cols = _colset(table_name, schema=schema)
        missing = sorted([c for c in required_cols if c not in cols])
        if missing:
            failures.append(f"{table_name} missing columns: {', '.join(missing)} (schema={schema or 'default'})")

    if failures:
        print("Shadow migration check failed:")
        for f in failures:
            print(" -", f)
        sys.exit(4)

    print("Shadow migration check passed (required tables/columns present).")
    sys.exit(0)


if __name__ == '__main__':
    main()
