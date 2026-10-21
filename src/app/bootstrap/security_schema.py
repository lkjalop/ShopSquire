"""Fail visibly when the legacy security schema cannot initialize."""


def ensure_security_ingest_ready() -> None:
    from src.app.security.security_event_ingest import ensure_security_event_ingest_table

    if not ensure_security_event_ingest_table():
        raise RuntimeError('security_event_ingest_schema_unavailable')
