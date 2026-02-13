import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Tuple

class ParallelExecutor:
    def __init__(self, timeout_sec: float = 2.0):
        self.timeout = timeout_sec

    async def gather(self, tasks: List[Tuple[str, Callable[[], Awaitable[Any]]]]) -> Dict[str, Any]:
        async def _wrap(name: str, coro_fn: Callable[[], Awaitable[Any]]):
            try:
                return name, await asyncio.wait_for(coro_fn(), timeout=self.timeout)
            except Exception:
                return name, {"error": "timeout_or_failure"}
        results = await asyncio.gather(*[_wrap(n, fn) for n, fn in tasks], return_exceptions=False)
        return {k: v for k, v in results}
