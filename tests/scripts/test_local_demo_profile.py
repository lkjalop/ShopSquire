"""Native launcher contract: the configured local model port is the only allowed port."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_native_powershell_profile_uses_exact_configured_port(monkeypatch):
    powershell = shutil.which('pwsh') or shutil.which('powershell')
    if not powershell:
        pytest.skip('Native PowerShell is unavailable on this platform')
    script = ROOT / 'scripts/local_demo_runtime.ps1'
    command = ". '" + str(script).replace("'", "''") + "'; @{url=$env:OLLAMA_URL; allowlist=$env:INTERNAL_SERVICE_ALLOWLIST; private=$env:SSRF_ALLOW_PRIVATE} | ConvertTo-Json -Compress"
    result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, check=True, timeout=15)
    actual = json.loads(result.stdout)
    profile = json.loads((ROOT / 'config/local_demo_runtime.json').read_text())
    port = profile['ollama_port']
    assert actual['url'] == f'http://127.0.0.1:{port}'
    assert actual['allowlist'] == f'127.0.0.1:{port},localhost:{port}'
    assert actual['private'] == '0'
    monkeypatch.setenv('INTERNAL_SERVICE_ALLOWLIST', actual['allowlist'])
    monkeypatch.setenv('SSRF_ALLOW_PRIVATE', actual['private'])
    from src.app.security.url_guard import validate_outbound_url
    assert validate_outbound_url(actual['url'])[0]
    assert not validate_outbound_url('http://169.254.169.254/latest/meta-data')[0]
    assert not validate_outbound_url(f'http://127.0.0.1:{port + 1}')[0]


def test_launcher_does_not_override_the_shared_allowlist():
    assert 'INTERNAL_SERVICE_ALLOWLIST' not in (ROOT / 'start_demo.ps1').read_text(encoding='utf-8')
