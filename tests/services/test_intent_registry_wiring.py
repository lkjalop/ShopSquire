"""Partial KB step 3 — the new use_case_registry's capability predicates now reach the LIVE
decision path. Before this, 'drawing' wasn't even in the router's vocabulary and touchscreen/
form_factor (boolean/enum, which the numeric constraint machinery and the legacy KB can't
express) never fired. This is the wiring that makes the marquee scenario real, not unit-only."""
from src.app.services.recommendation_core import intent_resolver as IR


def test_registry_use_cases_are_classifiable():
    known = IR.known_use_cases()
    assert "drawing" in known and "creative" in known      # smart intents now in the router vocab
    assert IR.normalize_use_case("drawing") == "drawing"


def test_drawing_injects_touchscreen_and_form_factor_for_electronics():
    reqs = IR.resolve(["drawing"], vertical="electronics")["requirements"]
    assert reqs["touchscreen"] == [("==", True)]           # boolean predicate the legacy KB can't hold
    assert reqs["form_factor"][0][0] == "in"               # enum predicate
    assert "convertible" in reqs["form_factor"][0][1]
    assert "ram_gb" in reqs                                # numeric registry req also injected


def test_no_vertical_means_no_injection_backward_compatible():
    reqs = IR.resolve(["drawing"], vertical=None)["requirements"]   # ungrounded → registry not consulted
    assert "touchscreen" not in reqs


def test_stated_numeric_wins_over_registry_fill():
    # an explicit RAM ask rides the numeric machinery; the registry only FILLS gaps, never overrides
    reqs = IR.resolve(["drawing"], model_requirements={"ram_gb": (">=", 32)},
                      vertical="electronics")["requirements"]
    assert any(tuple(p) == (">=", 32.0) for p in reqs["ram_gb"])   # stated 32 wins over registry 16
    assert reqs["touchscreen"] == [("==", True)]                   # gaps still filled
