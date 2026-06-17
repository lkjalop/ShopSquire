"""No-flavour-in-core lint — the mechanical boundary guard (agnostic core).

CORE modules are vertical-blind MECHANISMS. Laptop/electronics FLAVOUR (brand names, GPU
models, refresh-rate, etc.) must live in config/store_profiles/*.json, never in core code.
This test greps the core modules for laptop literals and FAILS the build if any appear —
so flavour bleeding into core is impossible to merge, not just discouraged.

As each suggest()/helper stage is extracted into a core module, ADD it to _CORE_MODULES.
A module that still carries transitional fallback flavour (query_decomposer,
product_classifier) is intentionally NOT listed until its flavour is fully excised.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# Modules that are CORE (agnostic mechanism) and must contain zero laptop flavour.
_CORE_MODULES = [
    "src/app/services/recommend_response_finalizer.py",
    "src/app/platform/store_profile.py",
    "src/app/policy/execution_gate.py",
    "src/app/services/answer_composer.py",
    "src/app/services/candidate_retriever.py",
    "src/app/services/recommend_pipeline.py",
    "src/app/services/commerce_source_status.py",
    "src/app/services/checkout_handoff.py",
    "src/app/services/recommend_context.py",
]

# Unambiguous electronics/laptop flavour literals (brand models, GPU prefixes, display).
# Deliberately specific — avoids false positives on generic words.
_FLAVOUR_RE = re.compile(
    r"\b(rtx|gtx|vivobook|macbook|thinkpad|zenbook|ideapad|alienware|aspire|"
    r"predator|omen|spectre|pavilion|victus|katana|legion|"
    r"gaming laptop|refresh_hz|\d{3} ?hz|tgp)\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("module", _CORE_MODULES)
def test_core_module_has_no_laptop_flavour(module):
    p = Path(module)
    assert p.exists(), f"core module missing: {module}"
    text = p.read_text(encoding="utf-8", errors="replace")
    hits = sorted({m.group(0).lower() for m in _FLAVOUR_RE.finditer(text)})
    assert not hits, (
        f"{module} contains laptop/electronics FLAVOUR {hits} — move it to a "
        f"StoreProfile (config/store_profiles/*.json). Core must be vertical-blind."
    )


def test_lint_actually_detects_flavour():
    # Guard the guard: the regex must catch a known flavour literal.
    assert _FLAVOUR_RE.search("the RTX 4070 vivobook gaming laptop at 240hz")
    assert not _FLAVOUR_RE.search("a generic product recommendation pipeline")
