"""V2 Phase 0: the full-response differ + contract validator are themselves load-bearing
(they gate shadow→canary→primary promotion), so their classification logic is pinned here."""
from src.app.contracts.suggest_contract import CORE_FIELDS, validate_response
from src.app.services.recommend_parity_full import (
    diff_responses,
    message_class,
    product_set_diff,
    summarize_run,
)


def _base(**over):
    """Minimal payload carrying every CORE field (so validate_response is clean)."""
    p = {f: None for f in CORE_FIELDS}
    p.update({
        "assistant_message": "Here are 2 options.",
        "products": [{"sku": "LAP-1"}, {"sku": "LAP-2"}],
        "results": [{"sku": "LAP-1"}, {"sku": "LAP-2"}],
        "trace_id": "t-1", "decision_id": "d-1", "turn_type": "search",
        "turn_intent": "SEARCH", "needs_disambiguation": False,
    })
    p.update(over)
    return p


# ── message_class ─────────────────────────────────────────────────────────────

def test_message_class_off_catalog_wins():
    assert message_class(_base(off_catalog={"class": "datacenter_gpu_server"}, products=[])) == "off_catalog"


def test_message_class_refusal():
    assert message_class(_base(refusal_note="cannot do 500 units", products=[])) == "refusal"


def test_message_class_answer_and_clarify_variants():
    assert message_class(_base()) == "answer"
    assert message_class(_base(needs_disambiguation=True, next_questions=[{"q": "budget?"}])) == "answer_with_clarify"
    assert message_class(_base(products=[], needs_disambiguation=True, next_questions=[{"q": "?"}])) == "clarify_no_products"
    assert message_class(_base(products=[], assistant_message="No matches.")) == "no_results"
    assert message_class(_base(products=[], assistant_message="")) == "empty"


# ── product_set_diff ──────────────────────────────────────────────────────────

def test_product_set_jaccard_and_top3():
    a = _base(products=[{"sku": s} for s in ("A", "B", "C")])
    b = _base(products=[{"sku": s} for s in ("A", "B", "D")])
    d = product_set_diff(a, b)
    assert not d["match"] and d["jaccard"] == 0.5 and not d["top3_match"]
    assert d["only_a"] == ["C"] and d["only_b"] == ["D"]


# ── diff_responses severity ladder ────────────────────────────────────────────

def test_identical_payloads_are_identical_outcome():
    d = diff_responses(_base(), _base())
    assert d["identical_outcome"] and d["severity"] == "INFO"


def test_nondeterministic_fields_do_not_diverge():
    d = diff_responses(_base(trace_id="t-1", llm_summary_job_id="j1"),
                       _base(trace_id="t-999", llm_summary_job_id="j2"))
    assert d["identical_outcome"]


def test_off_catalog_flip_is_blocker():
    v1 = _base(off_catalog={"class": "datacenter_gpu_server"}, products=[], results=[])
    v2 = _base()  # v2 sells products where v1 refused
    d = diff_responses(v1, v2)
    assert d["severity"] == "BLOCKER"
    assert not d["dimensions"]["gates"]["match"]


def test_dropped_refusal_is_blocker():
    d = diff_responses(_base(refusal_note="qty refused"), _base())
    assert d["severity"] == "BLOCKER"


def test_product_drift_within_tolerance_is_clean():
    v1 = _base(products=[{"sku": s} for s in "ABCDEFGHIJ"])
    v2 = _base(products=[{"sku": s} for s in "ABCDEFGHI"])  # jaccard 0.9 = membership tolerance
    d = diff_responses(v1, v2)
    assert d["dimensions"]["product_set"]["match"] is True   # within membership tolerance
    assert d["severity"] == "INFO"                           # nothing else diverges


