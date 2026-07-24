from pathlib import Path


def test_shopper_decision_trace_has_no_operator_commercial_actions():
    source = (Path(__file__).resolve().parents[1] / "frontend" / "src" /
              "components" / "DecisionTrace.tsx").read_text(encoding="utf-8")
    assert "/api/v1/admin/bi/product-projection" not in source
    assert "Request human review" not in source
    assert "Create catalogue draft" not in source
    assert "commercial-proposal-" not in source
