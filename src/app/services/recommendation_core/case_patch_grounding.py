"""Deterministic buyer-utterance grounding for canonical case-patch completion."""

from __future__ import annotations

import json
import logging
import re as _re
from dataclasses import dataclass
from typing import Any, Dict, Tuple

logger = logging.getLogger("shopsquire.recommendation_core.case_patch_grounding")


@dataclass(frozen=True)
class CasePatchEvaluation:
    accepted: Tuple[Dict[str, Any], ...]
    rejections: Tuple[Dict[str, Any], ...]


def _evaluate_bounded_case_patches(
    data: Dict[str, Any], query: str | None = None,
) -> CasePatchEvaluation:
    """Validate model-proposed case operations without applying them.

    When the buyer query is supplied, changed values must also be grounded in
    that utterance. Retained values are never re-emitted as patches.
    """
    from pydantic import ValidationError

    from src.app.services.procurement_case_state import CasePatch, case_patch_path_supported

    raw = data.get("case_patches")
    if not isinstance(raw, list):
        return CasePatchEvaluation(accepted=(), rejections=())
    accepted: list[Dict[str, Any]] = []
    rejections: list[Dict[str, Any]] = []
    normalized_query = " ".join(str(query or "").casefold().split())

    def reject(index: int, item: Dict[str, Any], reason: str, predicate: str) -> None:
        receipt = {
            "schema_version": "case_patch_rejection.v1",
            "patch_index": index,
            "operation": str(item.get("operation") or "unknown")[:40],
            "path": str(item.get("path") or "unknown")[:120],
            "reason": reason,
            "rejecting_predicate": predicate,
            "utterance_present": bool(normalized_query),
        }
        rejections.append(receipt)
        logger.info("case patch rejected: %s", json.dumps(receipt, sort_keys=True))

    def numeric_value_grounded(value: int) -> bool:
        from src.app.services.bulk_intent import quantity_value_mentioned

        return quantity_value_mentioned(query, value)

    def grounded(patch: CasePatch) -> tuple[bool, str]:
        if not normalized_query:
            return True, "no_utterance_clamp_requested"
        if patch.operation == "move_quantity":
            result = bool(
                patch.quantity is not None
                and numeric_value_grounded(patch.quantity)
                and str(patch.from_ref or "").casefold() in normalized_query
                and str(patch.to_ref or "").casefold() in normalized_query
            )
            return result, "move_quantity_span_and_locations"
        if patch.path == "budget.amount_minor" and isinstance(patch.value, int):
            from src.app.services.budget_grammar import parse_budget

            parsed = parse_budget(query or "")
            authorized = {
                int(amount) * 100
                for amount in (
                    getattr(parsed, "budget_min", None),
                    getattr(parsed, "budget_max", None),
                )
                if amount is not None
            }
            return patch.value in authorized, "canonical_budget_grammar"
        if patch.path == "budget.scope":
            from src.app.services.budget_grammar import classify_budget_scope

            return (
                str(patch.value) == classify_budget_scope(query or ""),
                "canonical_budget_scope_grammar",
            )
        if patch.path == "requested_quantity" and isinstance(patch.value, int):
            return numeric_value_grounded(patch.value), "canonical_quantity_grammar"
        values: list[Any]
        if patch.path == "destinations" and isinstance(patch.value, list):
            values = [
                value
                for row in patch.value if isinstance(row, dict)
                for value in (row.get("location_ref"), row.get("quantity"))
            ]
        elif patch.path == "workloads" and isinstance(patch.value, list):
            values = list(patch.value)
        else:
            values = [patch.value]
        for value in values:
            if value is None:
                return False, "non_null_value"
            candidate = str(value).casefold()
            if isinstance(value, int):
                if not numeric_value_grounded(value):
                    return False, "canonical_numeric_grounding"
            elif candidate not in normalized_query:
                return False, "literal_buyer_span"
        return True, "literal_buyer_span"
    for index, item in enumerate(raw[:8]):
        if not isinstance(item, dict):
            continue
        candidate_item = dict(item)
        if (
            candidate_item.get("operation") == "set"
            and candidate_item.get("path") == "destinations"
            and isinstance(candidate_item.get("value"), list)
        ):
            valid_location_kinds = {
                "region", "city", "store", "warehouse", "address_token", "unknown",
            }
            candidate_item["value"] = [
                {
                    "location_ref": row.get("location_ref"),
                    "quantity": row.get("quantity"),
                    # Location classification is not buyer authority and must not
                    # make an otherwise grounded allocation crash the turn.
                    "location_kind": (
                        row.get("location_kind")
                        if row.get("location_kind") in valid_location_kinds else "unknown"
                    ),
                }
                for row in candidate_item["value"][:100]
                if isinstance(row, dict)
            ]
        try:
            patch = CasePatch.model_validate(candidate_item)
        except ValidationError:
            reject(index, candidate_item, "schema_validation_failed", "CasePatch")
            continue
        if not case_patch_path_supported(patch.operation, patch.path):
            reject(index, candidate_item, "unsupported_case_patch_path", "case_patch_path_supported")
            continue
        is_grounded, predicate = grounded(patch)
        if not is_grounded:
            reject(index, candidate_item, "buyer_grounding_failed", predicate)
            continue
        accepted.append(patch.model_dump(mode="json", exclude_none=True))
    return CasePatchEvaluation(
        accepted=tuple(accepted), rejections=tuple(rejections),
    )


