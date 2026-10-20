from src.app.routers.fulfillment_cases import router
from fastapi.routing import iter_route_contexts


def test_outbound_routes_have_one_owned_handler_and_keep_operator_boundary():
    expected = {
        '/api/v1/fulfillment/outbound/process': 'POST',
        '/api/v1/fulfillment/outbound/jobs/{job_id}': 'GET',
        '/api/v1/fulfillment/outbound/status': 'GET',
        '/api/v1/fulfillment/outbound/dead-letters': 'GET',
    }
    contexts = list(iter_route_contexts(router.routes))
    for path, method in expected.items():
        routes = [r for r in contexts if r.path == path and method in r.methods]
        assert len(routes) == 1
        route = routes[0]
        assert route.endpoint.__module__ == 'src.app.routers.fulfillment_outbound'
        assert route.dependant.dependencies  # operator authorization is retained
    assert next(r for r in contexts if r.path.endswith('/outbound/process')).status_code == 202
