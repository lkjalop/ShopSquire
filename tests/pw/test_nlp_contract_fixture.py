from src.app.services.nlp_contract import DeterministicFixture


def test_deterministic_fixture_basic():
    f = DeterministicFixture(label="test-fixture")
    res = f.infer("rank these", candidates=[{"sku": "A1"}, {"sku": "B2"}])
    assert res.reasons and res.reasons[0].startswith("fixture:")
    assert isinstance(res.scores, dict)
    assert "A1" in res.scores
