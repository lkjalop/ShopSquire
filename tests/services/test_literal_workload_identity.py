from src.app.services.recommendation_core.literal_workload_identity import (
    deterministic_additive_workload_continuation,
    deterministic_named_workload_switch,
    literal_game_identity_candidate,
    literal_software_identity_candidate,
    recover_literal_workload_identity,
)
from src.app.services.recommendation_core.semantic_coverage import (
    discard_covered_model_workload_echo,
)


def test_literal_game_identity_recovers_common_subject_switch_phrases():
    cases = {
        "what about Baldur's Gate 3? is 2500 good?": "Baldur's Gate 3",
        "can this laptop run Heroes of Might and Magic III Remake?": "Heroes of Might and Magic III Remake",
        "I want a laptop that can play Cyberpunk 2077": "Cyberpunk 2077",
        "I need a computer for Baldurs Gate 3": "Baldurs Gate 3",
        "Is AUD 3,000 excessive for Baldur’s Gate 3": "Baldur’s Gate 3",
    }
    for query, expected in cases.items():
        assert literal_game_identity_candidate(query) == (("game", expected),)


def test_literal_switch_rejects_generic_use_cases():
    assert literal_game_identity_candidate("I need a laptop for university") == ()
    assert literal_game_identity_candidate("I need a computer for digital twin simulations") == ()
    assert literal_game_identity_candidate("I need a laptop for university study") == ()
    assert literal_game_identity_candidate("I need a laptop for game development") == ()
    assert not deterministic_named_workload_switch("what about gaming?")
    assert deterministic_named_workload_switch("what about Baldur's Gate 3?")


def test_additive_workload_continuation_is_explicit_and_does_not_imply_identity():
    assert deterministic_additive_workload_continuation(
        "It must run Rockwell Emulate3D locally as well"
    )
    assert deterministic_additive_workload_continuation(
        "It also needs to support Siemens NX"
    )
    assert not deterministic_additive_workload_continuation("What about Rockwell Emulate3D?")
    assert not deterministic_additive_workload_continuation("It must be portable")


def test_named_local_application_resolves_ambiguous_workload_without_also():
    assert deterministic_additive_workload_continuation(
        "It must run Rockwell Emulate3D locally."
    )


def test_literal_software_identity_recovers_natural_processing_workload_switch():
    utterance = "I process large drone surveys in Agisoft Metashape. What hardware do I need?"
    assert literal_software_identity_candidate(utterance) == (
        ("software", "Agisoft Metashape"),
    )
    assert deterministic_named_workload_switch(utterance)
    assert recover_literal_workload_identity(utterance, [], set()) == [
        ("software", "Agisoft Metashape"),
    ]


def test_literal_software_identity_recovers_what_about_local_application():
    utterance = "What about Rockwell Emulate3D running locally?"
    assert literal_software_identity_candidate(utterance) == (
        ("software", "Rockwell Emulate3D"),
    )
    assert deterministic_named_workload_switch(utterance)


def test_literal_software_identity_survives_generic_taxonomy_coverage_filter():
    utterance = "I process large drone surveys in Agisoft Metashape. What hardware do I need?"
    assert discard_covered_model_workload_echo(
        query=utterance,
        use_cases=["image_processing"],
        workload_entities=[("software", "Agisoft Metashape")],
        node_path="so-1-10-1",
    ) == [("software", "Agisoft Metashape")]


def test_single_token_application_in_explicit_hardware_grammar_replaces_workload():
    utterance = "I need hardware for CupixWorks. Please inspect this page."
    assert literal_software_identity_candidate(utterance) == (("software", "CupixWorks"),)
    assert deterministic_named_workload_switch(utterance)
