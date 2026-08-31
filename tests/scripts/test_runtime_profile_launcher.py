from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_one_launcher_names_fixture_live_demo_and_production_profiles():
    script = (ROOT / "scripts" / "start_shopsquire_profile.ps1").read_text(
        encoding="utf-8"
    )
    assert 'ValidateSet("fixture", "demo-live", "production")' in script
    assert '"fixture" {' in script and 'start_recording_stack.ps1' in script
    assert '"demo-live" {' in script and 'LiveDemo = $true' in script
    assert '"production" {' in script
    assert 'run_production_shaped_browser_battery.ps1' in script
    assert 'KeepServices' in script
