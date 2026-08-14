from scripts.generate_runtime_requirements import ROOT, _locked_packages, _render


def test_committed_runtime_profiles_match_poetry_lock() -> None:
    import json

    definitions = json.loads(
        (ROOT / "config/runtime_dependency_profiles.json").read_text(encoding="utf-8")
    )
    packages, lock_hash = _locked_packages()
    for profile, definition in definitions.items():
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
