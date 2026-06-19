"""RecommendContext — the read-only request envelope shared across extracted suggest() stages.

The strangler-fig decomposition of recommend.py::suggest() (7.7k lines) lifts one stage at a
time into a pure function `stage(payload, ctx) -> payload`. A stage may ONLY read from this
context — it must never reach back into suggest()'s local scope. The dataclass grows ONE field
at a time, as each extracted stage proves it needs that input; speculative fields are not added.

`store_profile_id` is here from the start because the agnostic core is profile-driven: any stage
that branches on vertical flavour must do so via the profile, never via inline literals.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.app.platform.store_profile import active_profile_id


@dataclass(frozen=True)
class RecommendContext:
    query: str | None = None
    uid: str | None = None
    # Resolves to the ACTIVE vertical at construction time (request ContextVar → env → electronics)
    # rather than a hardcoded "electronics" — so a stage reading the envelope sees the live tenant.
    store_profile_id: str = field(default_factory=active_profile_id)
