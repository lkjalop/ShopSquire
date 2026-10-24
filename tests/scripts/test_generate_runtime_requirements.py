from scripts.generate_runtime_requirements import ROOT, _locked_packages, _render
import pytest


def test_committed_runtime_profiles_match_poetry_lock() -> None:
    import json

    definitions = json.loads(
        (ROOT / "config/runtime_dependency_profiles.json").read_text(encoding="utf-8")
    )
    for profile, definition in definitions.items():
        packages, lock_hash = _locked_packages(group=definition.get("group", "main"))
        expected = _render(profile, definition["roots"], packages, lock_hash)
        assert (ROOT / definition["output"]).read_text(encoding="utf-8") == expected


def test_api_profile_contains_required_transitive_runtime_packages() -> None:
    requirements = (ROOT / "requirements/api-runtime.txt").read_text(encoding="utf-8")
    for package in ("starlette==", "anyio==", "greenlet==", "kombu==", "websockets=="):
        assert package in requirements


@pytest.mark.parametrize('suffix', ['', '-windows'])
def test_browser_fixture_imports_are_present_in_the_lean_test_profile(suffix):
    # Hosted image/performance positives reached missing imports after a
    # successful install. These bindings were locked only in the main closure.
    requirements = (ROOT / f'requirements/test-runtime{suffix}.txt').read_text(encoding='utf-8')
    for package in ('psutil==', 'pyzbar==', 'pytesseract=='):
        assert f'\n{package}' in requirements


def test_profile_outputs_stay_inside_requirements_directory() -> None:
    import json

    definitions = json.loads(
        (ROOT / "config/runtime_dependency_profiles.json").read_text(encoding="utf-8")
    )
    for definition in definitions.values():
        output = (ROOT / definition["output"]).resolve()
        assert output.is_relative_to((ROOT / "requirements").resolve())


def test_windows_profile_excludes_linux_only_packages(monkeypatch):
    import json
    import scripts.generate_runtime_requirements as generator
    monkeypatch.setattr(generator,'TARGET_ENV',generator.target_environment('windows'))
    packages,digest=generator._locked_packages()
    definitions=json.loads(generator.PROFILES.read_text())
    rendered=generator._render('api-runtime',definitions['api-runtime']['roots'],packages,digest)
    assert '\nuvloop==' not in rendered
    assert '\ncolorama==' in rendered
    assert (generator.ROOT/'requirements/api-runtime-windows.txt').read_text(encoding='utf-8')==rendered


def test_missing_main_marker_is_unconditional_when_main_group_is_present(tmp_path, monkeypatch):
    import scripts.generate_runtime_requirements as generator

    lock = tmp_path / 'poetry.lock'
    lock.write_text('''[[package]]
name = "api-root"
version = "1.0.0"
groups = ["main"]
[package.dependencies]
cffi = "*"

[[package]]
name = "cffi"
version = "2.1.1"
groups = ["main", "dev"]
markers = {dev = 'platform_python_implementation == "PyPy"'}

[[package]]
name = "dev-only"
version = "1.0.0"
groups = ["dev"]
markers = {dev = 'python_version >= "3.10"'}
''', encoding='utf-8')
    monkeypatch.setattr(generator, 'LOCK', lock)
    packages, digest = generator._locked_packages()
    rendered = generator._render('api-runtime', ['api-root'], packages, digest)
    assert '\ncffi==2.1.1\n' in rendered
    assert 'dev-only' not in packages
    dev_packages, _ = generator._locked_packages(group='dev')
    assert 'dev-only' in dev_packages
    assert 'api-root' not in dev_packages


@pytest.mark.parametrize('suffix', ['', '-windows'])
def test_vision_profile_has_one_owner_of_the_cv2_binary_namespace(suffix):
    packages = {
        line.split('==')[0] for line in
        (ROOT / f'requirements/vision-runtime{suffix}.txt').read_text(encoding='utf-8').splitlines()
        if line and not line.startswith('#')
    }
    owners = packages & {'opencv-python', 'opencv-python-headless',
                         'opencv-contrib-python', 'opencv-contrib-python-headless'}
    assert len(owners) == 1, f'Competing distributions own cv2: {sorted(owners)}'


def test_unrequested_ambiguous_packages_do_not_break_a_cpu_profile(tmp_path, monkeypatch):
    import scripts.generate_runtime_requirements as generator
    lock = tmp_path / 'poetry.lock'
    lock.write_text('''[[package]]
name = "api-root"
version = "1.0.0"
groups = ["main"]
[[package]]
name = "unrequested-gpu"
version = "1.0.0"
groups = ["main"]
[[package]]
name = "unrequested-gpu"
version = "2.0.0"
groups = ["main"]
''', encoding='utf-8')
    monkeypatch.setattr(generator, 'LOCK', lock)
    packages, digest = generator._locked_packages()
    assert '\napi-root==1.0.0\n' in generator._render('api-runtime', ['api-root'], packages, digest)
    with pytest.raises(RuntimeError, match='ambiguous locked versions for unrequested-gpu'):
        generator._render('gpu-runtime', ['unrequested-gpu'], packages, digest)


@pytest.mark.parametrize('platform,machine', [('linux', 'x86_64'), ('windows', 'AMD64')])
def test_target_architecture_is_independent_of_the_generator_host(monkeypatch, platform, machine):
    import scripts.generate_runtime_requirements as generator
    original = generator.default_environment
    monkeypatch.setattr(generator, 'default_environment', lambda: {**original(), 'platform_machine': 'ARM64'})
    assert generator.target_environment(platform)['platform_machine'] == machine
