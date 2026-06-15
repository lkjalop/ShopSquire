from src.app.services.grounding_ladder import ground_identity


def _identity(brand=None, model=None, ptype="laptop", conf=0.7, gpu=None, ram=None):
    return {
        "identified": True, "brand": brand, "model": model, "product_type": ptype,
        "confidence": conf, "gpu_hint": gpu, "ram_gb_hint": ram,
    }


def test_user_typed_brand_is_authoritative_and_grounded():
    # No catalog/visual signal, but the user typed "MSI" → grounded, asserted.
    r = ground_identity("msi gaming laptop under 1900")
    assert r.brand == "msi"
    assert r.category == "laptop"
    assert r.tier <= 2
    assert r.residual_question is None


def test_user_product_line_climbs_to_brand_line_tier():
    r = ground_identity("looking for an msi raider")
    assert r.brand == "msi"
    assert r.product_line == "Raider"
    assert r.tier in (0, 1)
    assert r.confidence_label in ("likely", "confirmed")


def test_ungrounded_vlm_brand_is_dropped_and_asks_to_confirm():
    # Vision guesses "Razer" but the catalog has no Razer and no visual match.
    r = ground_identity(
        "good gaming laptop",
        vision_identity=_identity(brand="Razer", ptype="laptop", conf=0.7),
        catalog_brands={"msi", "asus", "dell", "hp"},
    )
    assert r.brand is None                      # not asserted — catalog can't confirm it
    assert r.category == "laptop"
    assert r.tier == 3                          # fell to category
    assert r.residual_field == "brand"
    assert r.residual_question["id"] == "confirm_brand_guess"


def test_visual_match_grounds_the_brand():
    # Vision says MSI AND a CLIP catalog match confirms MSI → grounded.
    r = ground_identity(
        "something like this for gaming",
        vision_identity=_identity(brand="MSI", model="Raider GE78", conf=0.7, gpu="RTX 4070"),
        visual_matches=[{"sku": "MSI-1", "name": "MSI Raider GE78", "brand": "MSI", "visual_score": 0.82}],
    )
    assert r.brand == "msi"
    assert r.product_line == "Raider"
    assert r.tier in (0, 1)
    assert r.grounded is True


def test_cross_source_brand_conflict_triggers_clarify():
    # Vision says Dell, OCR says Asus, user gave no brand → conflict, ask which.
    r = ground_identity(
        "gaming laptop",
        vision_identity=_identity(brand="Dell", conf=0.7),
        text_identity=_identity(brand="Asus", conf=0.8),
        catalog_brands={"dell", "asus"},
    )
    assert r.brand is None                       # not asserted under conflict
    assert r.residual_field == "brand"
    assert r.residual_question["id"] == "clarify_brand_conflict"
    assert any(c["field"] == "brand" for c in r.conflicts)


def test_authoritative_user_overrides_vision_disagreement():
    # User typed MSI; vision guessed Dell. User wins, no residual needed.
    r = ground_identity(
        "msi gaming laptop",
        vision_identity=_identity(brand="Dell", conf=0.6),
        catalog_brands={"msi", "dell"},
    )
    assert r.brand == "msi"
    assert r.residual_question is None


def test_generic_query_is_category_or_query_only():
    r = ground_identity("show me something good")
    assert r.tier == 4
    assert r.brand is None


def test_empty_query_is_safe():
    r = ground_identity("")
    assert r.tier == 4
    assert r.to_dict()["tier_name"] == "query_only"
