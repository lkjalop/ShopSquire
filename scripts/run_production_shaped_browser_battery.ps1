param(
    [string]$ArtifactRoot = "",
    [switch]$KeepServices
)

$ErrorActionPreference = "Stop"
$pgName = "shopsquire-live-pg"
$redisName = "shopsquire-live-redis"
if (-not $ArtifactRoot) {
    $ArtifactRoot = Join-Path $env:TEMP (
        "shopsquire-live-" + [guid]::NewGuid().ToString("N")
    )
}
$resolvedRepo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
$processes = @()

function Assert-NativeSuccess([string]$Label) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Tail-IfPresent([string]$Name) {
    $path = Join-Path $ArtifactRoot $Name
    if (Test-Path -LiteralPath $path) {
        Write-Output "LOG=$Name"
        Get-Content -LiteralPath $path | Select-Object -Last 60
    }
}

docker run --name $pgName --rm -d --tmpfs /var/lib/postgresql/data `
    -e POSTGRES_PASSWORD=shopsquire_test -e POSTGRES_DB=shopsquire `
    -p 55434:5432 pgvector/pgvector:pg16 | Out-Null
Assert-NativeSuccess "live_postgres_start"
docker run --name $redisName --rm -d -p 56379:6379 redis:7-alpine | Out-Null
Assert-NativeSuccess "live_redis_start"

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker exec $pgName pg_isready -U postgres -d shopsquire | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "live_postgres_not_ready"
    }

    $env:APP_ENV = "testing"
    $env:DATABASE_URL = (
        "postgresql+psycopg2://postgres:shopsquire_test@" +
        "127.0.0.1:55434/shopsquire"
    )
    $env:DATABASE_URL_RO = $env:DATABASE_URL
    $env:REDIS_URL = "redis://127.0.0.1:56379/0"
    $env:CELERY_BROKER_URL = "redis://127.0.0.1:56379/1"
    $env:CELERY_RESULT_BACKEND = "redis://127.0.0.1:56379/2"
    $env:CELERY_HMAC_KEY = "local-browser-worker-signing-key"
    $env:SHOPSQUIRE_RUNTIME_PROFILE = "demo_v2"
    $env:RECOMMEND_CORE_MODE = "primary"
    $env:RECOMMEND_CART_SERVE = "1"
    $env:RECOMMEND_PROCUREMENT_ADVICE_MODE = "on"
    $env:RECOMMEND_POLICY_ANSWER_MODE = "on"
    $env:RECOMMEND_SUPPORT_HANDOFF_MODE = "on"
    $env:RECOMMEND_INVENTORY_READ_MODE = "on"
    $env:MULTI_INTENT_PLANNER_ENABLED = "1"
    $env:FULFILLMENT_DEMO_ENABLED = "1"
    $env:GATE_PROCUREMENT = "1"
    $env:USE_MOCK_LLM = "1"
    $env:USE_OLLAMA_INTENT = "0"
    $env:MODEL_WARMUP_ON_STARTUP = "0"
    $env:EMAIL_CONNECTOR_IDENTITY_MODE = "shared_secret"
    $env:GMAIL_INGEST_SECRET = "local-browser-ingress-only"
    $env:LIVE_GMAIL_INGEST_SECRET = "local-browser-ingress-only"
    $env:EMAIL_EVIDENCE_ACTIVE_KEY_ID = "local-v1"
    $env:EMAIL_EVIDENCE_KEYS = (
        "local-v1:000102030405060708090a0b0c0d0e0f" +
        "101112131415161718191a1b1c1d1e1f"
    )
    $env:RATE_LIMIT_PER_IP_PER_MIN = "10000"
    $env:RATE_LIMIT_PER_MINUTE_IP = "10000"
    $env:RATE_LIMIT_PER_MINUTE_KEY = "10000"

    python -m alembic upgrade head *>&1 |
        Tee-Object -FilePath (Join-Path $ArtifactRoot "migration.log") | Out-Null
    Assert-NativeSuccess "live_migration"
    python scripts/seed_demo_data.py *>&1 |
        Tee-Object -FilePath (Join-Path $ArtifactRoot "seed.log") | Out-Null
    Assert-NativeSuccess "live_seed"

    $processes += Start-Process -FilePath python -ArgumentList @(
        "-m", "uvicorn", "src.app.main:create_app", "--factory",
        "--host", "127.0.0.1", "--port", "8080"
    ) -WorkingDirectory $resolvedRepo -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "backend.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "backend.err.log")
    $processes += Start-Process -FilePath python -ArgumentList @(
        "-m", "celery", "-A", "src.app.workers.celery_app:celery_app",
        "worker", "--loglevel=INFO", "--pool=solo"
    ) -WorkingDirectory $resolvedRepo -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "worker.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "worker.err.log")
    $processes += Start-Process -FilePath npm.cmd -ArgumentList @(
        "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"
    ) -WorkingDirectory (Join-Path $resolvedRepo "frontend") `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "storefront.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "storefront.err.log")
    $processes += Start-Process -FilePath npm.cmd -ArgumentList @(
        "run", "dev", "--", "--host", "127.0.0.1", "--port", "3001"
    ) -WorkingDirectory (Join-Path $resolvedRepo "src/frontend/admin-react") `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "admin.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "admin.err.log")

    $stackReady = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $health = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:8080/healthz" -TimeoutSec 5
            $store = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:5173" -TimeoutSec 2
            $admin = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:3001" -TimeoutSec 2
            if (
                $health.StatusCode -eq 200 -and
                $store.StatusCode -eq 200 -and
                $admin.StatusCode -eq 200
            ) {
                $stackReady = $true
                break
            }
        }
        catch {
            # The bounded readiness loop reports process logs on failure.
        }
        if ($processes[0].HasExited) {
            throw "backend_exited_before_ready"
        }
        Start-Sleep -Seconds 1
    }
    if (-not $stackReady) {
        throw "live_stack_not_ready"
    }

    python -m celery -A src.app.workers.celery_app:celery_app `
        inspect ping --timeout 10 *>&1 |
        Tee-Object -FilePath (Join-Path $ArtifactRoot "worker-ping.log") |
        Out-Null
    Assert-NativeSuccess "live_worker_ping"

    Push-Location (Join-Path $resolvedRepo "frontend")
    try {
        $reactProcess = Start-Process -FilePath npx.cmd -ArgumentList @(
            "playwright", "test", "--reporter=line", "--workers=1"
        ) -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru `
            -Wait -RedirectStandardOutput (
                Join-Path $ArtifactRoot "react-playwright.log"
            ) -RedirectStandardError (
                Join-Path $ArtifactRoot "react-playwright.err.log"
            )
        $reactExit = $reactProcess.ExitCode
    }
    finally {
        Pop-Location
    }

    $env:RUN_LIVE_BROWSER_TESTS = "1"
    $env:LIVE_SHOPPER_URL = "http://127.0.0.1:5173"
    $env:LIVE_ADMIN_URL = "http://127.0.0.1:3001"
    $spaProcess = Start-Process -FilePath python -ArgumentList @(
        "-m", "pytest", "-vv", "-s",
        "tests/e2e/test_procurement_malicious_reply_playwright.py",
        "tests/e2e/test_live_policy_trace.py",
        "tests/e2e/test_live_procurement_closed_loop.py"
    ) -WorkingDirectory $resolvedRepo -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardOutput (
            Join-Path $ArtifactRoot "spa-regressions.log"
        ) -RedirectStandardError (
            Join-Path $ArtifactRoot "spa-regressions.err.log"
        )
    $spaExit = $spaProcess.ExitCode

    Write-Output "LIVE_STACK_ARTIFACTS=$ArtifactRoot"
    Write-Output "REACT_PLAYWRIGHT_EXIT=$reactExit"
    Write-Output "SPA_REGRESSIONS_EXIT=$spaExit"
    Tail-IfPresent "react-playwright.log"
    Tail-IfPresent "spa-regressions.log"
    if ($reactExit -ne 0 -or $spaExit -ne 0) {
        throw "browser_battery_failed"
    }
}
catch {
    Write-Output "LIVE_STACK_ARTIFACTS=$ArtifactRoot"
    Write-Output "LIVE_STACK_ERROR=$($_.Exception.Message)"
    foreach ($name in @(
        "seed.log", "backend.err.log", "worker.err.log",
        "storefront.err.log", "admin.err.log",
        "react-playwright.log", "react-playwright.err.log",
        "spa-regressions.log", "spa-regressions.err.log"
    )) {
        Tail-IfPresent $name
    }
    throw
}
finally {
    if (-not $KeepServices) {
        foreach ($process in $processes) {
            if ($process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
        docker stop $redisName | Out-Null
        docker stop $pgName | Out-Null
    }
}
