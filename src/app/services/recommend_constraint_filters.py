"""Conservative query-plan filtering at the V2 service boundary."""
from __future__ import annotations

import re
from typing import Any

from src.app.services.recommend_utils import _extract_candidate_numeric_specs


_CONSTRAINT_FRIENDLY = {
    "refresh": "refresh-rate",
    "ram": "RAM",
    "needs_dgpu": "dedicated-GPU",
    "weight": "weight/portability",
    "accessory": "product-type",
}


def constraint_relaxation_note(violated: list[str]) -> str:
    """Return an honest buyer-facing relaxation note."""
    labels = [
        _CONSTRAINT_FRIENDLY.get(value, value)
        for value in violated
        if value in _CONSTRAINT_FRIENDLY
    ]
    if labels:
        unmet = ", ".join(labels)
        return (
            f"No exact match for your {unmet} requirement — these are the "
            f"closest options. I can relax the {unmet}, adjust the budget, or "
            "widen the search if you'd like."
        )
    return (
        "No exact match for every requirement — these are the closest options. "
        "I can relax a constraint, adjust the budget, or widen the search if "
        "you'd like."
    )


def apply_query_plan_filters(
    results: list[Any],
    plan: Any,
) -> tuple[list[Any], dict[str, Any]]:
    """Drop confident hard-constraint violations without inventing facts."""
    if not results or plan is None:
        return results, {}
    try:
        hard_constraints = getattr(plan, "hard_constraints", {}) or {}
        category = getattr(plan, "category", None)
        intent = str(getattr(plan, "intent", "") or "")
        dropped: dict[str, Any] = {}
        accessory_pattern = re.compile(
            r"\b(stand|cable|adapter|charger|dock|hub|sleeve|case|bag|"
            r"mouse ?pad|cooling pad|screen protector|cleaning kit|warranty|"
            r"insurance|webcam cover|keyboard|mouse|headset|backpack)\b",
            re.I,
        )
        device_categories = {"laptop", "desktop", "phone", "tablet"}
        accessory_categories = {
            "keyboard", "mouse", "headset", "storage", "gpu", "cpu",
        }
        is_device_query = category in device_categories or (
            intent in ("product_search", "recommendation_multi")
            and category not in accessory_categories
        )
        refresh_min = hard_constraints.get("refresh_hz_min")
        ram_min = hard_constraints.get("ram_gb_min")
        weight_max = hard_constraints.get("weight_kg_max")
        needs_dedicated_gpu = bool(
            hard_constraints.get("must_have_dedicated_gpu")
        )
        filtered: list[Any] = []
        for result in results:
            if not isinstance(result, dict):
                filtered.append(result)
                continue
            name = str(result.get("name") or "")
            if is_device_query and accessory_pattern.search(name):
                dropped["accessory"] = dropped.get("accessory", 0) + 1
                continue
            specs = _extract_candidate_numeric_specs(result)
            if (
                needs_dedicated_gpu
                and specs.get("has_dedicated_gpu") is False
                and not specs.get("gaming_style")
            ):
                dropped["needs_dgpu"] = dropped.get("needs_dgpu", 0) + 1
                continue
            if (
                refresh_min
                and specs.get("refresh_hz") is not None
                and float(specs["refresh_hz"]) < float(refresh_min)
            ):
                dropped["refresh"] = dropped.get("refresh", 0) + 1
                continue
            if (
                ram_min
                and specs.get("ram_gb") is not None
                and float(specs["ram_gb"]) < float(ram_min)
            ):
                dropped["ram"] = dropped.get("ram", 0) + 1
                continue
            if (
                weight_max
                and specs.get("weight_kg") is not None
                and float(specs["weight_kg"]) > float(weight_max)
            ):
                dropped["weight"] = dropped.get("weight", 0) + 1
                continue
            filtered.append(result)
        if not filtered:
            violated = [
                key
                for key in (
                    "refresh", "ram", "needs_dgpu", "weight", "accessory",
                )
                if dropped.get(key)
            ]
            dropped["reverted"] = True
            dropped["exact_match"] = False
            dropped["violated_constraints"] = violated
            return results, dropped
        dropped["exact_match"] = True
        return filtered, dropped
    except Exception:
        # Frozen compatibility behaviour: malformed plans retain the slate.
        return results, {}


# Transitional aliases preserve frozen helper names without requiring tests to
# import the retired router.
_apply_query_plan_filters = apply_query_plan_filters
_constraint_relaxation_note = constraint_relaxation_note
