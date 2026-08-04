"""NEW-2 — _extract_hard_constraints is profile-driven (agnostic core graduation).

The refresh/RAM/storage/weight/esports spec logic moved from hardcoded electronics literals into the
StoreProfile slots (hard_constraint_rules / use_case_spec_implications / portable_weight_kg_max).
This locks: (a) electronics extracts byte-identical constraints to the pre-refactor baseline, and
(b) a vertical with no spec rules (pharmacy/fashion) extracts NO GPU/refresh specs — no bleed.
"""
from __future__ import annotations

import pytest

from src.app.services.query_decomposer import (
    _extract_hard_constraints,
    _hard_constraint_rules_for,
    _use_case_spec_implications_for,
    reset_cache,
)

# Byte-for-byte baseline captured from the pre-NEW-2 hardcoded implementation.
_GOLDEN = [
    ("a 240hz gaming laptop", ["gaming"], {"refresh_hz_min": 240, "must_have_dedicated_gpu": True}),
    ("laptop with 144 fps", ["gaming"], {"refresh_hz_min": 144, "must_have_dedicated_gpu": True}),
    ("portable ultrabook", [], {"weight_kg_max": 2.0}),
    ("laptop under 1.5 kg", [], {"weight_kg_max": 1.5}),
    ("32gb ram laptop", [], {"ram_gb_min": 32}),
    ("2tb storage", [], {"storage_gb_min": 2048}),
    ("esports valorant rig", ["gaming"], {"must_have_dedicated_gpu": True, "refresh_hz_min": 144}),
    ("competitive gaming", ["gaming"], {"must_have_dedicated_gpu": True, "refresh_hz_min": 144}),
    ("rtx 4070 laptop", ["gaming"], {"gpu_model_hint": "rtx 4070", "must_have_dedicated_gpu": True}),
    ("16gb 1tb 165hz", ["gaming"], {"refresh_hz_min": 165, "ram_gb_min": 16, "storage_gb_min": 1024, "must_have_dedicated_gpu": True}),
    ("plain office laptop", ["office"], {}),
]


@pytest.mark.parametrize("query,use_cases,expected", _GOLDEN)
def test_electronics_hard_constraints_byte_identical(query, use_cases, expected):
    reset_cache()
    assert _extract_hard_constraints(query, list(use_cases)) == expected


def test_electronics_profile_carries_the_rules():
    reset_cache()
    assert _hard_constraint_rules_for("electronics"), "electronics must carry hard_constraint_rules"
    assert _use_case_spec_implications_for("electronics"), "electronics must carry use_case_spec_implications"


def test_non_electronics_verticals_have_no_spec_bleed():
    # Pharmacy/fashion carry no GPU/refresh rules → the mechanism contributes nothing for them.
    reset_cache()
    assert _hard_constraint_rules_for("pharmacy") == ()
    assert _hard_constraint_rules_for("fashion") == ()
    assert _use_case_spec_implications_for("pharmacy") == ()
