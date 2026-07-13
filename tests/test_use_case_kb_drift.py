"""KB DRIFT-LINT (Track E / E4 — the missing knowledge-pool validation).

The use-case knowledge is spread across FOUR files with THREE incompatible key namespaces and no
generator/validator. This lint surfaces cross-file value CONFLICTS (the same use-case given
different numbers by different files) so no NEW drift lands while the consolidation into a single
registry is designed. It is behaviour-neutral (a test, changes no data).

Known conflicts are documented in _ACCEPTED_CONFLICTS with the reason + the decision owed — a NEW
conflict (not in that set) fails the build. When the canonical value is chosen, fix the data and
delete the entry (the lint then proves it stays fixed).
"""
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_A2 = _ROOT / "config" / "use_case_kb.json"                    # coarse namespace, nested specs
_A3 = _ROOT / "config" / "use_case_knowledge_base.json"       # fine namespace, flat specs (workhorse)
_A4 = _ROOT / "config" / "use_case_knowledge.json"            # fine namespace, price floors

# a numeric field name in file A that means the same thing as a (possibly different) name in file B
_FLOOR_FIELDS = ("budget_floor", "min_price_floor")

# conflicts we KNOW about and have NOT yet resolved (decision owed). Delete when the data is fixed.
_ACCEPTED_CONFLICTS = {
    # use_case: (values seen, why-unresolved)
    "high_school:floor": ({300, 400}, "Asset2 budget_floor=300 vs Asset3/4 min_price_floor=400 — "
                                      "canonical value owed (consensus 400); changing it shifts a "
                                      "live floor so it waits for the soak baseline"),
}


def _floors(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for k, v in (d.get("use_cases") or {}).items():
        if not isinstance(v, dict):
            continue
        for f in _FLOOR_FIELDS:
            if f in v and isinstance(v[f], (int, float)):
                out[k] = v[f]
    return out


def test_no_new_cross_file_floor_conflicts():
    """Any use-case whose budget floor is defined in >1 file must agree — except the documented,
    decision-pending conflicts. A NEW disagreement fails."""
    floors = {"A2": _floors(_A2), "A3": _floors(_A3), "A4": _floors(_A4)}
    all_keys = set().union(*(f.keys() for f in floors.values()))
    conflicts = {}
    for k in all_keys:
        vals = {src: f[k] for src, f in floors.items() if k in f}
        distinct = set(vals.values())
        if len(distinct) > 1:
            conflicts[f"{k}:floor"] = distinct
    new = {k: v for k, v in conflicts.items() if k not in _ACCEPTED_CONFLICTS}
    assert not new, (
        "NEW use-case KB floor drift (same use-case, different money across files): " + str(new) +
        " — resolve the value and keep the files in sync, or the recommender floors depend on which "
        "code path reads which file."
    )
    # and the accepted ones must still be exactly what we documented (no silent widening)
    for k, (expected, _why) in _ACCEPTED_CONFLICTS.items():
        if k in conflicts:
            assert conflicts[k] == expected, (
                f"{k} conflict CHANGED to {conflicts[k]} (was {expected}) — re-review the drift.")


def test_namespace_fragmentation_is_documented():
    """The coarse (Asset2) vs fine (Asset3/4) namespaces are the reason a single registry is owed.
    This asserts the shape so a silent third namespace can't creep in unnoticed."""
    a2 = set((json.loads(_A2.read_text(encoding="utf-8")).get("use_cases") or {}))
    a3 = set((json.loads(_A3.read_text(encoding="utf-8")).get("use_cases") or {}))
    # Asset3 is the fine-grained workhorse; Asset2 is coarse. They deliberately diverge TODAY.
    assert "gaming" in a2 and "gaming" not in a3          # coarse vs split
    assert "gaming_aaa_heavy" in a3 and "gaming_aaa_heavy" not in a2
