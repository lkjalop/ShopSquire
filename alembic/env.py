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
fileConfig(config.config_file_name, disable_existing_loggers=False)

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


def assert_preserving_downgrade(current_heads, connection):
    """Reject protected plans before SQLite can commit any destructive DDL."""
    from alembic.script import ScriptDirectory
    from alembic.script.revision import RangeNotAncestorError
    from alembic.util import CommandError

    if not current_heads:
        return
    try:
        destination = context.get_revision_argument()
    except KeyError:
        # Read-only commands such as current/check do not supply a destination.
        # They must inspect populated history without inventing a downgrade.
        return
    script = ScriptDirectory.from_config(config)
    try:
        planned = list(script.iterate_revisions(
            current_heads, destination, select_for_downgrade=True,
        ))
    except RangeNotAncestorError:
        # The destination is newer than the database: this is an upgrade.
        return
    protected = [revision.revision for revision in planned
                 if getattr(revision.module, 'preserve_history_on_downgrade', False)]
    if protected:
        raise CommandError('Downgrade requires a reviewed data-preserving recovery plan; '
                           'no downgrade steps started. Protected revisions: ' + ', '.join(protected))
    # Applied revisions remain frozen. Protect populated reversible tails here,
    # before SQLite can commit any earlier DROP TABLE in a multi-step plan.
    from sqlalchemy import inspect, text
    history = {
        '20260894_supplier_enquiry_drafts': ('supplier_enquiry_draft',),
        '20260892_buyer_supplier_selection': ('buyer_supplier_quote_selection',),
        '20260891_governed_product_offers': ('governed_product_offer',),
        '20260890_supplier_enquiry_journey': ('supplier_enquiry_request', 'supplier_enquiry_reply',
                                             'person_effect_case_binding'),
    }
    schema = inspect(connection)
    for revision in planned:
        for table in history.get(revision.revision, ()):
            if schema.has_table(table) and connection.execute(text(f'SELECT 1 FROM {table} LIMIT 1')).first():
                raise CommandError('Downgrade would remove communication or approval history; '
                                   'no downgrade steps started. Restore a reviewed backup. Table: ' + table)


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
            assert_preserving_downgrade(context.get_context().get_current_heads(), connection)
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
