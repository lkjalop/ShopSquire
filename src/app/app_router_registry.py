"""Typed router registration seam for incrementally shrinking ``main.py``."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI


@dataclass(frozen=True)
class RouterRegistration:
    name: str
    router: APIRouter


def register_routers(app: FastAPI, registrations: tuple[RouterRegistration, ...]) -> None:
    """Register an ordered router set and fail on accidental duplicate names."""

    names = [item.name for item in registrations]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_router_registration_name")
    recorded: list[str] = list(getattr(app.state, "registered_router_groups", []))
    for item in registrations:
        app.include_router(item.router)
        recorded.append(item.name)
    app.state.registered_router_groups = recorded


def router_registration(name: str, router: Any) -> RouterRegistration:
    if not isinstance(router, APIRouter):
        raise TypeError(f"invalid_router:{name}")
    return RouterRegistration(name=name, router=router)


__all__ = ["RouterRegistration", "register_routers", "router_registration"]
