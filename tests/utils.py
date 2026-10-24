import json
import os
from pathlib import Path


def default_headers() -> dict:
    return {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}


def with_client_address(app, host: str, port: int = 50000):
    """Set the ASGI peer for Starlette versions without TestClient(client=...).

    Host headers remain independent, and application identity/role checks still run.
    """
    async def transport(scope, receive, send):
        if scope['type'] in {'http', 'websocket'}:
            scope = {**scope, 'client': (host, port)}
        await app(scope, receive, send)
    return transport


def write_feature_flags(flags: dict, path: str | None = None) -> None:
    """Merge test flags without depending on the archived V1 recommendation suite."""
    path = path or os.environ.get("FEATURE_FLAGS_PATH")
    tracked = Path(__file__).resolve().parents[1] / "config" / "feature_flags.json"
    if not path or Path(path).resolve() == tracked.resolve():
        raise ValueError("Test flags require an isolated path, never the tracked config")
    base = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
        if raw:
            try:
                base = json.loads(raw)
            except json.JSONDecodeError:
                base = {}
    merged = dict(base) if isinstance(base, dict) else {}
    merged.update(flags or {})
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, ensure_ascii=False, indent=2)
