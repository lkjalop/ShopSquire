from __future__ import annotations

import os
import time


def echo(*, value):
    return {"value": value, "pid": os.getpid()}


def wait(*, seconds: float):
    time.sleep(float(seconds))
    return "late"


def fail():
    raise ValueError("fixture failure")
