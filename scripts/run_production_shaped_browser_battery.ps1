param(
    [string]$ArtifactRoot = "",
    [switch]$KeepServices,
    [string[]]$PlaywrightSpec = @()
)

$ErrorActionPreference = "Stop"
$pgName = "shopsquire-live-pg"
$redisName = "shopsquire-live-redis"
$workerNode = (
    "shopsquire-live-" + [guid]::NewGuid().ToString("N") +
    "@" + $env:COMPUTERNAME
)
if (-not $ArtifactRoot) {
    $ArtifactRoot = Join-Path $env:TEMP (
        "shopsquire-live-" + [guid]::NewGuid().ToString("N")
    )
}
$resolvedRepo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoots = @(
    (Join-Path $resolvedRepo "frontend"),
    (Join-Path $resolvedRepo "src/frontend/admin-react")
)
foreach ($frontendRoot in $frontendRoots) {
    $viteLauncher = Join-Path $frontendRoot "node_modules/.bin/vite.cmd"
    if (-not (Test-Path -LiteralPath $viteLauncher)) {
        throw (
            "frontend_dependencies_missing:$frontendRoot; " +
            "run npm ci --prefix `"$frontendRoot`""
        )
    }
}
if (-not [System.IO.Path]::IsPathRooted($ArtifactRoot)) {
    $ArtifactRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $resolvedRepo $ArtifactRoot)
    )
}
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
$env:CONVERSATIONAL_SPATIOTEMPORAL_CERTIFICATE_PATH = Join-Path `
    $ArtifactRoot "conversational-spatiotemporal-browser-certificate.json"
$env:CONVERSATIONAL_SPATIOTEMPORAL_SCREENSHOT_PATH = Join-Path `
    $ArtifactRoot "conversational-spatiotemporal-showcase.png"
$processes = @()
$receiverProcess = $null
$officialProviderProcess = $null

function Get-FreeTcpPort {
    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

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

function Stop-ProcessTree([int]$ProcessId) {
    $children = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ParentProcessId -eq $ProcessId }
    )
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Wait-BoundedProcess(
    [System.Diagnostics.Process]$Process,
    [int]$TimeoutSec,
    [string]$Label,
    [string]$ExitFile = ""
) {
    if (-not $Process.WaitForExit($TimeoutSec * 1000)) {
        Stop-ProcessTree -ProcessId $Process.Id
        throw "$Label timed out after $TimeoutSec seconds"
    }
    if ($ExitFile) {
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (Test-Path -LiteralPath $ExitFile) {
                $rawExitCode = (Get-Content -LiteralPath $ExitFile -Raw).Trim()
                if ($rawExitCode -match "^-?\d+$") {
                    return [int]$rawExitCode
                }
            }
            Start-Sleep -Milliseconds 100
        }
        throw "$Label completed without a persisted exit code"
    }
    # Windows PowerShell can expose a null ExitCode for redirected children.
    # Callers needing a reliable result must use the ExitFile contract above.
    $Process.Refresh()
    return [int]$Process.ExitCode
}

docker run --name $pgName --rm -d --tmpfs /var/lib/postgresql/data `
    -e POSTGRES_PASSWORD=shopsquire_test -e POSTGRES_DB=shopsquire `
    -p 127.0.0.1::5432 pgvector/pgvector:pg16 | Out-Null
Assert-NativeSuccess "live_postgres_start"
docker run --name $redisName --rm -d -p 127.0.0.1::6379 redis:7-alpine | Out-Null
Assert-NativeSuccess "live_redis_start"
$pgPort = ((docker port $pgName 5432/tcp) -split ":")[-1]
Assert-NativeSuccess "live_postgres_port"
$redisPort = ((docker port $redisName 6379/tcp) -split ":")[-1]
Assert-NativeSuccess "live_redis_port"

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
        "127.0.0.1:$pgPort/shopsquire"
    )
    $env:DATABASE_URL_RO = $env:DATABASE_URL
    $env:REDIS_URL = "redis://127.0.0.1:$redisPort/0"
    $env:CELERY_BROKER_URL = "redis://127.0.0.1:$redisPort/1"
    $env:CELERY_RESULT_BACKEND = "redis://127.0.0.1:$redisPort/2"
    $env:CELERY_HMAC_KEY = "local-browser-worker-signing-key"
    $env:SHOPSQUIRE_RUNTIME_PROFILE = "demo_v2"
    $env:RECOMMEND_CORE_MODE = "primary"
    $env:RECOMMEND_LEGACY_DELEGATE_ENABLED = "0"
    $env:RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED = "1"
    $env:RECOMMEND_CART_SERVE = "1"
    $env:RECOMMEND_PROCUREMENT_ADVICE_MODE = "on"
    $env:RECOMMEND_POLICY_ANSWER_MODE = "on"
    $env:RECOMMEND_SUPPORT_HANDOFF_MODE = "on"
    $env:RECOMMEND_INVENTORY_READ_MODE = "on"
    $env:MULTI_INTENT_PLANNER_ENABLED = "1"
    # The portable browser catalog carries 14-18 units per laptop. Treat 10+
    # as the scenario's declared surplus so the market-adaptation case has a
    # genuine actionable cohort instead of silently exercising a neutral one.
    $env:SALES_RESPONSE_OVERSTOCK_UNITS = "10"
    # The market-adaptation browser story is an explicit shadow/demo contract.
    # Keep the bounded nudge on here; production remains default-off unless a
    # tenant experiment enables it.
    $env:SALES_RESPONSE_NUDGE_ENABLED = "1"
    $env:FULFILLMENT_DEMO_ENABLED = "1"
    # The recorded procurement contract proves the bounded GATE-1 behaviour:
    # buyer commitment may draft an RFQ, but it may not send it. Keep this
    # independent flag explicit so a clean checkout cannot silently stop at
    # COMMITTED and make the browser proof depend on a developer's local flags.
    $env:FULFILLMENT_AUTO_DRAFT_ON_COMMIT = "1"
    $env:GATE_PROCUREMENT = "1"
    # The canonical portfolio certificate is an explicitly gated, read-only
    # surface. Enable it only inside this disposable production-shaped stack.
    $env:PORTFOLIO_CERTIFICATION_ENABLED = "1"
    # Enrol a disposable, explicit research proof stack. These settings mirror
    # hosted CI and grant authority only to the synthetic/local certificate
    # tenant; application defaults remain disabled and fail closed.
    $env:EXTERNAL_RESEARCH_ENABLED = "1"
    $officialPort = Get-FreeTcpPort
    $env:EXTERNAL_RESEARCH_SEARCH_URL = (
        "http://127.0.0.1:$officialPort/search?q={query}&format=json"
    )
    $env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = "1"
    $env:EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED = "1"
    $env:EXTERNAL_RESEARCH_PROVIDER_ID = "local_synthetic_discovery_fixture"
    $env:EXTERNAL_RESEARCH_PROVIDER_BILLING_CLASS = "free"
    $env:EXTERNAL_RESEARCH_TENANT_ALLOWLIST = "default"
    $env:EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY = "local-certificate-source-reviewer"
    $env:EXTERNAL_RESEARCH_SOURCE_LICENCE = "test-fixture"
    $env:OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST = "docs.vendor.example"
    $env:PRODUCT_CAPABILITY_TENANT_ALLOWLIST = "default"
    $env:OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED = "1"
    $env:SEMANTIC_RESEARCH_FIXTURES_ENABLED = "1"
    $env:SEMANTIC_RESEARCH_FIXTURE_ID = "siemens_digital_twin_qualified_contract"
    $env:SEMANTIC_SIMULATION_AUTHORITY_ENABLED = "1"
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
    # Keep quota enforcement enabled while preventing one browser case from
    # consuming the shared test tenant's allowance and invalidating later,
    # otherwise-independent multi-turn cases.
    $env:TOKEN_BUDGET_ENABLED = "1"
    $env:TOKEN_BUDGET_GUEST_DAILY_TOKENS = "1000000000"
    $env:TOKEN_BUDGET_GUEST_DAILY_USD = "1000000"
    $backendPort = Get-FreeTcpPort
    $storefrontPort = Get-FreeTcpPort
    $adminPort = Get-FreeTcpPort
    $siemPort = Get-FreeTcpPort
    $backendUrl = "http://127.0.0.1:$backendPort"
    $storefrontUrl = "http://127.0.0.1:$storefrontPort"
    $adminUrl = "http://127.0.0.1:$adminPort"
    $env:VITE_API_BASE_URL = $backendUrl
    $env:PLAYWRIGHT_BASE_URL = $storefrontUrl
    $env:BACKEND_SMOKE_URL = $backendUrl
    $env:SIEM_WEBHOOK_URL = "http://127.0.0.1:$siemPort/events"
    $env:OFFICIAL_REQUIREMENTS_API_URL = (
        "http://127.0.0.1:$officialPort/requirements?q={query}"
    )
    $env:SECURITY_HANDOFF_INLINE = "1"

    $officialProviderProcess = Start-Process -FilePath python -ArgumentList @(
        (Join-Path $resolvedRepo "tests/fixtures/fake_official_requirements_provider.py"),
        "--port", "$officialPort"
    ) -WorkingDirectory $resolvedRepo -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "official-provider.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "official-provider.err.log")
    $receiverProcess = Start-Process -FilePath python -ArgumentList @(
        (Join-Path $resolvedRepo "scripts/security_handoff_test_receiver.py"),
        "--port", "$siemPort", "--output", (Join-Path $ArtifactRoot "siem-events.jsonl")
    ) -WorkingDirectory $resolvedRepo -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "siem-receiver.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "siem-receiver.err.log")
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $siemHealth = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$siemPort/health" -TimeoutSec 2
            if ($siemHealth.StatusCode -eq 200) { break }
        }
        catch { Start-Sleep -Milliseconds 200 }
    }

    python -m alembic upgrade head *>&1 |
        Tee-Object -FilePath (Join-Path $ArtifactRoot "migration.log") | Out-Null
    Assert-NativeSuccess "live_migration"
    python -m alembic current *>&1 |
        Tee-Object -FilePath (Join-Path $ArtifactRoot "migration-current.log") | Out-Null
    Assert-NativeSuccess "live_migration_current"
    $migrationCurrent = Get-Content `
        -LiteralPath (Join-Path $ArtifactRoot "migration-current.log") -Raw
    if ($migrationCurrent -notmatch "20260874") {
        throw "live_migration_revision_mismatch:expected=20260874"
    }
    python scripts/seed_demo_data.py *>&1 |
        Tee-Object -FilePath (Join-Path $ArtifactRoot "seed.log") | Out-Null
    Assert-NativeSuccess "live_seed"
    python -m scripts.seed_portable_catalog *>&1 |
        Tee-Object -FilePath (
            Join-Path $ArtifactRoot "portable-catalog-seed.log"
        ) | Out-Null
    Assert-NativeSuccess "portable_catalog_seed"
    python -m scripts.seed_suppliers *>&1 |
        Tee-Object -FilePath (
            Join-Path $ArtifactRoot "supplier-seed.log"
        ) | Out-Null
    Assert-NativeSuccess "supplier_seed"
    python -m scripts.seed_eight_buyer_allocation_demo *>&1 |
        Tee-Object -FilePath (
            Join-Path $ArtifactRoot "eight-buyer-allocation-seed.log"
        ) | Out-Null
    Assert-NativeSuccess "eight_buyer_allocation_seed"

    $processes += Start-Process -FilePath python -ArgumentList @(
        "-m", "uvicorn", "src.app.main:create_app", "--factory",
        "--host", "127.0.0.1", "--port", "$backendPort"
    ) -WorkingDirectory $resolvedRepo -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "backend.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "backend.err.log")
    $processes += Start-Process -FilePath python -ArgumentList @(
        "-m", "celery", "-A", "src.app.workers.celery_app:celery_app",
        "worker", "--loglevel=INFO", "--pool=solo",
        "--hostname=$workerNode"
    ) -WorkingDirectory $resolvedRepo -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "worker.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "worker.err.log")
    $processes += Start-Process -FilePath npm.cmd -ArgumentList @(
        "run", "dev", "--", "--host", "127.0.0.1", "--port", "$storefrontPort"
    ) -WorkingDirectory (Join-Path $resolvedRepo "frontend") `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "storefront.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "storefront.err.log")
    $processes += Start-Process -FilePath npm.cmd -ArgumentList @(
        "run", "dev", "--", "--host", "127.0.0.1", "--port", "$adminPort"
    ) -WorkingDirectory (Join-Path $resolvedRepo "src/frontend/admin-react") `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ArtifactRoot "admin.out.log") `
        -RedirectStandardError (Join-Path $ArtifactRoot "admin.err.log")

    $stackReady = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $health = Invoke-WebRequest -UseBasicParsing `
                -Uri "$backendUrl/healthz" -TimeoutSec 5
            $store = Invoke-WebRequest -UseBasicParsing `
                -Uri $storefrontUrl -TimeoutSec 2
            $admin = Invoke-WebRequest -UseBasicParsing `
                -Uri $adminUrl -TimeoutSec 2
            $official = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$officialPort/requirements?q=health" -TimeoutSec 2
            $search = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$officialPort/search?q=health&format=json" -TimeoutSec 5
            if (
                $health.StatusCode -eq 200 -and
                $store.StatusCode -eq 200 -and
                $admin.StatusCode -eq 200 -and
                $official.StatusCode -eq 200 -and
                $search.StatusCode -eq 200
            ) {
                $stackReady = $true
                break
            }
        }
        catch {
            # The bounded readiness loop reports process logs on failure.
        }
        $serviceNames = @("backend", "worker", "storefront", "admin")
        for ($processIndex = 0; $processIndex -lt $processes.Count; $processIndex++) {
            if ($processes[$processIndex].HasExited) {
                throw (
                    $serviceNames[$processIndex] +
                    "_exited_before_ready:exit_code=" +
                    $processes[$processIndex].ExitCode
                )
            }
        }
        Start-Sleep -Seconds 1
    }
    if (-not $stackReady) {
        throw "live_stack_not_ready"
    }

    python -m celery -A src.app.workers.celery_app:celery_app `
        inspect ping --destination $workerNode --timeout 10 *>&1 |
        Tee-Object -FilePath (Join-Path $ArtifactRoot "worker-ping.log") |
        Out-Null
    Assert-NativeSuccess "live_worker_ping"

    Push-Location (Join-Path $resolvedRepo "frontend")
    try {
        $reactExitFile = Join-Path $ArtifactRoot "react-playwright.exit"
        $env:SHOPSQUIRE_CHILD_EXIT_FILE = $reactExitFile
        $reactArguments = @(
            (Join-Path $resolvedRepo "scripts/run_child_process.py"),
            "python", (Join-Path $resolvedRepo "scripts/run_playwright_memory_safe.py"),
            "--frontend", (Join-Path $resolvedRepo "frontend")
        )
        foreach ($spec in $PlaywrightSpec) {
            $reactArguments += @("--spec", $spec)
        }
        $reactProcess = Start-Process -FilePath python -ArgumentList $reactArguments `
            -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (
                Join-Path $ArtifactRoot "react-playwright.log"
            ) -RedirectStandardError (
                Join-Path $ArtifactRoot "react-playwright.err.log"
        )
        $reactTimeoutSec = if ($PlaywrightSpec) {
            600 * [Math]::Max(1, $PlaywrightSpec.Count)
        } else { 2400 }
        $reactExit = Wait-BoundedProcess `
            -Process $reactProcess -TimeoutSec $reactTimeoutSec -Label "react_playwright" `
            -ExitFile $reactExitFile
    }
    finally {
        Remove-Item Env:SHOPSQUIRE_CHILD_EXIT_FILE -ErrorAction SilentlyContinue
        Pop-Location
    }

    $spaExit = 0
    if (-not $PlaywrightSpec) {
        $env:RUN_LIVE_BROWSER_TESTS = "1"
        $env:LIVE_SHOPPER_URL = $storefrontUrl
        $env:LIVE_ADMIN_URL = $adminUrl
        $spaExitFile = Join-Path $ArtifactRoot "spa-regressions.exit"
        $env:SHOPSQUIRE_CHILD_EXIT_FILE = $spaExitFile
        $spaProcess = Start-Process -FilePath python -ArgumentList @(
            (Join-Path $resolvedRepo "scripts/run_child_process.py"),
            "python", "-m", "pytest", "-vv", "-s",
            "tests/e2e/test_procurement_malicious_reply_playwright.py",
            "tests/e2e/test_live_allocation_workbench.py",
            "tests/e2e/test_live_policy_trace.py",
            "tests/e2e/test_live_procurement_closed_loop.py"
        ) -WorkingDirectory $resolvedRepo -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (
                Join-Path $ArtifactRoot "spa-regressions.log"
            ) -RedirectStandardError (
                Join-Path $ArtifactRoot "spa-regressions.err.log"
        )
        $spaExit = Wait-BoundedProcess `
            -Process $spaProcess -TimeoutSec 600 -Label "spa_regressions" `
            -ExitFile $spaExitFile
        Remove-Item Env:SHOPSQUIRE_CHILD_EXIT_FILE -ErrorAction SilentlyContinue
    }

    # A 200 response is not sufficient when a caught SQL error poisoned the
    # request transaction and forced silent compatibility fallbacks. Treat the
    # PostgreSQL aborted-transaction signature and unhandled tracebacks as hard
    # browser-proof failures, and retain the exact lines in the artifact bundle.
    $abortGatePath = Join-Path $ArtifactRoot "transaction-abort-gate.log"
    $abortPatterns = @(
        "\bERROR:",
        "current transaction is aborted",
        "InFailedSqlTransaction",
        "\[unhandled_exception\]",
        "Exception in ASGI application"
    )
    $abortHits = @()
    try {
        # Docker writes container logs to stderr even on success. Temporarily
        # relax native-command error promotion so PowerShell does not turn a
        # successful capture into a catch-only placeholder.
        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $postgresGateLog = @(docker logs $pgName 2>&1)
        $ErrorActionPreference = $previousErrorAction
        $postgresGateLog |
            Out-File -LiteralPath (Join-Path $ArtifactRoot "postgres.log") -Encoding utf8
    }
    catch {
        "postgres_log_capture_failed: $($_.Exception.Message)" |
            Set-Content -Path (Join-Path $ArtifactRoot "postgres.log") -Encoding UTF8
    }
    foreach ($serviceLog in @("backend.err.log", "worker.err.log", "postgres.log")) {
        $serviceLogPath = Join-Path $ArtifactRoot $serviceLog
        if (Test-Path $serviceLogPath) {
            $abortHits += Select-String -Path $serviceLogPath -Pattern $abortPatterns
        }
    }
    $abortHits | ForEach-Object { "{0}:{1}:{2}" -f $_.Path, $_.LineNumber, $_.Line } |
        Set-Content -Path $abortGatePath -Encoding UTF8
    $transactionAbortExit = if ($abortHits.Count -gt 0) { 1 } else { 0 }
    $siemEventsPath = Join-Path $ArtifactRoot "siem-events.jsonl"
    # A targeted functional spec is not expected to emit a security handoff.
    # The complete battery retains the canonical SIEM delivery gate below.
    $siemTelemetryExit = if ($PlaywrightSpec) { 0 } else { 1 }
    if (-not $PlaywrightSpec -and (Test-Path -LiteralPath $siemEventsPath)) {
        $siemRows = @(Get-Content -LiteralPath $siemEventsPath | Where-Object { $_.Trim() })
        if ($siemRows.Count -gt 0) {
            $canonicalRows = @($siemRows | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object {
                $_.schema_version -eq "shopsquire.security.v1" -and $_.tenant_id -and ($_.trace_id -or $_.decision_id)
            })
            if ($canonicalRows.Count -gt 0) { $siemTelemetryExit = 0 }
        }
    }

    Write-Output "LIVE_STACK_ARTIFACTS=$ArtifactRoot"
    Write-Output "REACT_PLAYWRIGHT_EXIT=$reactExit"
    Write-Output "SPA_REGRESSIONS_EXIT=$spaExit"
    Write-Output "TRANSACTION_ABORT_GATE_EXIT=$transactionAbortExit"
    Write-Output "SIEM_TELEMETRY_GATE_EXIT=$siemTelemetryExit"
    Tail-IfPresent "react-playwright.log"
    Tail-IfPresent "spa-regressions.log"
    if ($reactExit -ne 0 -or $spaExit -ne 0 -or $transactionAbortExit -ne 0 -or $siemTelemetryExit -ne 0) {
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
    if ($officialProviderProcess -and -not $officialProviderProcess.HasExited) {
        Stop-ProcessTree -ProcessId $officialProviderProcess.Id
    }
    if ($receiverProcess -and -not $receiverProcess.HasExited) {
        Stop-ProcessTree -ProcessId $receiverProcess.Id
    }
    if (-not $KeepServices) {
        foreach ($process in $processes) {
            if ($process -and -not $process.HasExited) {
                Stop-ProcessTree -ProcessId $process.Id
            }
        }
    }
    try {
        $priorErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $postgresLog = docker logs $pgName 2>&1
        $postgresLog |
            Out-File -LiteralPath (Join-Path $ArtifactRoot "postgres.log") -Encoding utf8
        $ErrorActionPreference = $priorErrorPreference
    }
    catch {
        $ErrorActionPreference = $priorErrorPreference
        Write-Warning "postgres_log_capture_failed: $($_.Exception.Message)"
    }
    try {
        $priorErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $redisLog = docker logs $redisName 2>&1
        $redisLog |
            Out-File -LiteralPath (Join-Path $ArtifactRoot "redis.log") -Encoding utf8
        $ErrorActionPreference = $priorErrorPreference
    }
    catch {
        $ErrorActionPreference = $priorErrorPreference
        Write-Warning "redis_log_capture_failed: $($_.Exception.Message)"
    }
    if (-not $KeepServices) {
        docker stop $redisName | Out-Null
        docker stop $pgName | Out-Null
    }
}
