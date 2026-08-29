param(
    [string]$LogRoot = "",
    [switch]$NoMarketSignal,
    [switch]$LiveDemo,
    [string]$LiveModel = "qwen3:14b"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $LogRoot) {
    $LogRoot = Join-Path $env:TEMP ("shopsquire-recording-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

$redisContainer = "shopsquire-recording-redis"
$redisExists = docker ps -a --filter "name=^/$redisContainer$" --format "{{.Names}}"
if ($redisExists -eq $redisContainer) {
    docker start $redisContainer | Out-Null
} else {
    docker run --name $redisContainer -d -p 127.0.0.1:6381:6379 redis:7-alpine | Out-Null
}

$env:APP_ENV = "development"
$env:SHOPSQUIRE_RUNTIME_PROFILE = "demo_v2"
$env:USE_MOCK_LLM = "1"
$env:USE_OLLAMA_INTENT = "0"
$env:MODEL_WARMUP_ON_STARTUP = "0"
# Keep the quota boundary enabled in the production-shaped demo, but size it
# for repeated rehearsals. Inheriting a developer shell's small allowance made
# a valid cart amendment fail after the first RFQ draft.
$env:TOKEN_BUDGET_ENABLED = "1"
$env:TOKEN_BUDGET_GUEST_DAILY_TOKENS = "1000000000"
$env:TOKEN_BUDGET_GUEST_DAILY_USD = "1000000"
$env:COMMERCE_CATALOG_ENABLED = "1"
$env:FULFILLMENT_DEMO_ENABLED = "1"
$env:FULFILLMENT_CASES_ENABLED = "1"
$env:FULFILLMENT_AUTO_DRAFT_ON_COMMIT = "1"
$env:GATE_PROCUREMENT = "1"
$env:RECOMMEND_CORE_MODE = "primary"
$env:RECOMMEND_CART_SERVE = "1"
$env:RECOMMEND_PROCUREMENT_ADVICE_MODE = "on"
$env:RECOMMEND_POLICY_ANSWER_MODE = "on"
$env:RECOMMEND_SUPPORT_HANDOFF_MODE = "on"
$env:RECOMMEND_INVENTORY_READ_MODE = "on"
$env:RECOMMEND_NARRATION_MODE = "async"
$env:NARRATION_DEDICATED_EXECUTOR = "1"
$env:NARRATION_EXECUTOR_WORKERS = "2"
$env:NARRATION_EXECUTOR_QUEUE = "8"
$env:MULTI_INTENT_PLANNER_ENABLED = "1"
# The credential-free recording journey uses the same versioned, explicitly
# simulation-only research contract as hosted browser CI.  These flags never
# enable live egress and the semantic source-policy gate prevents this fixture
# from being used in staging/production or presented as independent evidence.
$env:SEMANTIC_RESEARCH_FIXTURES_ENABLED = "1"
$env:SEMANTIC_RESEARCH_FIXTURE_ID = "siemens_digital_twin_qualified_contract"
$env:SEMANTIC_SIMULATION_AUTHORITY_ENABLED = "1"
if ($LiveDemo) {
    # Live demo mode is intentionally distinct from the reproducible certificate
    # mode above. It uses local Ollama plus local SearXNG and records those live
    # dependencies rather than presenting fixture evidence as live research.
    $env:USE_MOCK_LLM = "0"
    $env:USE_OLLAMA_INTENT = "1"
    $env:MODEL_WARMUP_ON_STARTUP = "1"
    $env:ROUTER_MODEL_ENABLED = "1"
    $env:ROUTER_MODEL = $LiveModel
    $env:OLLAMA_DEFAULT_MODEL = $LiveModel
    $env:OLLAMA_MEDIUM_MODEL = $LiveModel
    $env:OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED = "1"
    $env:OPEN_WORLD_QUERY_MODEL = $LiveModel
    $env:PORTFOLIO_LOCAL_NARRATION_PREVIEW_ENABLED = "1"
    $env:PORTFOLIO_NARRATION_MODEL = $LiveModel
    $env:PORTFOLIO_NARRATION_TIMEOUT_SEC = "8"
    $env:EXTERNAL_RESEARCH_ENABLED = "1"
    $env:EXTERNAL_RESEARCH_AUTO_AUTHORIZED = "1"
    $env:STEAM_REQUIREMENTS_LIVE_ENABLED = "1"
    $env:VITE_EXTERNAL_RESEARCH_AUTO_ENABLED = "1"
    $env:EXTERNAL_RESEARCH_SEARCH_URL = "http://127.0.0.1:8888/search?q={query}&format=json"
    $env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = "1"
    $env:EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED = "1"
    $env:EXTERNAL_RESEARCH_PROVIDER_ID = "local_searxng"
    $env:EXTERNAL_RESEARCH_PROVIDER_BILLING_CLASS = "free"
    $env:EXTERNAL_RESEARCH_TENANT_ALLOWLIST = "default,portfolio-demo"
    $env:EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY = "leoma-project-owner"
    $env:EXTERNAL_RESEARCH_SOURCE_LICENCE = "portfolio-demo-policy-v1"
    $env:OFFICIAL_REQUIREMENTS_PUBLISHER_POLICY_ID = "leoma-publisher-policy-v1"
    $env:OFFICIAL_REQUIREMENTS_FRESHNESS_SLA_HOURS = "720"
    $env:SEMANTIC_RESEARCH_FIXTURES_ENABLED = "0"
    $env:SEMANTIC_SIMULATION_AUTHORITY_ENABLED = "0"

    try {
        $warmupBody = @{
            model = $LiveModel
            prompt = "Reply with READY only."
            stream = $false
            keep_alive = "30m"
            options = @{ num_predict = 8; temperature = 0 }
        } | ConvertTo-Json -Depth 4
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:11434/api/generate" `
            -ContentType "application/json" -Body $warmupBody -TimeoutSec 180 | Out-Null
        $ollamaTags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 10
        $liveManifest = $ollamaTags.models | Where-Object {
            $_.name -eq $LiveModel -or $_.model -eq $LiveModel
        } | Select-Object -First 1
        $liveDigest = [string]$liveManifest.digest
        if ($liveDigest -notmatch '^[a-fA-F0-9]{64}$') {
            throw "Ollama did not report a verifiable manifest digest for '$LiveModel'."
        }
        $env:ROUTER_MODEL_DIGEST = $liveDigest
        $env:OLLAMA_DEFAULT_MODEL_DIGEST = $liveDigest
        $env:OLLAMA_MEDIUM_MODEL_DIGEST = $liveDigest
        $env:OPEN_WORLD_QUERY_MODEL_DIGEST = $liveDigest
        $env:PORTFOLIO_NARRATION_MODEL_DIGEST = $liveDigest
        Write-Output "OLLAMA_PREWARMED=$LiveModel"
        Write-Output "OLLAMA_MANIFEST_VERIFIED=$($liveDigest.Substring(0, 12))"
    } catch {
        throw "Live demo requested, but Ollama prewarm failed for '$LiveModel': $($_.Exception.Message)"
    }
}
$env:SALES_RESPONSE_OVERSTOCK_UNITS = "10"
$env:SALES_RESPONSE_NUDGE_ENABLED = "1"
$env:MERCHANT_API_KEY = "local-merchant-key"
$env:OWNER_API_KEY = "local-owner-key"
$env:VITE_API_BASE = "http://127.0.0.1:8080"
$env:VITE_API_BASE_URL = "http://127.0.0.1:8080"
$env:REDIS_URL = "redis://127.0.0.1:6381/0"
$env:CELERY_BROKER_URL = "redis://127.0.0.1:6381/1"
$env:CELERY_RESULT_BACKEND = "redis://127.0.0.1:6381/2"
$env:SIEM_WEBHOOK_URL = "http://127.0.0.1:8099/events"
$env:SECURITY_HANDOFF_INLINE = "1"
$recordingDb = (Join-Path $LogRoot "recording.sqlite3") -replace "\\", "/"
$env:DATABASE_URL = "sqlite:///$recordingDb"
$env:DATABASE_URL_RO = $env:DATABASE_URL

& python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "recording_migration_failed" }
& python scripts/seed_demo_data.py
if ($LASTEXITCODE -ne 0) { throw "recording_demo_seed_failed" }
& python -m scripts.seed_portable_catalog
if ($LASTEXITCODE -ne 0) { throw "recording_catalog_seed_failed" }
& python -m scripts.seed_suppliers
if ($LASTEXITCODE -ne 0) { throw "recording_supplier_seed_failed" }
if (-not $NoMarketSignal) {
    & python -m scripts.demo_market_adaptation --direction spike --confidence 0.85 --severity critical
    if ($LASTEXITCODE -ne 0) { throw "recording_market_signal_seed_failed" }
}

# Browser tests and manual demo helpers are separate processes. Persist the
# recording database address so they cannot silently seed a developer database
# while the API reads this isolated one.
$recordingEnv = Join-Path $LogRoot "recording-env.ps1"
@"
`$env:DATABASE_URL = '$($env:DATABASE_URL)'
`$env:DATABASE_URL_RO = '$($env:DATABASE_URL_RO)'
`$env:REDIS_URL = '$($env:REDIS_URL)'
`$env:CELERY_BROKER_URL = '$($env:CELERY_BROKER_URL)'
`$env:CELERY_RESULT_BACKEND = '$($env:CELERY_RESULT_BACKEND)'
`$env:VITE_API_KEY = 'local-merchant-key'
`$env:PYTHON_EXECUTABLE = 'python'
"@ | Set-Content -LiteralPath $recordingEnv -Encoding utf8

$receiver = Start-Process python -ArgumentList @(
    "scripts/security_handoff_test_receiver.py", "--port", "8099",
    "--output", (Join-Path $LogRoot "siem-events.jsonl")
) -WorkingDirectory $repo -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogRoot "siem.out.log") `
    -RedirectStandardError (Join-Path $LogRoot "siem.err.log")
$api = Start-Process python -ArgumentList @(
    "-m", "uvicorn", "src.app.main:create_app", "--factory",
    "--host", "127.0.0.1", "--port", "8080"
) -WorkingDirectory $repo -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogRoot "backend.out.log") `
    -RedirectStandardError (Join-Path $LogRoot "backend.err.log")
$worker = Start-Process python -ArgumentList @(
    "-m", "celery", "-A", "src.app.workers.celery_app:celery_app",
    "worker", "--loglevel=INFO", "--pool=solo", "--hostname=shopsquire-recording-$PID@%h"
) -WorkingDirectory $repo -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogRoot "worker.out.log") `
    -RedirectStandardError (Join-Path $LogRoot "worker.err.log")
$storefront = Start-Process npm.cmd -ArgumentList @(
    "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"
) -WorkingDirectory (Join-Path $repo "frontend") -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogRoot "storefront.out.log") `
    -RedirectStandardError (Join-Path $LogRoot "storefront.err.log")
$admin = Start-Process npm.cmd -ArgumentList @(
    "run", "dev", "--", "--host", "127.0.0.1", "--port", "3001"
) -WorkingDirectory (Join-Path $repo "src/frontend/admin-react") -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogRoot "admin.out.log") `
    -RedirectStandardError (Join-Path $LogRoot "admin.err.log")

Write-Output "LOG_ROOT=$LogRoot"
Write-Output "PIDS receiver=$($receiver.Id) api=$($api.Id) worker=$($worker.Id) storefront=$($storefront.Id) admin=$($admin.Id)"
Write-Output "RECORDING_ENV=$recordingEnv"
Write-Output "STOREFRONT=http://127.0.0.1:5173 ADMIN=http://127.0.0.1:3001 API=http://127.0.0.1:8080/docs"
Write-Output "ADMIN_KEY=local-owner-key"
