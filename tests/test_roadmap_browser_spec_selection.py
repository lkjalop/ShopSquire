"""A browser receipt must cover every explicitly requested scenario file."""
import pytest

from scripts.run_roadmap_browser import validate_specs, soak_buyers


def test_persistent_runtime_replays_enroll_distinct_buyers_without_changing_security_limits():
    prefix, bindings = soak_buyers(28800, 'owned-tenant', 'abc12345-rest')
    assert prefix == 'ss-abc12345'
    assert len(bindings) == 481
    assert bindings['ss-abc12345-1'] == ['owned-tenant']
    assert bindings['ss-abc12345-481'] == ['owned-tenant']
    assert soak_buyers(0, 'owned-tenant', 'abc') == ('', {})


def test_missing_spec_is_rejected_even_beside_valid_spec(tmp_path):
    directory = tmp_path / 'frontend' / 'e2e'
    directory.mkdir(parents=True)
    (directory / 'valid.spec.ts').write_text('test fixture', encoding='utf-8')
    with pytest.raises(ValueError, match='missing_browser_spec'):
        validate_specs(tmp_path, ['valid.spec.ts', 'typo.spec.ts'])


def test_specs_are_exact_existing_files_inside_e2e(tmp_path):
    directory = tmp_path / 'frontend' / 'e2e'
    directory.mkdir(parents=True)
    (directory / 'valid.spec.ts').write_text('test fixture', encoding='utf-8')
    assert validate_specs(tmp_path, ['valid.spec.ts']) == ['frontend/e2e/valid.spec.ts']
    for invalid in ['../valid.spec.ts', '.*', str(tmp_path / 'external.spec.ts')]:
        with pytest.raises(ValueError):
            validate_specs(tmp_path, [invalid])
