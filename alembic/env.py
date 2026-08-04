from __future__ import annotations

from logging.config import fileConfig
import os
import sys
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# The installed ``alembic.exe`` starts with its Scripts directory on
# ``sys.path``.  Add the repository root before importing application settings;
# otherwise DATABASE_URL resolution silently falls through and the placeholder
# in alembic.ini reaches ConfigParser unchanged.
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# Prefer DATABASE_URL from environment or application settings
db_url = os.getenv("DATABASE_URL")
if not db_url:
    try:
        from src.app.config import get_settings
        db_url = get_settings().database_url
    except Exception:
        db_url = None

if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# add your model's MetaData object here for 'autogenerate' support
target_metadata = None

# Try to import SQLAlchemy Base metadata for autogenerate
for import_path in (
    "src.app.models.orm",
    "app.models.orm",
    "models.orm",
):
    try:
        module = __import__(import_path, fromlist=["Base"])
        _Base = getattr(module, "Base", None)
        if _Base is not None:
            target_metadata = getattr(_Base, "metadata", None)
            if target_metadata is not None:
                break
    except Exception:
        continue


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    hooks_enabled = os.getenv("ALEMBIC_HOOKS_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

    with connectable.connect() as connection:
        # Run pre-migration hook if present
        try:
            if hooks_enabled:
                import subprocess
                pre = os.path.join(os.path.dirname(__file__), "pre_migration_hook.sh")
                if os.path.exists(pre) and os.access(pre, os.X_OK):
                    subprocess.run([pre], check=False)
        except Exception:
            pass
        # Pin migrations to the public schema so all Alembic-managed tables land
        # in a predictable location regardless of role search_path defaults.
        # (Runtime engine sets search_path=oltp,audit,security,public via connect
        # event; Alembic uses a separate NullPool connection and must be anchored
        # explicitly. The oltp schema is used only for product_embeddings which
        # are fully schema-qualified in their migration.)
        try:
            from sqlalchemy import text as _alembic_text
            if connection.dialect.name != "sqlite":
                connection.execute(_alembic_text("SET search_path TO public"))
                # SQLAlchemy 2.x autobegins on SET. Commit that configuration
                # transaction before Alembic opens its managed migration
                # transaction; otherwise all migration DDL is rolled back when
                # the connection closes even though `upgrade head` exits zero.
                connection.commit()
        except Exception:
            pass
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()
        # Run post-migration hook if present
        try:
            if hooks_enabled:
                import subprocess
                post = os.path.join(os.path.dirname(__file__), "post_migration_hook.sh")
                if os.path.exists(post) and os.access(post, os.X_OK):
                    subprocess.run([post], check=False)
        except Exception:
            pass


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
