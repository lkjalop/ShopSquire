from scripts.check_source_file_sizes import evaluate_source_sizes, main


def test_no_new_source_file_exceeds_two_thousand_lines():
    assert main() == 0


def test_grandfathered_oversized_file_cannot_grow(tmp_path):
    source = tmp_path / "legacy.py"
    source.write_text("\n".join("pass" for _ in range(11)), encoding="utf-8")

    _, failures = evaluate_source_sizes(root=tmp_path, baseline={"legacy.py": 10})

    assert failures == ["OVERSIZE_GROWTH legacy.py: 11 lines exceeds ceiling 10"]


def test_grandfathered_oversized_file_may_shrink(tmp_path):
    source = tmp_path / "legacy.py"
    source.write_text("\n".join("pass" for _ in range(9)), encoding="utf-8")

    _, failures = evaluate_source_sizes(root=tmp_path, baseline={"legacy.py": 10})

    assert failures == []
