"""Attribute layer: data-driven defs, unit conversion, clamping, honest drops, unit-anchored
extraction with GB-ambiguity surfaced (never guessed), and tri-state requirement evaluation."""
from src.app.services.attribute_registry import (
    apply_derivations,
    defs_union,
    derivations_union,
    evaluate_requirements,
    extract_keyed_quantity_requirements,
    extract_quantities,
    load_defs,
    meets,
    normalize_specs,
    normalize_value,
    registered_verticals,
)

EL = load_defs("electronics")
PH = load_defs("pharmacy")
FA = load_defs("fashion")


# ── loading ───────────────────────────────────────────────────────────────────

def test_defs_load_per_vertical_and_union():
    assert "ram_gb" in EL and "strength_mg" in PH and "material" in FA
    assert load_defs("no-such-vertical") == {}
    merged = defs_union(("electronics", "pharmacy", "fashion"))
    assert {"ram_gb", "strength_mg", "material"} <= set(merged)


def test_registered_verticals_are_discovered_from_installed_data():
    assert {"electronics", "pharmacy", "fashion"} <= set(registered_verticals())


# ── value normalization ───────────────────────────────────────────────────────

def test_quantity_unit_conversion():
    assert normalize_value(EL["storage_gb"], "1TB") == 1024
    assert normalize_value(EL["storage_gb"], "512 gb") == 512
    assert normalize_value(PH["strength_mg"], "0.5g") == 500
    assert normalize_value(PH["volume_ml"], "1l") == 1000
    assert normalize_value(EL["ram_gb"], 16) == 16


def test_bounds_catch_the_live_ram512_data_bug():
    # the live catalog has ram_gb=512 (storage stuffed into the RAM field) — bounds refuse it
    assert normalize_value(EL["ram_gb"], 512) is None
    assert normalize_value(EL["refresh_hz"], 9999) is None


def test_unknown_unit_is_distrust_not_guess():
    assert normalize_value(EL["ram_gb"], "16 bananas") is None


def test_enum_aliases_and_unknowns():
    assert normalize_value(EL["wifi"], "802.11ax") == "Wi-Fi 6"
    assert normalize_value(EL["os"], "win11") == "Windows 11"
    assert normalize_value(FA["material"], "faux leather") == "vegan leather"
    assert normalize_value(FA["material"], "unobtainium") is None


def test_boolean_literals():
    assert normalize_value(EL["gpu_discrete"], "yes") is True
    assert normalize_value(EL["gpu_discrete"], 0) is False
    assert normalize_value(EL["gpu_discrete"], "maybe") is None


def test_graphics_memory_models_do_not_conflate_unified_memory_with_vram():
    unified, dropped = normalize_specs({
        "graphics_architecture": "unified",
        "graphics_memory_model": "unified memory",
        "unified_memory_gb": 24,
        "native_metal": True,
        "native_cuda": False,
        "graphics_capability_source": "https://support.apple.com/en-us/121552",
    }, EL)

    assert not dropped
    assert unified["graphics_architecture"] == "unified"
    assert unified["graphics_memory_model"] == "unified_memory"
    assert unified["unified_memory_gb"] == 24
    assert unified["native_metal"] is True
    assert unified["native_cuda"] is False
    assert "gpu_vram_gb" not in unified


def test_dedicated_and_external_graphics_are_distinct_architectures():
    dedicated, _ = normalize_specs({
        "graphics_architecture": "dedicated",
        "graphics_memory_model": "dedicated video memory",
        "gpu_vram_gb": 8,
    }, EL)
    external, _ = normalize_specs({
        "graphics_architecture": "egpu",
        "graphics_memory_model": "external video memory",
        "gpu_vram_gb": 12,
    }, EL)

    assert dedicated["graphics_architecture"] == "dedicated_discrete"
    assert external["graphics_architecture"] == "external_discrete"


def test_graphics_architecture_is_derived_from_validated_discrete_fact():
    dedicated = apply_derivations(
        {"gpu_discrete": True}, derivations_union(("electronics",)), EL)
    integrated = apply_derivations(
        {"gpu_discrete": False}, derivations_union(("electronics",)), EL)

    assert dedicated["graphics_architecture"] == "dedicated_discrete"
    assert dedicated["graphics_memory_model"] == "dedicated_vram"
    assert integrated["graphics_architecture"] == "integrated_shared"
    assert integrated["graphics_memory_model"] == "shared_system"
    assert integrated["gpu_vram_gb"] == 0


