from src.app.services.recommendation_core.literal_workload_identity import (
    deterministic_named_workload_switch,
    literal_game_identity_candidate,
)


def test_literal_game_identity_recovers_common_subject_switch_phrases():
    cases = {
        "what about Baldur's Gate 3? is 2500 good?": "Baldur's Gate 3",
        "can this laptop run Heroes of Might and Magic III Remake?": "Heroes of Might and Magic III Remake",
        "I want a laptop that can play Cyberpunk 2077": "Cyberpunk 2077",
        "I need a computer for Baldurs Gate 3": "Baldurs Gate 3",
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
