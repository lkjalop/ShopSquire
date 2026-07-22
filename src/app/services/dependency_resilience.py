from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Dict


@dataclass
class CircuitState:
    failures: int = 0
    open_until: float = 0.0


_CIRCUITS: Dict[str, CircuitState] = {}
_LOCK = Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=8)


def _state(dep: str) -> CircuitState:
    with _LOCK:
        if dep not in _CIRCUITS:
            _CIRCUITS[dep] = CircuitState()
        return _CIRCUITS[dep]


def call_with_resilience(
    dep: str,
    fn: Callable[[], Any],
    *,
    timeout_s: float = 5.0,
    retries: int = 1,
    backoff_s: float = 0.15,
    breaker_failures: int = 5,
    breaker_open_s: float = 20.0,
) -> Any:
    st = _state(dep)
    now = time.time()
    if st.open_until > now:
        raise RuntimeError(f"circuit_open:{dep}")

    last_exc: Exception | None = None
    for i in range(max(1, retries + 1)):
        fut = _EXECUTOR.submit(fn)
        try:
            out = fut.result(timeout=timeout_s)
            st.failures = 0
            st.open_until = 0.0
            return out
        except FuturesTimeout as e:
            fut.cancel()
            last_exc = TimeoutError(f"timeout:{dep}")
        except Exception as e:
            last_exc = e
        st.failures += 1
        if st.failures >= breaker_failures:
            st.open_until = time.time() + breaker_open_s
            break
        if i < retries:
            try:
                time.sleep(backoff_s * (2 ** i))
            except Exception:
                pass
    if last_exc:
        raise last_exc
    raise RuntimeError(f"dependency_error:{dep}")
