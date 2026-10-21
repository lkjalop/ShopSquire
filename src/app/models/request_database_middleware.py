"""Bind legacy database consumers for the entire HTTP/WebSocket request."""
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.app.models.database_ownership import RequestDatabaseUnavailable, request_database_owner


class RequestDatabaseOwnerMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] not in {'http', 'websocket'}:
            await self.app(scope, receive, send)
            return
        application = scope.get('app')
        engine = getattr(getattr(application, 'state', None), 'engine', None)
        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message['type'] == 'http.response.start':
                response_started = True
            await send(message)

        with request_database_owner(engine):
            try:
                await self.app(scope, receive, tracked_send)
            except RequestDatabaseUnavailable:
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 1011})
                elif not response_started:
                    await JSONResponse({'detail': 'database_owner_unavailable'}, status_code=503)(scope, receive, send)
                else:
                    raise
