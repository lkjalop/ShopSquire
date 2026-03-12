from src.app.services.answer_quality import apply_answer_quality


def test_budget_question_gets_direct_answer_and_range():
    out = apply_answer_quality(
        query="i am going to university what budget should i think? do i need to spend over 1800?",
        assistant_message="Found 1 match between $1200 and $1800.",
        turn_intent="FILTER",
        products=[{"price": 1278}],
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

