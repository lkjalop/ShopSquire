from fastapi import FastAPI

from src.app.bootstrap.conversation_router_group import register_conversation_router_group


def test_conversation_group_registers_required_surfaces_without_silent_skip() -> None:
    app = FastAPI()
    registered = register_conversation_router_group(app)
    paths = {route.path for route in app.routes}

    assert registered == ("support_complaints", "chat", "chat_stream", "safe_links")
    assert app.state.conversation_router_group == registered
    assert "/api/v1/chat/query" in paths
    assert any("stream" in path and "chat" in path for path in paths)
