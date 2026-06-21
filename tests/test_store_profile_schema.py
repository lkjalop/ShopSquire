"""StoreProfile schema validation (Track 7 — agnostic-core contract).

config/store_profiles/store_profile.schema.json declares the slots every vertical MUST carry plus
their JSON types. This validator is dependency-free (no jsonschema package): it checks `required`
presence and, for declared properties, that the value's JSON type matches. additionalProperties is
allowed (profiles carry many vertical-specific slots). This makes a missing/mistyped core slot a
build failure, so the vertical-blind core can rely on the slot instead of an inline fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_DIR = Path("config/store_profiles")
_SCHEMA = json.loads((_DIR / "store_profile.schema.json").read_text(encoding="utf-8"))
_PROFILES = sorted(p for p in _DIR.glob("*.json") if p.name != "store_profile.schema.json")

_JSON_TYPE = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "boolean": bool,
}


def _json_type_ok(value, declared: str) -> bool:
    py = _JSON_TYPE.get(declared)
    if py is None:
        return True
    if declared == "number" and isinstance(value, bool):
        return False  # bool is a subclass of int — don't accept it as a number
    return isinstance(value, py)


def test_profiles_exist():
    assert _PROFILES, "no store profiles found to validate"


@pytest.mark.parametrize("path", _PROFILES, ids=lambda p: p.name)
def test_profile_satisfies_schema(path):
    profile = json.loads(path.read_text(encoding="utf-8"))

    missing = [k for k in _SCHEMA.get("required", []) if k not in profile]
    assert not missing, f"{path.name} is missing required slot(s): {missing}"

    props = _SCHEMA.get("properties", {})
    type_errors = []
    for key, spec in props.items():
        if key in profile and "type" in spec and not _json_type_ok(profile[key], spec["type"]):
            type_errors.append(f"{key}: expected {spec['type']}, got {type(profile[key]).__name__}")
    assert not type_errors, f"{path.name} has type error(s): {type_errors}"


def test_schema_id_matches_filename():
    # The `id` slot should match the filename stem (electronics.json -> id 'electronics').
    for path in _PROFILES:
        profile = json.loads(path.read_text(encoding="utf-8"))
        assert profile.get("id") == path.stem, f"{path.name}: id '{profile.get('id')}' != stem '{path.stem}'"
