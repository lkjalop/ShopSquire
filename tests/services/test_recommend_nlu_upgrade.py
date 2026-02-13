from src.app.services.recommendations import RecommendationService


def test_analyze_query_multilingual_normalization_and_locale():
    svc = RecommendationService()
    out = svc.analyze_query("hola quiero un portatil para universidad con presupuesto 1200")
    assert out.get("locale") == "es"
    prefs = out.get("preferences") or {}
    assert prefs.get("locale") == "es"
    entities = out.get("entities") or {}
    assert entities.get("budget_max") in (1200, None) or entities.get("budget_min") in (1200, None)


def test_analyze_query_lifecycle_signal_back_to_school():
    svc = RecommendationService()
    out = svc.analyze_query("back to school laptop for university under $1500")
    ents = out.get("entities") or {}
    assert ents.get("lifecycle_signal") in ("back_to_school", "university_term")
