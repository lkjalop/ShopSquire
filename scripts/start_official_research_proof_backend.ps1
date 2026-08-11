$env:EXTERNAL_RESEARCH_ENABLED = "1"
$env:EXTERNAL_RESEARCH_SEARCH_URL = "http://127.0.0.1:8888/search?q={query}&format=json"
$env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = "1"
$env:EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED = "1"
$env:EXTERNAL_RESEARCH_PROVIDER_ID = "local_searxng"
$env:EXTERNAL_RESEARCH_PROVIDER_BILLING_CLASS = "free"
$env:DISCOVERY_ENGINE_RELIABILITY_DB_PATH = (Join-Path $PSScriptRoot "..\discovery-engine-health.db")
$env:OFFICIAL_REQUIREMENTS_API_URL = "http://127.0.0.1:8099/requirements?q={query}"
$env:OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST = "docs.vendor.example"
$env:EXTERNAL_RESEARCH_TENANT_ALLOWLIST = "default"
$env:EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY = "e2e-source-policy-reviewer"
$env:EXTERNAL_RESEARCH_SOURCE_LICENCE = "test-fixture"
$env:PORTFOLIO_DEMO_INVENTORY_PROFILE = "realistic"
$env:PRODUCT_CAPABILITY_TENANT_ALLOWLIST = "default"
$env:PRODUCT_CAPABILITY_ASUS_OFFICIAL_SPECS_URL = "https://rog.asus.com/au/laptops/rog-zephyrus/rog-zephyrus-duo-2026/spec/"
$env:PRODUCT_CAPABILITY_ASUS_OFFICIAL_SPECS_FORMAT = "asus_html"

# The upload lane persists an append-only artifact-security verdict before
# extracted buyer text can enter a shopping case.  A legacy demo database can
# contain application tables without an Alembic version, which otherwise makes
# every valid PNG/PDF/TXT upload degrade at that security boundary.
& python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "official research proof migration failed" }

& (Join-Path $PSScriptRoot "..\start_demo.ps1")
