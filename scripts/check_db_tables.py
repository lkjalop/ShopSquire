#!/usr/bin/env python3
"""Verify required database tables exist.

Run this BEFORE implementing changes to verify schema is ready.

Usage:
    python scripts/check_db_tables.py

If tables are missing, run:
    alembic upgrade head
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from sqlalchemy import text, inspect
    from src.app.models.db import db_session
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're in the project root and dependencies are installed.")
    sys.exit(1)


REQUIRED_TABLES = [
    # Core tables
    "products",
    "inventory",
    "customers",
    "orders",
    # Decision/Audit tables
    "decision_logs",
    "decision_trace_events",
    # Fraud/Security tables
    "fraud_image_hashes",
    "tickets",
    # Supplier tables
    "suppliers",
    "supplier_products",
    "purchase_orders",
    # Feature flags
    "feature_flags",
]

OPTIONAL_TABLES = [
    # These may not exist in all environments
    "idempotency_keys",
    "session_memory",
    "api_keys",
    "tenants",
    "ragas_evaluations",
]


def check_tables():
    """Check if required tables exist."""
    print("\n" + "=" * 60)
    print("  ShopSquire Database Table Check")
    print("=" * 60 + "\n")

    try:
        with db_session() as db:
            # Get database URL (sanitized)
            bind = db.get_bind()
            db_url = str(bind.url)
            # Hide password if present
            if "@" in db_url:
                parts = db_url.split("@")
                db_url = parts[0].split(":")[0] + ":****@" + parts[1]
            print(f"Database: {db_url}\n")

            inspector = inspect(bind)
            existing = set(inspector.get_table_names())

            print("Required Tables:")
            missing_required = []
            for table in REQUIRED_TABLES:
                if table in existing:
                    print(f"  [OK] {table}")
                else:
                    print(f"  [!!] {table} - MISSING")
                    missing_required.append(table)

            print("\nOptional Tables:")
            for table in OPTIONAL_TABLES:
                if table in existing:
                    print(f"  [OK] {table}")
                else:
                    print(f"  [--] {table} - not present (optional)")

            print("\n" + "-" * 60)

            if missing_required:
                print(f"\nMissing required tables: {missing_required}")
                print("\nTo fix, run:")
                print("  alembic upgrade head")
                print("\nOr for test environment:")
                print("  python scripts/apply_schema_for_tests.py")
                return 1
            else:
                print("\nAll required tables exist! Ready for implementation.")
                return 0

    except Exception as e:
        print(f"\nDatabase connection error: {e}")
        print("\nMake sure:")
        print("  1. PostgreSQL is running, OR")
        print("  2. DATABASE_URL is set for SQLite (testing)")
        print("\nExample for testing:")
        print("  export DATABASE_URL=sqlite:///test.sqlite")
        return 1


def check_decision_trace_columns():
    """Verify decision_trace_events has required columns."""
    print("\nDecision Trace Schema Check:")

    required_columns = ["id", "trace_id", "event_type", "source_type", "payload", "created_at"]

    try:
        with db_session() as db:
            inspector = inspect(db.get_bind())
            if "decision_trace_events" not in inspector.get_table_names():
                print("  [!!] Table does not exist")
                return

            columns = {c["name"] for c in inspector.get_columns("decision_trace_events")}

            for col in required_columns:
                if col in columns:
                    print(f"  [OK] {col}")
                else:
                    print(f"  [!!] {col} - MISSING")

    except Exception as e:
        print(f"  Error checking columns: {e}")


if __name__ == "__main__":
    exit_code = check_tables()
    check_decision_trace_columns()
    sys.exit(exit_code)
