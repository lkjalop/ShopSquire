from scripts.generate_runtime_requirements import ROOT, _locked_packages, _render


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
