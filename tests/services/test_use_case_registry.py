"""Unified use-case registry (Track E) — SMART capability model: intent → capability REQUIREMENTS,
price DERIVED from the real catalog (never hardcoded), with the drawing→touchscreen→Mac-escalates
example the user described."""
from src.app.services import use_case_registry as R


def test_match_use_cases_recovers_specific_registry_phrase():
    assert R.match_use_cases("I want to fine tune a 7b model locally") == [
        "ai_ml_workstation"
    ]


def test_match_use_cases_prefers_game_development_over_generic_game():
    assert R.match_use_cases("I need laptops for game development") == [
        "game_development"
    ]


def test_match_use_cases_ignores_collision_prone_short_abbreviations():
    assert R.match_use_cases("five A100 servers for my data team") == []


def test_match_use_cases_recovers_explicit_gaming_laptop_phrase():
    assert R.match_use_cases("I need gaming laptops for a studio") == ["gaming"]


def test_match_use_cases_recovers_generic_work_laptop_phrase():
    assert R.match_use_cases("what laptops for work should I buy") == ["office"]


def test_match_use_cases_recovers_stable_diffusion_workload():
    assert R.match_use_cases("stable diffusion image generation laptop") == [
        "ai_ml_workstation"
    ]
from src.app.services.catalog_read_model import VariantView


def _v(sku, title, price, specs=None):
    return VariantView(sku=sku, title=title, price_cents=price, specs=specs or {})


def test_intent_maps_to_capabilities_not_a_number():
    """drawing → real capability predicates (touchscreen + convertible/detachable form factor),
    NOT a hardcoded floor. This is the knowledge; price comes from the catalog."""
    got = R.resolve("electronics", "drawing")
    reqs = got["requirements"]
    assert reqs["touchscreen"] == ["==", True]
    assert reqs["form_factor"][0] == "in" and "convertible" in reqs["form_factor"][1]
    assert "budget_floor" not in got                      # no stored number
    assert got["budget_band_hint"] == [1200, 2200]        # advisory only


def test_floor_is_derived_from_real_catalog_products():
    """The drawing floor = the cheapest IN-CATALOG touchscreen 2-in-1 (read from its TITLE), not a
    stored number. Non-touch gaming laptops don't count even if cheaper."""
    catalog = [
        _v("GAM", "ASUS ROG Strix G16 Gaming Laptop (RTX 4060)", 129900, {"ram_gb": 32}),  # cheap, NOT touch
        _v("DELL2IN1", "Dell Inspiron 14 7440 2-in-1 Laptop", 119900, {"ram_gb": 16}),      # touch+convertible
        _v("YOGA", "Lenovo Yoga Slim 7i 14\" OLED Laptop", 149900, {"ram_gb": 16}),          # touch+convertible
    ]
    floor = R.derive_price_floor("electronics", "drawing", None, catalog)
    assert floor == 119900        # the Dell 2-in-1 — DERIVED; the cheaper gaming laptop fails touch


def test_brand_preference_escalates_floor_via_catalog_not_hardcode():
    """A shopper who narrows to Apple (a FILTERED candidate set) floors at the Mac price — the
    30-50% premium is EMERGENT from the catalog, nothing hardcodes it."""
    windows_2in1 = [_v("DELL", "Dell Inspiron 2-in-1 Laptop", 119900, {"ram_gb": 16})]
    # a Mac candidate set (touchscreen macs are rare, so use an iPad-class detachable Apple w/ touch)
    apple_touch = [_v("IPADP", "Apple iPad Pro 13 tablet", 287900, {"ram_gb": 16})]
    assert R.derive_price_floor("electronics", "drawing", None, windows_2in1) == 119900
    assert R.derive_price_floor("electronics", "drawing", None, apple_touch) == 287900   # escalated


def test_no_stocked_match_returns_none_not_a_guess():
    """Honest: if nothing in the candidate set carries the capability, there is NO floor to quote."""
    no_touch = [_v("A", "Plain Clamshell Laptop", 90000, {"ram_gb": 16})]
    assert R.derive_price_floor("electronics", "drawing", None, no_touch) is None


def test_variant_tightens_requirements():
    base = R.resolve("electronics", "gaming")
    aaa = R.resolve("electronics", "gaming", "aaa_heavy")
    assert base["requirements"]["gpu_vram_gb"] == [">=", 4]
    assert aaa["requirements"]["gpu_vram_gb"] == [">=", 8]     # variant tightens
    assert aaa["budget_band_hint"] == [1500, 3000]


def test_game_development_excludes_playing_games_without_code_rules():
    assert R.apply_use_case_exclusions(["gaming", "game_development", "university"]) == [
        "game_development", "university"
    ]
    assert R.apply_use_case_exclusions(["gaming"]) == ["gaming"]


def test_variant_routing_guide_is_data_owned():
    guide = R.variant_routing_guide(["game_development"])
    assert "unreal" in guide["game_development"]["unreal_realtime"]
    assert "short course" in guide["game_development"]["unity_course"]


def test_high_school_is_intent_variants_with_content_advisory():
    """The user's insight: high_school floor depends on intent (schooling vs gaming), and a minor
    requesting mature-game specs gets an ADVISORY, never a block."""
    assert R.resolve("electronics", "high_school", "schooling")["requirements"]["ram_gb"] == [">=", 8]
    assert R.resolve("electronics", "high_school", "serious_gaming")["requirements"]["gpu_vram_gb"] == [">=", 6]
    adv = R.content_advisory("electronics", "high_school")
    assert adv["persona"] == "minor" and "never a hard block" in adv["note"].lower()


def test_scaffold_verticals_load_empty_bound_to_taxonomy():
    for v in ("home", "appliances", "furniture"):
        assert R.list_use_cases(v) == []
        assert R.load_use_cases(v).get("host_nodes")


def test_case_workloads_retain_multiple_explicit_procurement_dimensions():
    assert R.match_case_workloads(
        "Engineering laptops for Unreal Engine, large CAD models and simulation."
    ) == ["game_development", "engineering_simulation"]
