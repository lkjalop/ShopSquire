import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "schema.sql"
BACKUP = ROOT / "db" / "schema.sql.bak"

def convert(sql: str) -> str:
    # Basic, best-effort conversions from Postgres -> SQLite
    out = sql
    # Remove PostgreSQL-specific extension/role statements
    out = re.sub(r"(?mi)^\s*CREATE EXTENSION.*?;\s*", "", out)
    out = re.sub(r"(?mi)^\s*COMMENT ON .*?;\s*", "", out)
    out = re.sub(r"(?mi)^\s*ALTER TABLE .*? OWNER TO .*?;\s*", "", out)

    # Replace types
    out = re.sub(r"\bUUID\b", "TEXT", out)
    out = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", out, flags=re.IGNORECASE)
    out = re.sub(r"\bTIMESTAMP WITH TIME ZONE\b", "TEXT", out, flags=re.IGNORECASE)
    out = re.sub(r"\bSERIAL\b", "INTEGER", out, flags=re.IGNORECASE)
    out = re.sub(r"\bBIGSERIAL\b", "INTEGER", out, flags=re.IGNORECASE)
    out = re.sub(r"\bJSONB\b", "TEXT", out, flags=re.IGNORECASE)
    out = re.sub(r"\bBOOLEAN\b", "INTEGER", out, flags=re.IGNORECASE)

    # Replace default functions
    out = re.sub(r"\bnow\s*\(\s*\)", "CURRENT_TIMESTAMP", out, flags=re.IGNORECASE)

    # Remove type casts like ::text
    out = re.sub(r"::\w+", "", out)

    # Remove USING clauses in alter statements (best-effort)
    out = re.sub(r"USING\s+[^;\n]+", "", out, flags=re.IGNORECASE)

    # Replace boolean literals
    out = re.sub(r"\btrue\b", "1", out, flags=re.IGNORECASE)
    out = re.sub(r"\bfalse\b", "0", out, flags=re.IGNORECASE)

    # Remove unsupported Postgres table or index options
    out = re.sub(r"WITH \(.*?\)", "", out, flags=re.IGNORECASE)

    # Remove sequences and ownership lines
    out = re.sub(r"(?mi)^\s*CREATE SEQUENCE .*?;\s*", "", out)
    out = re.sub(r"(?mi)^\s*ALTER SEQUENCE .*?;\s*", "", out)

    return out


def main():
    if not SCHEMA.exists():
        print("schema.sql not found; nothing to do")
        return
    sql = SCHEMA.read_text(encoding="utf-8")
    new_sql = convert(sql)
    # Backup original
    if not BACKUP.exists():
        SCHEMA.replace(BACKUP)
        SCHEMA.write_text(new_sql, encoding="utf-8")
        print(f"Backed up original schema to {BACKUP} and wrote converted schema")
    else:
        # Overwrite schema with converted each run
        SCHEMA.write_text(new_sql, encoding="utf-8")
        print(f"Overwrote schema.sql with converted SQLite-compatible SQL")


if __name__ == "__main__":
    main()
