"""In-process migrations must not silence already-created application loggers."""
import logging
from alembic import command
from alembic.config import Config


def test_migration_retains_application_failure_logging(tmp_path,monkeypatch,caplog):
    database='sqlite:///'+(tmp_path/'migration.sqlite3').as_posix()
    monkeypatch.setenv('DATABASE_URL',database)
    logger=logging.getLogger('shopsquire.migration.continuity')
    monkeypatch.setattr(logger,'disabled',False)
    config=Config('alembic.ini')
    config.set_main_option('sqlalchemy.url',database)
    command.upgrade(config,'head')
    assert logger.disabled is False
    # fileConfig replaces root handlers; attach pytest's capture to this logger.
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING):
            logger.warning('MIGRATION_LOGGING_CANARY')
    finally:
        logger.removeHandler(caplog.handler)
    assert 'MIGRATION_LOGGING_CANARY' in caplog.text
