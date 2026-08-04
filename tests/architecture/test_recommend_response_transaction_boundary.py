from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_response_transaction_is_v2_owned_after_legacy_archive():
    assert not (ROOT / "src/app/routers/recommend.py").exists()
    source = (
        ROOT / "src/app/services/recommend_response_transaction.py"
    ).read_text(encoding="utf-8")

    assert "def finalize_response_transaction(" in source
    assert "class ResponseTransactionDependencies" in source


def test_v2_cart_contract_does_not_import_legacy_router():
    source = (
        ROOT / "tests/test_recommend_with_trace_cart.py"
    ).read_text(encoding="utf-8")

    assert "src.app.routers.recommend" not in source
