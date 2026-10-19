"""Bind tenant identity for every transaction, including after commit and on replicas."""
from sqlalchemy import event, text
from src.app.platform.tenant_context import current_tenant_id


def bind_session_tenant(session, *, tenant_id: str | None = None):
    tenant = current_tenant_id() if tenant_id is None else tenant_id
    if not isinstance(tenant, str) or not tenant.strip():
        raise ValueError('database_tenant_required')
    previous = session.info.get('_shopsquire_bound_tenant')
    if previous is not None:
        if previous != tenant:
            raise ValueError('database_tenant_rebinding_forbidden')
        return session
    if session.in_transaction():
        raise ValueError('database_tenant_required_before_transaction')

    def bind_transaction(session, transaction, connection):
        if connection.dialect.name == 'postgresql':
            connection.execute(text("SELECT set_config('app.current_tenant', :tenant, true)"), {'tenant': tenant})

    event.listen(session, 'after_begin', bind_transaction)
    session.info['tenant_id'] = tenant
    session.info['_shopsquire_bound_tenant'] = tenant
    return session
