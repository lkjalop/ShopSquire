"""Fail-closed, non-production fault profiles for research browser certification."""

from __future__ import annotations

import os
from typing import Literal, cast


ResearchFaultProfile = Literal["publisher_timeout", "zero_parser_yield"]
_ALLOWED = {"publisher_timeout", "zero_parser_yield"}


def active_research_fault() -> ResearchFaultProfile | None:
    if str(os.getenv("RESEARCH_CERTIFICATION_MODE") or "").strip() != "1":
        return None
    environment = str(os.getenv("APP_ENV") or "development").strip().lower()
    if environment not in {"development", "dev", "test", "testing"}:
        return None
    value = str(os.getenv("RESEARCH_CERTIFICATION_FAULT_PROFILE") or "").strip().lower()
    return cast(ResearchFaultProfile, value) if value in _ALLOWED else None


__all__ = ["ResearchFaultProfile", "active_research_fault"]
