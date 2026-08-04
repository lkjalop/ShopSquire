"""Business/work-fleet ranking: a 'work laptops' query must rank business/productivity machines ABOVE
gaming SKUs, even when both sit in the same price band. Regression for the demo finding that "10 work
laptops $1300-$1500" surfaced gaming laptops.

Roots of the bug (both fixed):
  • the inferred tag is "business" but the KB key is "corporate" → the KB exclusion lookup missed, so the
    consumer_gaming_aesthetic exclusion never fired. Now the use_case is resolved through use_case_aliases.
  • the consumer_gaming_aesthetic check matched the bare substring "gaming", which also appears in the
    `gaming_style` specs KEY on EVERY product — penalising non-gaming machines too. Now it matches real
    gaming signals only.
"""
from __future__ import annotations

from src.app.services.recommendations import RecommendationService


def _svc() -> RecommendationService:
    # methods under test are pure (no instance state needed); skip the heavy __init__.
    return RecommendationService.__new__(RecommendationService)


def _score(svc, candidate, use_case="business"):
    feats = svc._extract_product_features(candidate)
    return svc._use_case_score(use_case, feats, candidate.get("specs", {}).get("price_cents"))


_GAMING = {"name": 'MSI Katana 15 B13VGK Gaming Laptop (RTX 4070)',
           "specs": {"gaming_style": True, "use_case": "gaming", "ram_gb": 16, "refresh_hz": 144}}
_PRODUCTIVITY = {"name": 'HP Pavilion 15 (Core i7)',
                 "specs": {"gaming_style": False, "use_case": "productivity", "ram_gb": 16, "storage_gb": 512}}
_BUSINESS_LINE = {"name": 'Dell Latitude 5440 Business Laptop',
                  "specs": {"gaming_style": False, "use_case": "productivity", "ram_gb": 16}}


def test_business_query_ranks_productivity_above_gaming():
    svc = _svc()
    gaming_score, _ = _score(svc, _GAMING)
    prod_score, prod_reasons = _score(svc, _PRODUCTIVITY)
    assert prod_score > gaming_score, f"productivity ({prod_score}) should outrank gaming ({gaming_score})"
    assert "use_case_business_class" in prod_reasons
    assert "use_case_not_business_gaming" not in prod_reasons  # productivity is not penalised as gaming


def test_business_line_brand_ranks_highest():
    svc = _svc()
    biz_score, biz_reasons = _score(svc, _BUSINESS_LINE)
    gaming_score, _ = _score(svc, _GAMING)
    assert biz_score > gaming_score
    assert "use_case_business_line" in biz_reasons


def test_gaming_sku_is_demoted_for_business():
    svc = _svc()
    gaming_score, gaming_reasons = _score(svc, _GAMING)
    assert gaming_score < 0  # net-negative: demoted out of the work-fleet shortlist
    assert "use_case_not_business_gaming" in gaming_reasons
    assert "kb_exclusion:consumer_gaming_aesthetic" in gaming_reasons


def test_consumer_gaming_exclusion_does_not_false_match_gaming_style_key():
    # the pre-existing false-positive: every product's specs JSON carries a `gaming_style` key, so a bare
    # "gaming" substring match penalised non-gaming machines. A productivity laptop must NOT be excluded.
    svc = _svc()
    _, prod_reasons = _score(svc, _PRODUCTIVITY)
    assert "kb_exclusion:consumer_gaming_aesthetic" not in prod_reasons


def test_work_and_office_aliases_score_like_business():
    # tags that resolve through the KB aliases to "corporate" get the same exclusion as "business".
    svc = _svc()
    base, _ = _score(svc, _GAMING, use_case="business")
    for alias in ("corporate", "office"):  # both land on the "corporate" KB entry → full exclusion
        alias_score, _ = _score(svc, _GAMING, use_case=alias)
        assert alias_score == base, f"{alias} should demote gaming the same as 'business'"
    # office_finance isn't a KB alias, so it still demotes gaming (branch) but without the KB exclusion.
    of_score, of_reasons = _score(svc, _GAMING, use_case="office_finance")
    assert of_score < 0 and "use_case_not_business_gaming" in of_reasons


def test_both_ranking_paths_agree_gaming_below_business():
    # consolidation guard: the rerank path (recommendations._use_case_score) and the fast-path adapter
    # (recommend_candidate_classify.use_case_fit) must AGREE — gaming ranks below business/productivity for
    # a work query — because both now read the SAME profile vocabulary. Pins them so they can't drift.
    from src.app.services.recommend_candidate_classify import use_case_fit
    svc = _svc()
    # rerank path
    g_rerank, _ = _score(svc, _GAMING)
    p_rerank, _ = _score(svc, _PRODUCTIVITY)
    assert p_rerank > g_rerank
    # adapter path (office query)
    g_fit = use_case_fit(_GAMING, "20 laptops for work", profile_id="electronics")
    p_fit = use_case_fit(_PRODUCTIVITY, "20 laptops for work", profile_id="electronics")
    assert (35 + p_fit["score_adjustment"]) > (35 + g_fit["score_adjustment"])
    # same direction on both paths
    assert (p_rerank > g_rerank) and (p_fit["score_adjustment"] > g_fit["score_adjustment"])
