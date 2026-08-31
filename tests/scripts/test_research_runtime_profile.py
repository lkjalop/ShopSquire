from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_FLAGS = (
    "ROUTER_MODEL_ENABLED",
    "EXTERNAL_RESEARCH_ENABLED",
    "EXTERNAL_RESEARCH_AUTO_AUTHORIZED",
    "STEAM_REQUIREMENTS_LIVE_ENABLED",
    "VITE_EXTERNAL_RESEARCH_AUTO_ENABLED",
)


def test_live_and_recording_profiles_align_all_research_controls():
    for relative in (
        "scripts/start_live_procurement_demo.ps1",
        "scripts/start_recording_stack.ps1",
        "scripts/start_portfolio_demo_backend.ps1",
    ):
        script = (ROOT / relative).read_text(encoding="utf-8")
        for flag in RUNTIME_FLAGS:
            env_assignment = f'$env:{flag} = "1"'
            map_assignment = f"{flag} = '1'"
            assert env_assignment in script or map_assignment in script, (
                f"{relative} does not enable {flag}"
            )

    portfolio = (ROOT / "scripts/start_portfolio_demo_backend.ps1").read_text(
        encoding="utf-8"
    )
    assert "RESEARCH_POLICY_PROFILE = 'demo-safe-auto-v1'" in portfolio

    live = (ROOT / "scripts/start_live_procurement_demo.ps1").read_text(encoding="utf-8")
    assert '$env:ROUTER_MODEL_DIGEST = $routerDigest' in live
    assert '$env:REDIS_URL = "redis://127.0.0.1:6381/0"' in live


def test_repository_defaults_remain_fail_closed_outside_explicit_live_profiles():
    import json

    flags = json.loads((ROOT / "config/feature_flags.json").read_text(encoding="utf-8"))
    assert flags["EXTERNAL_RESEARCH_ENABLED"] is False
    assert flags["STEAM_REQUIREMENTS_LIVE_ENABLED"] is False


def test_live_recording_profile_runs_query_planner_on_an_isolated_task_stream():
    script = (ROOT / "scripts/start_recording_stack.ps1").read_text(encoding="utf-8")

    assert '$env:TASK_CONSUMER_ENABLED = "1"' in script
    assert '$env:TASK_STREAM_NAME = "shopsquire:tasks:recording:$recordingRunKey"' in script
    assert "`$env:TASK_CONSUMER_ENABLED" in script
    assert "`$env:TASK_STREAM_NAME" in script
    assert '[string]$QueryModel = "granite4:micro"' in script
    assert '$env:OPEN_WORLD_QUERY_MODEL = $QueryModel' in script
    assert 'QUERY_PLANNER_PREWARMED=$QueryModel' in script


def test_local_discovery_profile_uses_a_bounded_working_engine_set():
    settings = (ROOT / "config/searxng/settings.yml").read_text(encoding="utf-8")

    assert "keep_only:" in settings
    assert "- privacywall" in settings
    assert "- yandex" in settings
    assert "- baidu" not in settings
    assert "- bing" not in settings
    assert "- mwmbl" not in settings
    assert "- mojeek" not in settings
    assert "request_timeout: 3.2" in settings
    assert "max_request_timeout: 3.6" in settings


def test_recording_restart_snapshot_preserves_demo_v2_modes():
    script = (ROOT / "scripts/start_recording_stack.ps1").read_text(encoding="utf-8")

    for setting in (
        "SHOPSQUIRE_RUNTIME_PROFILE",
        "RECOMMEND_CORE_MODE",
        "RECOMMEND_CART_SERVE",
        "RECOMMEND_PROCUREMENT_ADVICE_MODE",
        "RECOMMEND_POLICY_ANSWER_MODE",
        "RECOMMEND_SUPPORT_HANDOFF_MODE",
        "RECOMMEND_INVENTORY_READ_MODE",
    ):
        assert f"`$env:{setting} = '" in script
