"""Grounded, bounded conversation context for recommendation narration."""
from __future__ import annotations

from typing import Any


_USE_CASE_LABELS = {
    "gaming": "gaming laptop",
    "gaming_aaa_heavy": "AAA gaming laptop (ultra settings)",
    "gaming_casual": "casual gaming laptop",
    "gaming_competitive": "competitive esports laptop",
    "student_university": "university student laptop",
    "professional_developer": "developer / software engineering",
    "content_creator": "content creation / video editing",
    "office_general": "general office work",
    "office_finance": "finance / data analysis",
    "office_executive": "executive travel laptop",
    "photo_editing": "photo editing",
    "architecture_student": "architecture / CAD",
}


def build_context_preamble(
    kv: dict,
    structured_state: dict,
    constraints: dict,
    prior_shortlist_products: list | None = None,
) -> str:
    """Render only durable, previously observed conversation facts."""
    lines: list[str] = []
    answered: dict[str, Any] = {}
    try:
        answered.update(kv.get("nqe_answered_fields") or {})
        answered.update(structured_state.get("nqe_answered_fields") or {})
        answered.update(structured_state.get("confirmed_slots") or {})
    except Exception:
        pass
    for key in (
        "budget_max",
        "budget_min",
        "use_case",
        "brands",
        "gpu_preference",
    ):
        if key in constraints and key not in answered:
            answered[key] = constraints[key]
    if not answered:
        return ""

    budget_max = answered.get("budget_max") or constraints.get("budget_max")
    budget_min = answered.get("budget_min") or constraints.get("budget_min")
    use_case = str(
        answered.get("use_case") or constraints.get("use_case") or "",
    ).strip()
    brands = answered.get("brands") or constraints.get("brands") or []
    excluded = (
        answered.get("excluded_brands")
        or constraints.get("excluded_brands")
        or []
    )
    gpu_preference = (
        answered.get("gpu_preference")
        or constraints.get("gpu_preference")
        or ""
    )
    turn = int(answered.get("conversation_turn") or kv.get("conversation_turn") or 0)
    if use_case:
        lines.append(
            f"- Use case: {_USE_CASE_LABELS.get(use_case, use_case.replace('_', ' '))}",
        )
    if budget_max and budget_min:
        lines.append(f"- Budget: ${int(budget_min):,}–${int(budget_max):,}")
    elif budget_max:
        lines.append(f"- Budget: ${int(budget_max):,} max")
    elif budget_min:
        lines.append(f"- Budget: above ${int(budget_min):,}")
    if brands:
        lines.append(
            f"- Preferred brands: {', '.join(str(item) for item in brands[:3])}",
        )
    if excluded:
        lines.append(
            f"- Excluded brands: {', '.join(str(item) for item in excluded[:3])}",
        )
    if gpu_preference:
        lines.append(f"- GPU preference: {gpu_preference}")
    ignored = {
        "budget_max",
        "budget_min",
        "use_case",
        "brands",
        "excluded_brands",
        "gpu_preference",
        "conversation_turn",
    }
    confirmed = [
        key for key, value in answered.items()
        if key not in ignored and value is not None
    ]
    if confirmed[:3]:
        lines.append(f"- Also confirmed: {', '.join(confirmed[:3])}")
    if turn > 1:
        lines.append(f"- Conversation turn: {turn}")
    if not lines:
        return ""
    result = "Prior conversation context:\n" + "\n".join(lines)
    product_lines: list[str] = []
    for product in (prior_shortlist_products or [])[:4]:
        if not isinstance(product, dict):
            continue
        specs = product.get("specs")
        specs = specs if isinstance(specs, dict) else {}
        name = specs.get("display_name") or product.get("name") or ""
        if not name:
            continue
        price = int(float(product.get("price_cents") or 0) / 100)
        parts: list[str] = []
        if specs.get("gpu_model"):
            parts.append(str(specs["gpu_model"]))
        elif specs.get("gpu"):
            parts.append(str(specs["gpu"]).split("(")[0].strip()[:30])
        if specs.get("ram_gb"):
            parts.append(f"{specs['ram_gb']}GB RAM")
        if specs.get("refresh_hz"):
            parts.append(f"{specs['refresh_hz']}Hz")
        if specs.get("display_inches"):
            parts.append(f"{specs['display_inches']}\"")
        summary = ", ".join(parts) if parts else "specs unavailable"
        product_lines.append(f"  - {name} (${price:,}): {summary}")
    if product_lines:
        result += "\nProducts shown last turn:\n" + "\n".join(product_lines)
    return result
