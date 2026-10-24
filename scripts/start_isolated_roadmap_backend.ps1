param(
    [string]$DatabasePath = '.artifacts/connected-shop-2026-09-28/shop.sqlite3',
    [int]$Port = 8087,
    [switch]$EnableExpiry,
    [switch]$WithModels
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($WithModels) {
    . (Join-Path $PSScriptRoot 'local_demo_runtime.ps1')
    . (Join-Path $PSScriptRoot 'assert_local_ollama.ps1')
    . (Join-Path $PSScriptRoot 'enroll_local_demo_models.ps1')
}
$database = (Resolve-Path -LiteralPath (Join-Path $repoRoot $DatabasePath)).Path.Replace('\','/')
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already occupied; this script will not stop another server."
}
$configuration = @{
    APP_ENV='local'; DATABASE_URL="sqlite:///$database"; DATABASE_URL_RO="sqlite:///$database"
    ENABLE_DEMO_ROUTES='1'; FULFILLMENT_SUPPLIER_TRANSPORT='sandbox'
    EXTERNAL_RESEARCH_ENABLED='0'; ROUTER_PREWARM_ON_START='0'; VLM_WARMUP_ON_START='0'
    CV_WARMUP_ON_START='0'; INVENTORY_WORKER_ENABLED='0'; PAYMENT_RECONCILE_SCHEDULER_ENABLED='0'
    WEBHOOK_DISPATCHER_WORKER_ENABLED='0'; OTEL_SDK_DISABLED='true'; CHAT_REQUEST_TIMEOUT_SEC='30'
    RETENTION_CLEANUP_ENABLED='0'; INCIDENT_SLA_SCHEDULER_ENABLED='0'
    CHAT_UPSTREAM_TIMEOUT_SEC='25'; AUTOMATIC_RESEARCH_TIMEOUT_SEC='20'
    INVENTORY_EXPIRY_SCHEDULER_ENABLED=$(if ($EnableExpiry) { '1' } else { '0' })
}
foreach ($entry in $configuration.GetEnumerator()) { Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value }
if ($WithModels) {
    $env:ROUTER_MODEL_ENABLED='1'
    $configuration['ROUTER_MODEL_ENABLED']='1'
    foreach ($name in @('OLLAMA_URL','ROUTER_MODEL','ROUTER_MODEL_DIGEST','OLLAMA_VISION_MODEL',
        'CV_IDENTITY_MODEL_DIGEST','OLLAMA_CONTEXT_LENGTH','LOCAL_MODEL_MAX_CONCURRENCY','MODEL_ARTIFACT_ENROLLMENT_MODE')) {
        $configuration[$name]=[Environment]::GetEnvironmentVariable($name,'Process')
    }
}
$logDir = Join-Path $repoRoot '.artifacts/roadmap-runtime'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$configuration | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $logDir "$stamp-config.json")
$process = Start-Process -FilePath (Join-Path $repoRoot '.venv/Scripts/python.exe') `
    -ArgumentList '-m','uvicorn','src.app.main:app','--host','127.0.0.1','--port',$Port `
    -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "$stamp-out.log") `
    -RedirectStandardError (Join-Path $logDir "$stamp-err.log")
Write-Output "Started isolated roadmap backend, launcher PID $($process.Id), port $Port."
Write-Output "Runtime configuration and logs: $logDir"
