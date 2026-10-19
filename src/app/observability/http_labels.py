"""Bound HTTP metric cardinality to registered routes, never buyer resource IDs."""
from starlette.requests import Request


def route_metric_path(request: Request) -> str:
    # Routing populates this after call_next. Unknown paths share one series;
    # normalizing guessed UUID patterns would miss other identifiers and probes.
    route = request.scope.get('route')
    return getattr(route, 'path', None) or '__unmatched__'


def latency_metric_path(route_path: str) -> str:
    """Share histogram buckets across one API resource family.

    Request/error counters retain registered route templates. Giving every
    route its own histogram creates many value locks (native semaphores on
    Windows) even when resource IDs are correctly normalized.
    """
    if route_path in {'__unmatched__', '/health', '/healthz', '/readyz', '/metrics',
                      '/api/v1/chat/query', '/api/v1/chat/stream'}:
        return route_path
    parts = str(route_path or '').strip('/').split('/')
    depth = 4 if parts[:3] == ['api', 'v1', 'admin'] else 3 if parts[:2] == ['api', 'v1'] else 1
    return '/' + '/'.join(parts[:depth]) + '/*'
