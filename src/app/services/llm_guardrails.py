from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Schema registry – lightweight JSON-Schema-like validation
# ---------------------------------------------------------------------------

_SCHEMA_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_output_schema(name: str, schema: Dict[str, Any]) -> None:
    """Register a named schema for structured output validation.

    Schema format (subset of JSON Schema):
        {
            "type": "object",
            "required": ["field1", "field2"],
            "properties": {
                "field1": {"type": "string"},
                "field2": {"type": "number", "minimum": 0, "maximum": 100},
                "field3": {"type": "string", "enum": ["a", "b", "c"]},
                "field4": {"type": "array", "items": {"type": "string"}},
            }
        }
    """
    _SCHEMA_REGISTRY[name] = schema


def get_output_schema(name: str) -> Optional[Dict[str, Any]]:
    return _SCHEMA_REGISTRY.get(name)


def _validate_type(value: Any, expected: str) -> bool:
    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    expected_type = type_map.get(expected)
    if expected_type is None:
        return True  # unknown type constraint → pass
    return isinstance(value, expected_type)


def validate_against_schema(data: Any, schema: Dict[str, Any]) -> List[str]:
    """Validate *data* against a JSON-Schema-like *schema*.

    Returns a list of human-readable violation strings (empty = valid).
    """
    violations: List[str] = []
    schema_type = schema.get("type", "object")

    if not _validate_type(data, schema_type):
        violations.append(f"Expected top-level type '{schema_type}', got {type(data).__name__}")
        return violations

    if schema_type == "object" and isinstance(data, dict):
        required = schema.get("required") or []
        for field in required:
            if field not in data:
                violations.append(f"Missing required field '{field}'")

        properties = schema.get("properties") or {}
        for field, constraint in properties.items():
            if field not in data:
                continue
            val = data[field]
            prop_type = constraint.get("type")
            if prop_type and not _validate_type(val, prop_type):
                violations.append(f"Field '{field}' expected type '{prop_type}', got {type(val).__name__}")
                continue
            if "enum" in constraint:
                allowed = constraint["enum"]
                if val not in allowed:
                    violations.append(f"Field '{field}' value not in allowed set {allowed}")
            if "minimum" in constraint and isinstance(val, (int, float)):
                if val < constraint["minimum"]:
                    violations.append(f"Field '{field}' value {val} < minimum {constraint['minimum']}")
            if "maximum" in constraint and isinstance(val, (int, float)):
                if val > constraint["maximum"]:
                    violations.append(f"Field '{field}' value {val} > maximum {constraint['maximum']}")
            if "minLength" in constraint and isinstance(val, str):
                if len(val) < constraint["minLength"]:
                    violations.append(f"Field '{field}' length {len(val)} < minLength {constraint['minLength']}")
            if "maxLength" in constraint and isinstance(val, str):
                if len(val) > constraint["maxLength"]:
                    violations.append(f"Field '{field}' length {len(val)} > maxLength {constraint['maxLength']}")
            if prop_type == "array" and isinstance(val, list):
                items_schema = constraint.get("items")
                if items_schema and items_schema.get("type"):
                    for i, item in enumerate(val):
                        if not _validate_type(item, items_schema["type"]):
                            violations.append(
                                f"Field '{field}[{i}]' expected item type '{items_schema['type']}', got {type(item).__name__}"
                            )

    return violations


class LLMGuardrails:
    """Output guardrails with structured schema validation.

    Validates output format (JSON, sku_list, text, schema-backed), checks
    for content violations (PII, prompt leakage, harmful content), and
    optionally validates parsed JSON against a registered schema.
    """

    def __init__(self) -> None:
        pass

    async def validate_output(
        self,
        output: str,
        expected_format: str,
        context: Dict[str, Any],
    ) -> Tuple[bool, str, Any]:
        # 1) Format validation
        parsed: Any = output
        if expected_format == "json":
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                return False, "invalid_json", None
        elif expected_format == "sku_list":
            tokens = [t.strip() for t in re.split(r"[,\s]+", output or "") if t.strip()]
            parsed = tokens
            if not tokens:
                return False, "empty_sku_list", None
        elif expected_format == "text":
            parsed = output or ""

        # 2) Schema validation (when a schema_name is provided in context)
        schema_name = context.get("schema_name") if isinstance(context, dict) else None
        if schema_name and isinstance(parsed, dict):
            schema = get_output_schema(str(schema_name))
            if schema:
                schema_violations = validate_against_schema(parsed, schema)
                if schema_violations:
                    return False, "schema_violation", {"violations": schema_violations, "data": parsed}

        # 3) Content violations
        violations: List[str] = []
        if self._contains_pii(output):
            violations.append("pii_in_output")
        if self._contains_prompt_leak(output):
            violations.append("prompt_leakage")
        if self._contains_harmful(output):
            violations.append("harmful_content")
        if violations:
            return False, violations[0], None

        return True, "valid", parsed

    def _contains_pii(self, text: str) -> bool:
        if not text:
            return False
        patterns = [
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",  # Email
            r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # Phone
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b\d{13,16}\b",  # Credit card-ish
        ]
        return any(re.search(p, text) for p in patterns)

    def _contains_prompt_leak(self, text: str) -> bool:
        if not text:
            return False
        leak = [
            r"(?i)my\s+instructions\s+are",
            r"(?i)system\s+prompt",
            r"(?i)i\s+am\s+programmed\s+to",
        ]
        return any(re.search(p, text) for p in leak)

    def _contains_harmful(self, text: str) -> bool:
        if not text:
            return False
        harmful = [
            r"(?i)how\s+to\s+make\s+a\s+bomb",
            r"(?i)kill\s+",
            r"(?i)steal\s+credit\s+cards",
        ]
        return any(re.search(p, text) for p in harmful)
