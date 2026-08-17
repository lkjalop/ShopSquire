"""Presentation-free prompt assembly for the bounded turn interpreter."""
from __future__ import annotations


def compose_router_prompt(
    *, instruction_prefix: str, guide: str, variants: str, prior_context: str,
    pending_context: str, message: str, budget: str, image: str, research: str,
    candidate_lines: str,
) -> str:
    """Compose already-sanitized bounded sections in one stable order."""
    return (
        instruction_prefix + "\n" + guide + variants + prior_context + pending_context
        + f'MESSAGE: "{message[:400]}"\n' + budget + image + research
        + "CANDIDATE CATEGORIES (listed handle or null only):\n" + candidate_lines
        + "\nResolve MESSAGE now. Do not copy the schema's example values. For a product-commerce "
        "request with no fitting handle, return OFF_CATALOG and a specific non-null "
        "wanted_category; avoid ambiguous umbrella nouns, coined phrases, and accessory "
        "categories.\nJSON:"
    )


__all__ = ["compose_router_prompt"]
