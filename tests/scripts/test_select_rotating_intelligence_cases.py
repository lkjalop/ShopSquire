from scripts.select_rotating_intelligence_cases import select_cases


def test_rotating_selector_is_seeded_excludes_known_titles_and_adds_negative():
    rows = [
        {"appid": 1, "title": "Known Game", "release_state": "released", "requirements_completeness": "complete"},
        {"appid": 2, "title": "New: Horizon", "release_state": "unreleased", "requirements_completeness": "none"},
        {"appid": 3, "title": "Fresh Alpha", "release_state": "released", "requirements_completeness": "partial"},
        {"appid": 4, "title": "Novel Beta", "release_state": "released", "requirements_completeness": "complete"},
    ]
    first = select_cases(rows, corpus="known game", seed="seed-17", count=3)
    second = select_cases(rows, corpus="known game", seed="seed-17", count=3)

    assert first == second
    assert all(row["title"] != "Known Game" for row in first)
    assert any("typo" in row["scenario"] for row in first)
    assert first[-1]["scenario"] == "fabricated_negative"
    assert first[-1]["appid"] is None
