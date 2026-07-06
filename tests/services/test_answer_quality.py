from src.app.services.answer_quality import apply_answer_quality


def test_budget_question_gets_direct_answer_and_range():
    out = apply_answer_quality(
        query="i am going to university what budget should i think? do i need to spend over 1800?",
        assistant_message="Found 3 matches between $1200 and $1800.",
        turn_intent="FILTER",
        products=[{"price": 1200}, {"price": 1500}, {"price": 1800}],
        image_cv_signals={},
        has_image=False,
        buyer_persona="student",
        brand_name=None,
    )
    msg = str(out.get("assistant_message") or "")
    cov = out.get("answer_coverage_scored") or {}
    assert msg.lower().startswith("usually no.")
    assert "$1,200-$1,800" in msg
    assert "budget_recommendation" in (cov.get("covered") or [])


def test_no_match_template_for_under_budget():
    out = apply_answer_quality(
        query="which macbook under 1100 do you have?",
        assistant_message="No products found.",
        turn_intent="FILTER",
        products=[],
        image_cv_signals={},
        has_image=False,
        buyer_persona=None,
        brand_name=None,
    )
    msg = str(out.get("assistant_message") or "").lower()
    templ = out.get("template_selected") or {}
    assert str(templ.get("template_id") or "") == "no_match_explain_template"
    assert "not currently in-catalog under $1,100".lower() in msg


def test_budget_band_caps_at_buyer_ceiling_not_product_max():
    # over-budget "performance-fit" lane items must NOT inflate the stated band (the $1,900 query that
    # read "$1,199-$5,999"). The band ceiling is the buyer's cap; the floor is the cheapest in-budget unit.
    out = apply_answer_quality(
        query="i need about 15 laptops for heavy coding and content creation? any discount? budget is about 1900 each?",
        assistant_message="I found 15 options that match your criteria.",
        turn_intent="FILTER",
        products=[{"price": 1199}, {"price": 1499}, {"price": 1899},
                  {"price": 2899}, {"price": 4499}, {"price": 5999}],
        image_cv_signals={},
        has_image=False,
        buyer_persona=None,
        brand_name=None,
    )
    msg = str(out.get("assistant_message") or "")
    assert "$1,199-$1,900" in msg          # capped at the buyer's ceiling
    assert "5,999" not in msg and "4,499" not in msg and "2,899" not in msg  # no over-budget leak


def test_cv_hard_block_still_answers_text_path():
    out = apply_answer_quality(
        query="what are my options and how soon can i get it sorted?",
        assistant_message="I need a clearer, unedited image before I continue.",
        turn_intent="SUPPORT_CLAIM",
        products=[],
        image_cv_signals={"qr_prompt_injection": True},
        has_image=True,
        buyer_persona=None,
        brand_name=None,
    )
    msg = str(out.get("assistant_message") or "").lower()
    cov = out.get("answer_coverage_scored") or {}
    assert "i can't trust this image yet" in msg
    assert "1-2 min triage" in msg
    assert "eta_to_resolve" in (cov.get("covered") or [])



def test_payment_and_contact_are_policy_faq_topics():
    """Payment-methods and contact questions route to the FAQ answerer, not product search (gap fix).
    They resolve from the store's policy_faq slot; product queries still return None (proceed to search)."""
    from src.app.services.answer_quality import policy_faq_answer
    for q in ("what payment methods do you accept?", "how can i pay?", "do you take paypal?",
              "how do i contact support?", "whats your phone number?"):
        assert policy_faq_answer(q), f"{q!r} should get a policy answer"
    assert policy_faq_answer("gaming laptop under 2000") is None
    assert policy_faq_answer("show me lenovo laptops") is None