# ── spec-dict normalization ───────────────────────────────────────────────────

def test_normalize_specs_maps_aliases_and_reports_drops():
    attrs, dropped = normalize_specs(
        {"memory": "16GB", "display_inches": 15.6, "wifi": "Wi-Fi 6E",
         "ram_gb": 512, "mystery_field": "x"}, EL)
    assert attrs == {"ram_gb": 16, "display_in": 15.6, "wifi": "Wi-Fi 6E"}
    reasons = {d["key"]: d["reason"] for d in dropped}
    assert reasons["ram_gb"] == "unparseable_or_out_of_bounds"   # the 512 bug, visibly dropped
    assert reasons["mystery_field"] == "unknown_key"             # schema drift is visible


def test_pharmacy_and_fashion_same_mechanism():
    attrs, _ = normalize_specs({"dose": "500mg", "volume": "500ml"}, PH)
    assert attrs == {"strength_mg": 500, "volume_ml": 500}
    attrs, _ = normalize_specs({"fabric": "linen", "fit": "wrap"}, FA)
    assert attrs == {"material": "linen", "fit": "wrap"}


# ── unit-anchored text extraction ─────────────────────────────────────────────

def test_extraction_unambiguous_units():
    assigned, ambiguous = extract_quantities(
        'Blaupunkt 27" FHD 240Hz Curved Gaming Monitor', EL)
    assert assigned["refresh_hz"] == 240 and assigned["display_in"] == 27
    assert "gb" not in ambiguous


def test_extraction_gb_is_ambiguous_never_assigned():
    assigned, ambiguous = extract_quantities("Laptop 16GB RAM 512GB SSD RTX 4060 8GB", EL)
    assert "ram_gb" not in assigned and "storage_gb" not in assigned and "gpu_vram_gb" not in assigned
    assert sorted(ambiguous["gb"]) == [8.0, 16.0, 512.0]   # surfaced for the MODEL to assign


def test_keyed_quantity_requirements_resolve_shared_units_from_registry():
    assert extract_keyed_quantity_requirements(
        "only models with 16GB RAM or more and storage at least 1TB", EL
    ) == {"ram_gb": [(">=", 16.0)], "storage_gb": [(">=", 1024.0)]}
    assert extract_keyed_quantity_requirements("VRAM at most 8GB", EL) == {
        "gpu_vram_gb": [("<=", 8.0)]
    }


def test_extraction_pharmacy_spf_and_ml():
    assigned, _ = extract_quantities("SPF50+ Sunscreen 200ml", PH)
    assert assigned == {"spf": 50, "volume_ml": 200}


def test_extraction_keeps_max_per_key_and_respects_bounds():
    assigned, _ = extract_quantities("120Hz native, up to 165Hz overclocked", EL)
    assert assigned["refresh_hz"] == 165
    assigned, _ = extract_quantities("9999Hz nonsense", EL)
    assert "refresh_hz" not in assigned


# ── tri-state requirements ────────────────────────────────────────────────────

def test_meets_tri_state():
    attrs = {"ram_gb": 16, "refresh_hz": 144}
    assert meets(attrs, "ram_gb", ">=", 16) is True
    assert meets(attrs, "ram_gb", ">=", 32) is False
    assert meets(attrs, "gpu_vram_gb", ">=", 8) is None    # unknown stays unknown


def test_evaluate_requirements_verdicts():
    attrs = {"ram_gb": 16, "refresh_hz": 144}
    r = evaluate_requirements(attrs, {"ram_gb": (">=", 8), "refresh_hz": (">=", 120)})
    assert r["overall"] == "meets"
    r = evaluate_requirements(attrs, {"ram_gb": (">=", 32)})
    assert r["overall"] == "fails"
    r = evaluate_requirements(attrs, {"ram_gb": (">=", 8), "gpu_vram_gb": (">=", 8)})
    assert r["overall"] == "unknown" and r["unknown_keys"] == ["gpu_vram_gb"]
    assert evaluate_requirements(attrs, {})["overall"] == "unknown"
