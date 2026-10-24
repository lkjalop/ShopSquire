"""Tenant-filtered security projections for a fresh, read-only polling session."""
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def read_security_event_batch(
    database: Any, *, tenant_id: str, after_id: int,
    classify_details: Callable[[Any], str],
) -> list[dict[str, Any]]:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError('security_stream_tenant_required')
    parameters = {'cursor': after_id, 'tenant': tenant_id}
    try:
        primary = database.execute(text('''
            SELECT id, event_time, event_type, severity, vendor, tenant_id
            FROM security_event_ingest
            WHERE id > :cursor AND tenant_id = :tenant
            ORDER BY id ASC LIMIT 50
        '''), parameters).fetchall()
    except SQLAlchemyError:
        # Older installations can lack the primary table. A fresh read session
        # must rollback before the fallback query, including on PostgreSQL.
        database.rollback()
        primary = []
    if primary:
        return [dict(id=int(row[0]), event_time=str(row[1] or ''),
                     event_type=str(row[2] or ''), severity=str(row[3] or 'unknown'),
                     vendor=str(row[4] or ''), tenant_id=str(row[5] or ''),
                     source='security_event_ingest') for row in primary]
    fallback = database.execute(text('''
        SELECT id, event_time, severity, details, tenant_id
        FROM security_events
        WHERE id > :cursor AND tenant_id = :tenant
        ORDER BY id ASC LIMIT 50
    '''), parameters).fetchall()
    return [dict(id=int(row[0]), event_time=str(row[1] or ''),
                 event_type=classify_details(row[3]), severity=str(row[2] or 'unknown'),
                 vendor='', tenant_id=str(row[4] or ''), source='security_events')
            for row in fallback]
