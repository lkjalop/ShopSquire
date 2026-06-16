"""6a — pure unit tests for the answer-shape scorers (no server needed)."""
from __future__ import annotations

from eval.answer_shape_scorers import score_relevancy, score_recovery, score_faithfulness

_RESULTS = [
    {"sku": "MSI-1", "name": "MSI Katana 15", "brand": "MSI", "price_cents": 159900,
     "specs": {"gpu": "RTX 4060", "display": "144Hz", "ram": "16GB"}},
]


# ── relevancy ────────────────────────────────────────────────────────────────
def test_relevancy_budget_verdict_passes():
    case = {"must_match": r"^(yes|no|it depends|\$?1?,?800)"}
    assert score_relevancy("Yes, $1,800 is plenty for a strong gaming laptop.", case)


def test_relevancy_budget_non_verdict_fails():
    case = {"must_match": r"^(yes|no|it depends|\$?1?,?800)"}
    assert not score_relevancy("I found 3 matches between $800 and $1800.", case)


def test_relevancy_comparison_needs_both_subjects_and_recommendation():
    case = {"must_contain_all": ["4060", "4070"], "must_contain_any": ["pick", "value", "worth"]}
    assert score_relevancy("The 4060 is the value pick; the 4070 is worth it if cooling is better.", case)
    assert not score_relevancy("Here are some gaming laptops.", case)            # neither
    assert not score_relevancy("The 4060 and 4070 are both GPUs.", case)         # both subjects, no recommendation


def test_relevancy_empty_message_fails():
    assert not score_relevancy("", {"must_match": "yes"})


# ── recovery ─────────────────────────────────────────────────────────────────
def test_recovery_offers_upgrade_path():
    case = {"must_contain_any": ["raise", "nearest", "other brand"]}
    assert score_recovery("No in-stock ASUS under $400; raise the budget or allow other brands.", case)


def test_recovery_dead_end_fails():
    case = {"must_contain_any": ["raise", "nearest", "other brand"]}
    assert not score_recovery("No results found.", case)


# ── faithfulness (delegates to the production claim-guard) ────────────────────
def test_faithfulness_grounded_answer_passes():
    grounded, viol = score_faithfulness(
        "The MSI Katana 15 at $1599 has an RTX 4060 and 144Hz display.",
        _RESULTS, budget_min=1300, budget_max=1800)
    assert grounded, viol


def test_faithfulness_invented_product_fails():
    grounded, viol = score_faithfulness("The Razer Blade is the top pick.", _RESULTS)
    assert not grounded
    assert any(v.startswith("ungrounded_product") for v in viol)
