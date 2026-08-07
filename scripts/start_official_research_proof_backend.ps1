$env:EXTERNAL_RESEARCH_ENABLED = "1"
$env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = "1"
$env:OFFICIAL_REQUIREMENTS_API_URL = "http://127.0.0.1:8099/requirements?q={query}"
$env:OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST = "docs.vendor.example"
$env:EXTERNAL_RESEARCH_TENANT_ALLOWLIST = "default"
$env:EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY = "e2e-source-policy-reviewer"
$env:EXTERNAL_RESEARCH_SOURCE_LICENCE = "test-fixture"

& (Join-Path $PSScriptRoot "..\start_demo.ps1")
