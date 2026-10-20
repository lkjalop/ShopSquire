def test_registered_admin_api_routes_all_have_baseline_authorization():
    from src.app.main import create_app
    from src.app.security.admin_route_boundary import admin_operator
    from fastapi.routing import APIRoute, iter_route_contexts
    routes = [r for r in iter_route_contexts(create_app().routes)
              if isinstance(r.route, APIRoute) and r.path.startswith('/api/v1/admin/')]
    assert routes
    assert all(any(dep.call is admin_operator for dep in r.dependant.dependencies) for r in routes)
