"""Typed router registration boundaries used to shrink application composition safely."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from fastapi import APIRouter, FastAPI


@dataclass(frozen=True)
class RequiredRouter:
    name: str
    router: APIRouter


def register_required_routers(app: FastAPI, registrations: Iterable[RequiredRouter]) -> tuple[str, ...]:
    """Register required routes without swallowing import or registration failures."""
    registered: list[str] = []
    for registration in registrations:
        app.include_router(registration.router)
        registered.append(registration.name)
    return tuple(registered)
