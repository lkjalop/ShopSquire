"""Serialize category approvals across the workflow's internal commits."""
from contextlib import contextmanager
import hashlib
from sqlalchemy import text


@contextmanager
def category_budget_lock(db, *, tenant_id: str, category: str):
    if not tenant_id or not category:
        raise ValueError('budget_lock_identity_required')
    engine = db.get_bind()
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('category_budget_enforcement_requires_postgresql')
    identity = f'{tenant_id}\x1f{category.strip().lower()}'.encode()
    key = int.from_bytes(hashlib.sha256(identity).digest()[:8], 'big', signed=True)
    # A separate transaction is intentional: workflow.transition commits its
    # own session. This lock must survive that commit until dispatch completes.
    with engine.begin() as guard:
        guard.execute(text("SET LOCAL lock_timeout = '10s'"))
        guard.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
        yield
