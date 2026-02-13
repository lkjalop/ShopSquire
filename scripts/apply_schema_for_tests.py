import os
from sqlalchemy import create_engine, text

def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("No DATABASE_URL set; skipping schema apply")
        return
    print(f"Applying schema to {db_url}")
    engine = create_engine(db_url, future=True)
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'schema.sql')
    schema_path = os.path.abspath(schema_path)
    with open(schema_path, 'r', encoding='utf-8') as f:
        sql = f.read()

    # If using sqlite, do a few best-effort conversions from Postgres DDL to SQLite
    if 'sqlite' in db_url:
        import re

        # Replace JSONB with TEXT
        sql = re.sub(r"\bJSONB\b", "TEXT", sql, flags=re.IGNORECASE)
        # Replace TIMESTAMPTZ with TEXT
        sql = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", sql, flags=re.IGNORECASE)
        # Replace UUID primary keys with TEXT
        sql = re.sub(r"\bUUID\b", "TEXT", sql, flags=re.IGNORECASE)
        # Replace now() with CURRENT_TIMESTAMP
        sql = re.sub(r"\bnow\s*\(\s*\)\b", "CURRENT_TIMESTAMP", sql, flags=re.IGNORECASE)
        # Replace boolean types and defaults
        sql = re.sub(r"\bBOOLEAN\b", "INTEGER", sql, flags=re.IGNORECASE)
        sql = re.sub(r"DEFAULT\s+FALSE", "DEFAULT 0", sql, flags=re.IGNORECASE)
        sql = re.sub(r"DEFAULT\s+TRUE", "DEFAULT 1", sql, flags=re.IGNORECASE)
        # Replace PostgreSQL-style DECIMAL with REAL
        sql = re.sub(r"DECIMAL\s*\([^)]*\)", "REAL", sql, flags=re.IGNORECASE)
        # Remove Postgres-specific ON DELETE/REFERENCES clauses (best-effort)
        sql = re.sub(r"REFERENCES\s+\w+\s*\([^)]*\)\s*(ON\s+DELETE\s+[^,\n)]*)?", "", sql, flags=re.IGNORECASE)
        # Replace DEFAULT 'infinity' with NULL (no equivalent in sqlite)
        sql = re.sub(r"DEFAULT\s+'infinity'", "DEFAULT NULL", sql, flags=re.IGNORECASE)
        # Remove double precision casting or type casts
        sql = re.sub(r"::\w+", "", sql)
        # Remove PostgreSQL-style CREATE INDEX CONCURRENTLY or similar (no-op)
        sql = re.sub(r"CONCURRENTLY", "", sql, flags=re.IGNORECASE)
    statements = [s.strip() for s in sql.split(';') if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                # continue on errors; schema may already exist
                print(f"Warning applying statement: {e}")

if __name__ == '__main__':
    main()
