"""Phase 1 — single formatter: assistant_message is never empty at the choke point."""
from __future__ import annotations

from src.app.routers.recommend import _finalize_answer, _recovery_answer


def test_existing_answer_unchanged():
    p = {"assistant_message": "Yes, $1800 is plenty.", "message": "x"}
    out = _finalize_answer(dict(p))
    assert out["assistant_message"] == "Yes, $1800 is plenty."  # 95% path: untouched


def test_message_promoted_when_assistant_blank():
    out = _finalize_answer({"assistant_message": "", "message": "No matching products found."})
    assert out["assistant_message"] == "No matching products found."


def test_empty_gets_recovery_answer():
    out = _finalize_answer({"constraints_used": {"budget_max": 400, "brands": ["asus"]}})
    am = out["assistant_message"].lower()
    assert am  # never empty
    assert "asus" in am and "$400" in out["assistant_message"]
    assert any(k in am for k in ("raise", "nearest", "other brand"))
    # message kept consistent
    assert out["message"] == out["assistant_message"]


def test_whitespace_only_is_treated_as_empty():
    out = _finalize_answer({"assistant_message": "   ", "constraints_used": {}})
    assert out["assistant_message"].strip()


def test_never_raises_on_bad_input():
    assert isinstance(_finalize_answer({}), dict)
    assert isinstance(_finalize_answer({"constraints_used": None}), dict)


def test_recovery_answer_verdict_first_with_upgrade_path():
    msg = _recovery_answer({"budget_max": 1200})
    assert msg.lower().startswith("no")
    assert "$1,200" in msg
    assert "raise your budget" in msg.lower()


def test_dereference_replaces_labels_with_product_names():
    from src.app.routers.recommend import _dereference_product_labels
    p = {"assistant_message": "The [1] is a solid pick; [2] is cheaper.",
         "results": [{"name": "MSI Katana 15"}, {"name": "Dell G15"}]}
    out = _dereference_product_labels(p)
    assert out["assistant_message"] == "The MSI Katana 15 is a solid pick; Dell G15 is cheaper."
    assert "[1]" not in out["assistant_message"] and "[2]" not in out["assistant_message"]


def test_dereference_leaves_unknown_labels_and_no_results():
    from src.app.routers.recommend import _dereference_product_labels
    p = {"assistant_message": "See [5].", "results": [{"name": "X"}]}
    assert _dereference_product_labels(p)["assistant_message"] == "See [5]."  # out of range -> unchanged
    assert _dereference_product_labels({"assistant_message": "hi", "results": []})["assistant_message"] == "hi"
