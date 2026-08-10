param(
    [switch]$Foreground
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$environment = @{
    EXTERNAL_RESEARCH_ENABLED = '1'
    EXTERNAL_RESEARCH_SEARCH_URL = 'http://127.0.0.1:8888/search?q={query}&format=json'
    EXTERNAL_RESEARCH_ALLOW_PRIVATE = '1'
    EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED = '1'
    EXTERNAL_RESEARCH_PROVIDER_ID = 'local_searxng'
    EXTERNAL_RESEARCH_PROVIDER_BILLING_CLASS = 'free'
    EXTERNAL_RESEARCH_TENANT_ALLOWLIST = 'default,portfolio-demo'
    EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY = 'leoma-project-owner'
    EXTERNAL_RESEARCH_SOURCE_LICENCE = 'portfolio-demo-policy-v1'
    OFFICIAL_REQUIREMENTS_PUBLISHER_POLICY_ID = 'leoma-publisher-policy-v1'
    OFFICIAL_REQUIREMENTS_FRESHNESS_SLA_HOURS = '720'
    MULTI_INTENT_PLANNER_ENABLED = '1'
    MULTI_INTENT_LLM_BINDING_ENABLED = '1'
    SHOPSQUIRE_RUNTIME_PROFILE = 'demo_v2'
    RECOMMEND_CORE_MODE = 'primary'
    RECOMMEND_CART_SERVE = '1'
    RECOMMEND_PROCUREMENT_ADVICE_MODE = 'on'
    RECOMMEND_POLICY_ANSWER_MODE = 'on'
    RECOMMEND_SUPPORT_HANDOFF_MODE = 'on'
    RECOMMEND_INVENTORY_READ_MODE = 'on'
    RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED = '1'
    FULFILLMENT_SUPPLIER_TRANSPORT = 'sandbox'
    FULFILLMENT_AUTONOMOUS_RFQ = '0'
    AUTO_SEED_REVIEWED_PRODUCT_EVIDENCE = '1'
    PORTFOLIO_DEMO_INVENTORY_PROFILE = 'realistic'
}

foreach ($entry in $environment.GetEnumerator()) {
    Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value
}

$existing = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    throw "Port 8080 is already listening (PID $($existing.OwningProcess)). Stop it deliberately before restarting."
}

$arguments = @('-m', 'uvicorn', 'src.app.main:app', '--host', '127.0.0.1', '--port', '8080')
if ($Foreground) {
    & python @arguments
    exit $LASTEXITCODE
}

$logDirectory = Join-Path $repoRoot '.tmp-portfolio-backend'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$stdoutPath = Join-Path $logDirectory 'stdout.log'
$stderrPath = Join-Path $logDirectory 'stderr.log'
$process = Start-Process -FilePath python -ArgumentList $arguments `
    -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
Write-Output "Started ShopSquire portfolio backend on http://127.0.0.1:8080 (PID $($process.Id))."
Write-Output "Logs: $stdoutPath and $stderrPath"