def _bounded_case_patches(
    data: Dict[str, Any], query: str | None = None,
) -> Tuple[Dict[str, Any], ...]:
    """Compatibility projection for callers that need only accepted patches."""
    return _evaluate_bounded_case_patches(data, query).accepted


def _complete_canonical_case_patches(
    patches: Tuple[Dict[str, Any], ...],
    *,
    query: str,
    requested_quantity: int | None,
    total_budget_cents: int | None,
    budget_scope: str,
    settlement_currency: str,
) -> Tuple[Dict[str, Any], ...]:
    """Complete durable intake from already-authorized deterministic parsers.

    Model proposals remain useful, but a correctly parsed quantity, budget,
    deadline or data-owned workload must not disappear merely because the model
    omitted the parallel case-patch field. These patches grant no commerce
    authority and are still validated atomically by the case reducer.
    """
    completed = [dict(patch) for patch in patches]
    paths = {str(patch.get("path") or "") for patch in completed}

    def add(operation: str, path: str, value: Any, reason: str) -> None:
        completed.append({
            "operation": operation, "path": path, "value": value, "reason": reason,
        })
        paths.add(path)

    # ``requested_quantity`` and budget values can be inherited into the final
    # decision from the active case.  Completion is an intake projection, so it
    # may emit them only when this buyer utterance independently grounds them.
    # Otherwise an amendment such as "move 3 from Adelaide to Brisbane" would
    # silently rewrite retained quantity/budget alongside the one requested edit.
    from src.app.services.recommendation_core.case_patch_grounding import (
        budget_is_current,
        quantity_is_current,
    )
    if quantity_is_current(query, requested_quantity) and "requested_quantity" not in paths:
        add("set", "requested_quantity", requested_quantity, "canonical_quantity_grammar")
    if budget_is_current(query, total_budget_cents):
        if "budget.amount_minor" not in paths:
            add("set", "budget.amount_minor", total_budget_cents, "canonical_budget_grammar")
        if "budget.currency" not in paths:
            # Bind the currency to a money-shaped mention. A free-standing code is
            # unsafe here: procurement text commonly contains workload acronyms
            # such as "CAD models", which must not override "AUD 220,000".
            explicit_currency = _re.search(
                r"\b(AUD|USD|CAD|NZD|SGD|HKD|GBP|EUR|JPY)\b\s*[$€£¥]?\s*\d",
                query,
                _re.IGNORECASE,
            )
            currency = (
                explicit_currency.group(1).upper()
                if explicit_currency else str(settlement_currency or "AUD").upper()
            )
            add("set", "budget.currency", currency, "settlement_currency_authority")
        if budget_scope in {"per_unit", "total"} and "budget.scope" not in paths:
            add("set", "budget.scope", budget_scope, "bounded_budget_scope")

    from src.app.services.temporal_expression_authority import extract_temporal_expression

    expression = extract_temporal_expression(query)
    if expression and "temporal.original_expression" not in paths:
        add(
            "set", "temporal.original_expression", expression,
            "canonical_temporal_expression_grammar",
        )

    if "workloads" not in paths:
        from src.app.services.use_case_registry import match_case_workloads

        for workload in match_case_workloads(query):
            add("add", "workloads", workload, "data_owned_workload_phrase")
    return tuple(completed)

from src.app.services.budget_grammar import parse_budget
from src.app.services.bulk_intent import quantity_value_mentioned


def quantity_is_current(query: str, requested_quantity: int | None) -> bool:
    """Return true only when this turn independently mentions the quantity."""

    return bool(
        requested_quantity is not None
        and quantity_value_mentioned(query, requested_quantity)
    )


def budget_is_current(query: str, total_budget_cents: int | None) -> bool:
    """Return true only when this turn independently mentions the parsed budget."""

    parsed = parse_budget(query)
    return bool(
        total_budget_cents is not None
        and parsed is not None
        and total_budget_cents in {
            int(amount) * 100
            for amount in (parsed.budget_min, parsed.budget_max)
            if amount is not None
        }
    )


__all__ = ["budget_is_current", "quantity_is_current"]
