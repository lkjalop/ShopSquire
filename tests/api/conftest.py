import asyncio
import sys
import pytest


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    try:
        if sys.platform.startswith("win"):
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except Exception:
        pass
    yield
