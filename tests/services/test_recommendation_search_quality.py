from src.app.services.recommendations import RecommendationService
from types import SimpleNamespace


def test_reformulate_query_includes_spell_and_synonym_expansion():
    svc = RecommendationService(session=None)
    qs = svc._reformulate_query("gmaing notebok with gpu")
    joined = " | ".join(qs)
    assert "gaming" in joined
    assert "laptop" in joined or "notebook" in joined


def test_retrieve_candidates_tops_up_profile_valid_use_case_when_broad_search_is_full(monkeypatch):
    from src.app.platform import store_profile as sp

    monkeypatch.setenv("STORE_PROFILE_ID", "electronics")
    sp.reset_cache()
    svc = RecommendationService(session=None)

    weak = SimpleNamespace(
        id="p-lp018",
        sku="LP018",
        name='MSI Modern 15 H AI 15.6" FHD 60Hz Laptop',
        price_cents=149900,
        currency="USD",
        image_url=None,
        specs={"gpu": "Intel Arc Graphics", "refresh_hz": 60, "ram_gb": 16},
    )
    gaming = SimpleNamespace(
        id="p-gam001",
        sku="GAM-0001",
        name="Lenovo Legion 5 Gaming Laptop",
        price_cents=129900,
        currency="USD",
        image_url=None,
        specs={"gpu": "GeForce RTX 4060", "refresh_hz": 144, "ram_gb": 16},
    )

    monkeypatch.setattr(svc.catalog, "search_products", lambda query, limit=10: [weak])
    monkeypatch.setattr(svc.catalog, "list_products", lambda limit=400: [weak, gaming])
    monkeypatch.setattr(svc.catalog, "get_stock_by_product_ids", lambda ids: {"p-lp018": 10, "p-gam001": 8})

    candidates = svc.retrieve_candidates(
        "I am looking for a laptop for gaming. My budget is $1200 to $1800.",
        limit=1,
    )

    skus = [c["sku"] for c in candidates]
    assert "GAM-0001" in skus
    assert skus.index("GAM-0001") < skus.index("LP018")
    sp.reset_cache()
