import sys

try:
    import asyncio
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
except Exception:
    pass
