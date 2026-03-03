from src.app.services.recommendations import RecommendationService


def test_reformulate_query_includes_spell_and_synonym_expansion():
    svc = RecommendationService(session=None)
    qs = svc._reformulate_query("gmaing notebok with gpu")
    joined = " | ".join(qs)
    assert "gaming" in joined
    assert "laptop" in joined or "notebook" in joined