def test_reordering_same_set_is_diagnostic_not_major():
    # GPT-5.6 ranking ruling: same MEMBERSHIP, different top-3 ORDER → MINOR (diagnostic),
    # never a gate. order_matches_v1 records the divergence without bumping severity.
    v1 = _base(products=[{"sku": s} for s in ("A", "B", "C")])
    v2 = _base(products=[{"sku": s} for s in ("B", "A", "C")])
    d = diff_responses(v1, v2)
    ps = d["dimensions"]["product_set"]
    assert ps["severity"] == "MINOR" and ps["match"] is True   # membership identical
    assert ps["order_matches_v1"] is False                     # order differs (diagnostic)


def test_membership_divergence_is_major():
    v1 = _base(products=[{"sku": s} for s in ("A", "B", "C")])
    v2 = _base(products=[{"sku": s} for s in ("A", "X", "Y")])  # dropped B,C; added X,Y
    d = diff_responses(v1, v2)
    assert d["dimensions"]["product_set"]["severity"] == "MAJOR"


# ── summarize_run promotion gates ─────────────────────────────────────────────

def test_summarize_run_gates():
    clean = [diff_responses(_base(), _base()) for _ in range(50)]
    # parity/honesty gate = diagnostic_pass; gates_pass (promotion) additionally needs quality
    # to have been measured (review-6 #1), which these parity-only runs do not supply.
    assert summarize_run(clean)["diagnostic_pass"]
    assert summarize_run(clean)["gates_pass"] is False   # no quality → not promotable
    blocked = clean + [diff_responses(_base(off_catalog={"class": "x"}, products=[], results=[]), _base())]
    s = summarize_run(blocked)
    assert not s["diagnostic_pass"] and s["by_severity"]["BLOCKER"] == 1


# ── known_wrong: expected changes must not read as regressions (GPT-5.6 #4) ──

def test_fixing_a_known_wrong_is_not_a_blocker():
    from src.app.services.recommend_parity_full import evaluate_case
    v1_bug = _base()                                   # recorded: sells laptops to a forklift ask
    v2_fix = _base(off_catalog={"class": "material_handling"}, products=[], results=[],
                   assistant_message="Honest answer: we don't sell forklifts.")
    expect = {"message_class": "off_catalog", "products_max": 0}
    cases = [evaluate_case(_base(), _base()) for _ in range(50)]
    cases.append(evaluate_case(v1_bug, v2_fix, known_wrong_expect=expect))
    s = summarize_run(cases)
    assert s["diagnostic_pass"] and s["expected_changes"] == 1 and s["expected_changes_met"] == 1
    assert s["by_severity"]["BLOCKER"] == 0            # the fix is NOT counted as a regression


def test_missed_expectation_fails_the_run():
    from src.app.services.recommend_parity_full import evaluate_case
    v2_still_broken = _base()                          # v2 still sells laptops for forklifts
    cases = [evaluate_case(_base(), _base()) for _ in range(50)]
    cases.append(evaluate_case(_base(), v2_still_broken,
                               known_wrong_expect={"message_class": "off_catalog"}))
    s = summarize_run(cases)
    assert not s["diagnostic_pass"] and s["expected_changes_met"] == 0


def test_expectation_met_vocabulary():
    from src.app.services.recommend_parity_full import expectation_met
    honest = _base(off_catalog={"class": "x"}, products=[], results=[])
    assert expectation_met(honest, {"message_class": "off_catalog", "products_max": 0})
    assert not expectation_met(honest, {"products_min": 1})
    assert expectation_met(_base(), {"message_class_in": ["answer"], "nonempty_message": True})
    assert not expectation_met(_base(assistant_message=""), {"nonempty_message": True})


# ── contract validator ────────────────────────────────────────────────────────

def test_validate_response_flags_missing_core_and_honesty():
    p = _base()
    del p["proposal"]
    assert "missing core field: proposal" in validate_response(p)
    dishonest = _base(off_catalog={"class": "x"})  # products still non-empty
    assert any("honesty violation" in v for v in validate_response(dishonest))


def test_validate_response_clean_on_base():
    assert validate_response(_base()) == []
