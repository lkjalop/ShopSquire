"""Response-shape stage (E1, 2026-07-09) — the minimum/recommended tier split extracted from
suggest() (recommend.py ~10754-10782). First cut of the response-assembly extraction; more
inline blocks migrate here behind the parity net (scripts/suggest_parity_capture.py).

Why: suggest() is ~8,000 lines and every recent feature needed 2-3 placement attempts to find
the real choke point. Extracting response assembly into named stages means the next feature
lands in one placement, not three. This stage owns the tier split; behavior is byte-identical
to the inline block (parity-verified). Never raises."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def apply_recommendation_tiers(
    payload: Dict[str, Any],
    *,
    results: Any,
    constraints: Dict[str, Any],
    query: Any,
    parse_explicit_spec_blocks: Callable[[Any], Dict[str, Any]],
    build_minimum_recommended_tiers: Callable[..., Dict[str, Any]],
) -> None:
    """Stamp payload['explicit_spec_blocks'] + payload['recommendation_tiers'] — the
    minimum/recommended split, widened to a forced show_split when the buyer wrote explicit
    minimum/recommended spec blocks. Helpers injected so this is unit-testable. Verbatim
    behavior of the former inline block."""
    try:
        _spec_blocks = parse_explicit_spec_blocks(query)
        payload["explicit_spec_blocks"] = _spec_blocks
        _tiers = build_minimum_recommended_tiers(
            results if isinstance(results, list) else [],
            budget_min=constraints.get("budget_min"),
            budget_max=constraints.get("budget_max"),
            use_case=constraints.get("use_case"),
            query=query,
        )
        if bool(_spec_blocks.get("has_explicit_blocks")):
            _tiers["show_split"] = True
            if _spec_blocks.get("minimum"):
                _tiers["minimum_explanation"] = (
                    "Aligned to your minimum spec block. These are closest budget-fit matches to the baseline."
                )
            if _spec_blocks.get("recommended"):
                _tiers["recommended_explanation"] = (
                    "Aligned to your recommended spec block. These prioritize stronger long-term headroom."
                )
        payload["recommendation_tiers"] = {
            "minimum": _tiers.get("minimum", []),
            "recommended": _tiers.get("recommended", []),
            "show_split": bool(_tiers.get("show_split")),
            "minimum_explanation": _tiers.get("minimum_explanation"),
            "recommended_explanation": _tiers.get("recommended_explanation"),
        }
    except Exception:
        payload["recommendation_tiers"] = {"minimum": [], "recommended": [], "show_split": False}
