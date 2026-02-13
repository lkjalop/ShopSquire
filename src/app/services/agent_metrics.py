"""Runtime agent metrics utilities (canonical path).

This module replaces legacy `src.agents.metrics`.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Dict, Any


_counters: Dict[str, int] = defaultdict(int)
_histograms: Dict[str, list] = defaultdict(list)
_lock = Lock()


def incr(name: str, amount: int = 1) -> None:
    with _lock:
        _counters[name] += amount


def timing(name: str, seconds: float) -> None:
    with _lock:
        _histograms[name].append(seconds)


class Timer:
    def __init__(self, name: str):
        self.name = name
        self._start = None

    def __enter__(self):
        self._start = time.time()

    def __exit__(self, exc_type, exc, tb):
        elapsed = time.time() - self._start
        timing(self.name, elapsed)


def snapshot() -> Dict[str, Any]:
    with _lock:
        return {"counters": dict(_counters), "histograms": {k: list(v) for k, v in _histograms.items()}}
