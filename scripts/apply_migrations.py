import os
import sys


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set")
        return 2

    try:
        from alembic.config import Config
        from alembic import command
    except Exception as exc:
        print(f"Alembic not installed: {exc}")
        return 3

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    print(f"Applying Alembic migrations to head (DATABASE_URL={db_url})")
    command.upgrade(cfg, "head")
    print("Done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
