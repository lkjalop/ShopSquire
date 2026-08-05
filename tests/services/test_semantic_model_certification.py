from scripts.certify_semantic_model_providers import _json_object, _prompt


def test_certification_prompt_forbids_model_owned_commerce_facts() -> None:
    prompt = _prompt("Find 20 chairs made from iron birch.")

    assert "Do not include hardware requirements" in prompt
    assert "prices, inventory or citations" in prompt
    assert "exact span from buyer request" in prompt


def test_certification_parser_accepts_json_fences_but_not_prose() -> None:
    assert _json_object('```json\n{"confidence": 0.5}\n```') == {"confidence": 0.5}
    assert _json_object("I think you should ask a question") is None
