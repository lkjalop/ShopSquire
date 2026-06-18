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


# ── Profile-backed vocab (core/adapter excision) — parity + freshness invariants ──────────
def test_grounding_vocab_profile_union_keeps_all_inline_entries():
    """Excision invariant: the profile-backed accessors UNION the StoreProfile with the inline
    fallback, so no inline brand/line/alias/category is ever lost (parity-safe; profile only
    ADDS recognition)."""
    import src.app.services.grounding_ladder as g

    assert set(g._KNOWN_BRANDS) <= g._known_brands()
    assert set(g._BRAND_ALIASES.items()) <= set(g._brand_aliases().items())
    assert set(g._PRODUCT_LINES.items()) <= set(g._product_lines().items())
    assert set(g._CATEGORY_KW.keys()) <= set(g._category_kw().keys())


def test_grounding_categories_sourced_from_profile():
    from src.app.platform.store_profile import profile_slot
    assert isinstance(profile_slot("category_keywords", default=None), dict)


def test_catalog_brands_cache_reset_is_exposed():
    from src.app.services.grounding_ladder import reset_catalog_brands_cache, _CATALOG_BRANDS_CACHE
    _CATALOG_BRANDS_CACHE["brands"] = {"sentinel"}
    reset_catalog_brands_cache()
    assert _CATALOG_BRANDS_CACHE["brands"] is None


def test_visual_search_unavailable_emits_degraded_trace(monkeypatch):
    """Observability: when visual similarity is configured ON but the CLIP/FAISS backend is not
    loaded, grounding degrades to text-only — and that must be VISIBLE in the trace, not a silent
    no-op (the clip_unavailable silent gap)."""
    import src.app.services.grounding_ladder as g
    import src.app.services.visual_search as vs

    monkeypatch.setattr(vs, "is_available", lambda: False)
    monkeypatch.setattr(vs, "status", lambda: {"model_loaded": False, "faiss_available": False})

    events = []
    monkeypatch.setattr(
        "src.app.services.decision_log.log_trace_event",
        lambda *a, **k: events.append(a),
    )
    g.resolve_grounded_identity(
        "msi raider", image_bytes=b"fake", enable_visual_search=True, trace_id="t-vs-1",
    )
    degraded = [e for e in events if len(e) > 6 and e[1] == "stage_partial_failure"
                and isinstance(e[6], dict) and e[6].get("reason") == "visual_search_unavailable"]
    assert degraded, "expected a visual_search_unavailable degraded trace event"
    assert degraded[0][6]["degraded"] is True
