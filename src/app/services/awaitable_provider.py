"""Small boundary for replaceable sync test fixtures and async live providers."""
from __future__ import annotations

import inspect
from typing import Any


async def await_provider_result(value: Any) -> Any:
    """Await live providers while accepting deterministic in-memory fixture values."""

    return await value if inspect.isawaitable(value) else value


__all__ = ["await_provider_result"]
