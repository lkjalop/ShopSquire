"""Literal buyer-authored workload identity recovery for router degradation paths."""
from __future__ import annotations

import re
from typing import Sequence, Tuple


_LITERAL_GAME_PATTERNS = (
    re.compile(r"\bplay\s+(?:the\s+)?(.+?)(?=\?\s*is\b|\bis\s+(?:aud\s*)?\$?\d|[.!]|$)", re.I),
    re.compile(r"\bwhat\s+about\s+(.+?)(?=\?\s*is\b|\bis\s+(?:aud\s*)?\$?\d|[.!]|$)", re.I),
    re.compile(r"\b(?:can|could|will)\s+(?:it|this(?:\s+laptop)?|that(?:\s+laptop)?|a\s+laptop|the\s+laptop)\s+(?:run|play)\s+(.+?)(?=[?.!]|$)", re.I),
    re.compile(r"\bi\s+want\s+(?:a\s+laptop\s+)?(?:that\s+can|to)\s+(?:run|play)\s+(.+?)(?=\?\s*is\b|\bis\s+(?:aud\s*)?\$?\d|[.!]|$)", re.I),
    re.compile(r"\b(?:laptop|computer|pc)\s+for\s+(.+?)(?=\?\s*is\b|\bis\s+(?:aud\s*)?\$?\d|[.!]|$)", re.I),
)

_GENERIC_GAME_TARGETS = {
    "game", "games", "gaming", "online", "locally", "work", "school",
    "university", "office", "digital twin", "digital twin simulation",
    "digital twin simulations",
}


def literal_game_identity_candidate(query: str) -> Tuple[Tuple[str, str], ...]:
    """Copy a narrowly delimited game title for fail-closed identity lookup only."""
    text = str(query or "")
    matched = next(
        ((index, match) for index, pattern in enumerate(_LITERAL_GAME_PATTERNS)
         if (match := pattern.search(text))),
        None,
    )
    match = matched[1] if matched else None
    if not match:
        return ()
    candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,;:-")[:80]
    candidate = re.sub(
        r"\s+(?:under|below|up to|around|about|budget(?:\s+is)?)\s+(?:aud\s*)?\$?[\d,]+\s*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip(" ,;:-")
    if candidate.lower() in _GENERIC_GAME_TARGETS:
        return ()
    significant = [
        token for token in re.findall(r"[a-z0-9]+", candidate.lower())
        if token not in {"a", "an", "the", "new"}
    ]
    # Bare "laptop for ..." is also ordinary use-case grammar. Accept it as a
    # title only when the buyer supplied title-like capitalization or a numeric
    # edition marker; explicit play/run/what-about forms remain unambiguous.
    if matched and matched[0] == len(_LITERAL_GAME_PATTERNS) - 1:
        title_words = re.findall(r"\b[A-Z][A-Za-z']+\b", candidate)
        if not re.search(r"\d", candidate) and len(title_words) < 2:
            return ()
    return (("game", candidate),) if len(significant) >= 2 else ()


def deterministic_named_workload_switch(query: str) -> bool:
    """Recognize a literal new game subject without relying on model continuity output."""
    text = str(query or "").strip()
    if not literal_game_identity_candidate(text):
        return False
    return bool(re.search(
        r"\b(?:what\s+about|i\s+want|(?:can|could|will)\s+(?:it|this(?:\s+laptop)?|that(?:\s+laptop)?|a\s+laptop|the\s+laptop)\s+(?:run|play)|(?:laptop|computer|pc)\s+for)\b",
        text,
        re.IGNORECASE,
    ))


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
