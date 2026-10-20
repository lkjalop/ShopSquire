"""Bounded performance answers preserve scope; they grant no product authority."""

from __future__ import annotations

import re
import math
import time
from typing import Any, Mapping


_SCALE_FRAGMENT = re.compile(
    r"^(?:mostly|typically|usually|generally|primarily|mainly|only|small|medium|large)\b",
    re.IGNORECASE,
)
_SCALE_VALUE = re.compile(r"\b(?:small|medium|large|simple|complex)\b", re.IGNORECASE)
_WORKLOAD_OBJECT = re.compile(
    r"\b(?:models?|scenes?|assembl(?:y|ies)|projects?|datasets?|simulations?|workloads?)\b",
    re.IGNORECASE,
)
_REPLACEMENT = re.compile(
    r"\b(?:replace|instead|rather\s+than|new\s+(?:request|search)|start\s+over|"
    r"forget\s+(?:that|this)|switch\s+to|change\s+(?:my|the)\s+(?:mind|request))\b",
    re.IGNORECASE,
)


def workload_scale_relation(query: str, pending: Mapping[str, Any] | None) -> str | None:
    """Recognize a qualitative scale fragment bound to a live performance question.

    Enum questions, unrelated questions, new objectives and expired questions
    stay with their existing interpreter. No research consent is inferred.
    """
    if not pending or str(pending.get("state") or "active") != "active":
        return None
    if (
        pending.get("question_id") != "performance_target"
        and pending.get("purpose") != "resolve_performance_target"
    ):
        return None
    if pending.get("answer_mode") == "enum":
        return None
    try:
        if pending.get("expires_at") is not None:
            expiry = float(pending["expires_at"])
            if not math.isfinite(expiry) or expiry <= time.time():
                return None
    except (TypeError, ValueError):
        return None
    text = str(query or "").strip()
    if (
        not text
        or len(text) > 800
        or _REPLACEMENT.search(text)
        or not _SCALE_FRAGMENT.search(text)
        or not _SCALE_VALUE.search(text)
        or not _WORKLOAD_OBJECT.search(text)
    ):
        return None
    from src.app.services.recommendation_core.literal_workload_identity import (
        deterministic_named_workload_switch,
    )

    if deterministic_named_workload_switch(text):
        return None
    return "answer"
