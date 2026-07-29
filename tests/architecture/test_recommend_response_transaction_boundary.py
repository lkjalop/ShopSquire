from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_wrapper_delegates_to_v2_response_transaction():
    source = (ROOT / "src/app/routers/recommend.py").read_text(encoding="utf-8")
    active = source.split("def _with_trace(", 1)[1].split(
        "def _decision_log_writes_enabled",
        1,
    )[0]

    assert "finalize_response_transaction(" in active
    assert "ResponseTransactionDependencies(" in active


def test_v2_cart_contract_does_not_import_legacy_router():
    source = (
        ROOT / "tests/test_recommend_with_trace_cart.py"
    ).read_text(encoding="utf-8")

    assert "src.app.routers.recommend" not in source
