"""Baseline operator authorization on every mounted administrative API route."""
from fastapi import Depends
from fastapi.routing import APIRoute
from fastapi import routing
from fastapi.dependencies.utils import get_parameterless_sub_dependant
from src.app.security.auth import require_role, ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER

admin_operator = require_role([ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER])


def enforce_admin_route_boundary(app) -> None:
    # New FastAPI versions retain nested includes instead of cloning flat
    # APIRoutes. Use their effective path/dependency context so an include
    # prefix is guarded without mutating a public include of the same router.
    contexts = getattr(routing, 'iter_route_contexts', iter)(app.routes)
    for context in contexts:
        if not isinstance(getattr(context, 'route', context), APIRoute):
            continue
        path = context.path
        if not (path == '/api/v1/admin' or path.startswith('/api/v1/admin/')
                or path.startswith('/admin/')):
            continue
        dependant = context.dependant
        if dependant is None:
            raise RuntimeError('admin_route_dependency_metadata_missing')
        if not any(dep.call is admin_operator for dep in dependant.dependencies):
            dependant.dependencies.insert(0, get_parameterless_sub_dependant(
                depends=Depends(admin_operator), path=context.path_format))
    app.openapi_schema = None
