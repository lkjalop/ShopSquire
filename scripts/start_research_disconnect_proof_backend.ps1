$fixturePath = Join-Path $PSScriptRoot "dev_slow_searxng_fixture.py"
$fixture = Start-Process python `
    -ArgumentList @($fixturePath, "--port", "18888", "--delay-seconds", "2.5") `
    -PassThru -WindowStyle Hidden

$env:EXTERNAL_RESEARCH_ENABLED = "1"
$env:EXTERNAL_RESEARCH_SEARCH_URL = "http://127.0.0.1:18888/search?q={query}&format=json"
$env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = "1"
$env:EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED = "1"
$env:EXTERNAL_RESEARCH_RUNTIME_STATUS = "reachable"
$env:EXTERNAL_RESEARCH_PROVIDER_ID = "slow_local_searxng_disconnect_fixture"
$env:EXTERNAL_RESEARCH_PROVIDER_BILLING_CLASS = "free"
$env:EXTERNAL_RESEARCH_TENANT_ALLOWLIST = "default"
$env:EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY = "e2e-source-policy-reviewer"
$env:EXTERNAL_RESEARCH_SOURCE_LICENCE = "disconnect-certification-fixture"
$env:PORTFOLIO_DEMO_INVENTORY_PROFILE = "realistic"
$env:PRODUCT_CAPABILITY_TENANT_ALLOWLIST = "default"

try {
    & python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "disconnect proof migration failed" }
    & (Join-Path $PSScriptRoot "..\start_demo.ps1")
}
finally {
    if ($fixture -and -not $fixture.HasExited) {
        Stop-Process -Id $fixture.Id -Force
    }
}
