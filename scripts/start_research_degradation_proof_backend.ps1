$env:EXTERNAL_RESEARCH_ENABLED = "1"
$env:EXTERNAL_RESEARCH_SEARCH_URL = "http://127.0.0.1:65530/search?q={query}&format=json"
$env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = "1"
$env:EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED = "1"
$env:EXTERNAL_RESEARCH_RUNTIME_STATUS = "unreachable"
$env:EXTERNAL_RESEARCH_PROVIDER_ID = "unreachable_local_searxng_fixture"
$env:EXTERNAL_RESEARCH_PROVIDER_BILLING_CLASS = "free"
$env:EXTERNAL_RESEARCH_TENANT_ALLOWLIST = "default"
$env:EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY = "e2e-source-policy-reviewer"
$env:EXTERNAL_RESEARCH_SOURCE_LICENCE = "test-fixture"
$env:PORTFOLIO_DEMO_INVENTORY_PROFILE = "realistic"
$env:PRODUCT_CAPABILITY_TENANT_ALLOWLIST = "default"

& python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "degradation proof migration failed" }
& (Join-Path $PSScriptRoot "..\start_demo.ps1")
