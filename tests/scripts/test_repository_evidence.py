import pytest

from scripts.check_repository_evidence import DOCUMENTS, check_links


@pytest.mark.parametrize("relative_root", ["source", ".artifacts/clean-checkout"])
def test_public_links_require_real_targets_and_anchors(tmp_path, relative_root):
    tmp_path = tmp_path / relative_root
    for name in DOCUMENTS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Present\n', encoding='utf-8')
    (tmp_path / 'README.md').write_text(
        '[valid](docs/portfolio/ENGINEERING_WALKTHROUGH.md#present)\n'
        '[missing](missing.md)\n'
        '[anchor](docs/portfolio/ENGINEERING_WALKTHROUGH.md#absent)\n'
        '[private](.artifacts/receipt.json)\n', encoding='utf-8',
    )
    checked, failures = check_links(tmp_path)
    assert checked == 1
    assert len(failures) == 3
    assert any('missing target' in failure for failure in failures)
    assert any('invalid anchor' in failure for failure in failures)
    assert any('non-public target' in failure for failure in failures)
