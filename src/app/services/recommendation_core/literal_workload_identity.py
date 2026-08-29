"""Literal buyer-authored workload identity recovery for router degradation paths."""
from __future__ import annotations

import re
from typing import Sequence, Tuple


def literal_game_identity_candidate(query: str) -> Tuple[Tuple[str, str], ...]:
    """Copy a narrowly delimited game title for fail-closed identity lookup only."""
    match = re.search(
        r"\bplay\s+(?:the\s+)?(.+?)(?=\?\s*is\b|\bis\s+(?:aud\s*)?\$?\d|[.!]|$)",
        str(query or ""),
        re.IGNORECASE,
    )
    if not match:
        return ()
    candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,;:-")[:80]
    significant = [
        token for token in re.findall(r"[a-z0-9]+", candidate.lower())
        if token not in {"a", "an", "the", "new"}
    ]
    return (("game", candidate),) if len(significant) >= 2 else ()


def restore_literal_edition_qualifiers(
    workload_entities: Sequence[Tuple[str, str]], query_tokens: Sequence[str],
) -> list[Tuple[str, str]]:
    """Restore only edition qualifiers literally present in the buyer's current turn."""
    qualifiers = tuple(
        token for token in ("remastered", "remaster", "remake")
        if token in query_tokens
    )
    if not qualifiers:
        return list(workload_entities)
    restored: list[Tuple[str, str]] = []
    for kind, name in workload_entities:
        name_tokens = set(re.sub(r"[^a-z0-9]+", " ", name.lower()).strip().split())
        missing = [token for token in qualifiers if token not in name_tokens]
        restored.append((kind, f"{name} {' '.join(missing)}".strip()))
    return restored


def recover_literal_game_identity(
    query: str,
    workload_entities: Sequence[Tuple[str, str]],
    query_tokens: Sequence[str],
) -> list[Tuple[str, str]]:
    """Recover a missing literal title, then preserve buyer-authored edition qualifiers."""
    entities = list(workload_entities) or list(literal_game_identity_candidate(query))
    return restore_literal_edition_qualifiers(entities, query_tokens)
