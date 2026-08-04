"""NEW-4 — negation/exclusion response filter (agnostic core).

Drops excluded products by matching the term against product DATA. Must be fail-safe: a no-op
exclusion leaves the page intact, and an exclusion that would remove EVERYTHING is not applied
(never blank the page). No vertical literals in the mechanism.
"""
from __future__ import annotations

from src.app.services.negation_filter import apply_negation_exclusions


def _payload(names):
    rows = [{"sku": f"S{i}", "name": n} for i, n in enumerate(names)]
    return {"results": list(rows), "products": list(rows)}


def test_excludes_matching_brand():
    p = apply_negation_exclusions(_payload(["Apple MacBook Air", "Dell XPS 13", "HP Pavilion"]), ["apple"])
    names = [r["name"] for r in p["results"]]
    assert "Apple MacBook Air" not in names
    assert "Dell XPS 13" in names and "HP Pavilion" in names
    assert p["negation_excluded_count"] == 1
    assert p["negation_excluded_terms"] == ["apple"]
    # products mirror is filtered too
    assert all("apple" not in r["name"].lower() for r in p["products"])


def test_sibling_terms_remove_multiple():
    p = apply_negation_exclusions(_payload(["Apple X", "Dell Y", "HP Z"]), ["apple", "dell"])
    assert [r["name"] for r in p["results"]] == ["HP Z"]


def test_no_match_is_noop():
    src = _payload(["Dell XPS", "HP Pavilion"])
    p = apply_negation_exclusions(src, ["apple"])
    assert len(p["results"]) == 2
    assert "negation_excluded_count" not in p  # nothing removed → no annotation


def test_never_blanks_the_page():
    # Every product matches the exclusion → must NOT empty the results (fail-safe).
    src = _payload(["Apple A", "Apple B"])
    p = apply_negation_exclusions(src, ["apple"])
    assert len(p["results"]) == 2  # kept intact
    assert "negation_excluded_count" not in p


def test_empty_or_missing_inputs_are_safe():
    assert apply_negation_exclusions({}, ["apple"]) == {}
    assert apply_negation_exclusions({"results": []}, ["apple"]) == {"results": []}
    src = _payload(["Apple A", "Dell B"])
    assert apply_negation_exclusions(src, None)["results"] == src["results"]
    assert apply_negation_exclusions(src, [])["results"] == src["results"]


def test_short_terms_ignored():
    # 1-char terms are dropped (too noisy) → no-op.
    p = apply_negation_exclusions(_payload(["Apple A", "Dell B"]), ["a"])
    assert len(p["results"]) == 2
