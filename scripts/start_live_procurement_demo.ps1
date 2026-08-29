<#
.SYNOPSIS
  Deterministic bring-up for the ShopSquire live procurement + market-intel demo (Windows).

.DESCRIPTION
  Removes the fragile hand-set env interpolation from the runbook. It:
    1. Patches config/feature_flags.json for the flags that are NOT env-overlaid
       (FULFILLMENT_CASES_ENABLED, FULFILLMENT_BULK_THRESHOLD) - with a .demobak backup.
    2. Sets the process env for the os.getenv flags (COMMERCE_CATALOG_ENABLED,
       FULFILLMENT_DEMO_ENABLED, OWNER_API_KEY, PYTHONPATH, VITE_API_BASE).
    3. Seeds suppliers + canonical price/stock so the draft resolves a supplier and the
       buyer-procurement-truth shortfall both have data.
    4. Health-checks the API and the admin (3001) CORS preflight.
    5. Prints the exact URLs + the operator localStorage owner-key snippet + a restore reminder.
  Optionally (-Launch) starts the API + buyer + admin dev servers in separate windows (they inherit
  the env this script set).

.NOTES
  config/feature_flags.json is intentionally modified for the demo. A .demobak is written; run with
  -Restore (or 'git checkout config/feature_flags.json') afterwards. NEVER commit the demo flags.

.EXAMPLE
  ./scripts/start_live_procurement_demo.ps1 -OwnerKey "dev-owner-key" -BulkThreshold 3
  ./scripts/start_live_procurement_demo.ps1 -Launch
  ./scripts/start_live_procurement_demo.ps1 -Restore
#>
[CmdletBinding()]
param(
  [int]$ApiPort = 8080,
  [int]$BuyerPort = 5173,
  [int]$AdminPort = 3001,
  [int]$BulkThreshold = 5,
  [string]$OwnerKey = "dev-owner-key",
  [switch]$Launch,
  [switch]$Restore
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$FlagsPath = Join-Path $Root "config/feature_flags.json"
$FlagsBak  = "$FlagsPath.demobak"

function Write-Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }

if ($Restore) {
  if (Test-Path $FlagsBak) {
    Copy-Item $FlagsBak $FlagsPath -Force
    Remove-Item $FlagsBak -Force
    Write-Host "Restored config/feature_flags.json from backup." -ForegroundColor Green
  } else {
    Write-Host "No backup found. Use: git checkout config/feature_flags.json" -ForegroundColor Yellow
  }
  return
}

# 1. feature_flags.json (the flags that are NOT env-overlaid) -------------------
Write-Step "Patching feature flags (FULFILLMENT_CASES_ENABLED, FULFILLMENT_BULK_THRESHOLD)"
if (-not (Test-Path $FlagsBak)) { Copy-Item $FlagsPath $FlagsBak -Force }
$flags = Get-Content $FlagsPath -Raw | ConvertFrom-Json
$flags | Add-Member -NotePropertyName "FULFILLMENT_CASES_ENABLED"  -NotePropertyValue $true          -Force
$flags | Add-Member -NotePropertyName "FULFILLMENT_BULK_THRESHOLD" -NotePropertyValue $BulkThreshold -Force
$flags | Add-Member -NotePropertyName "FULFILLMENT_SINGLE_ITEM_OOS" -NotePropertyValue $true         -Force
$flags | ConvertTo-Json -Depth 50 | Set-Content $FlagsPath -Encoding utf8
Write-Host ("  FULFILLMENT_CASES_ENABLED=true  FULFILLMENT_BULK_THRESHOLD={0}  FULFILLMENT_SINGLE_ITEM_OOS=true  (backup: {1})" -f $BulkThreshold, $FlagsBak)

# 2. process env (the os.getenv flags; child processes inherit these) ----------
Write-Step "Setting process env"
$env:PYTHONPATH = $Root
$env:COMMERCE_CATALOG_ENABLED = "1"
$env:FULFILLMENT_DEMO_ENABLED = "1"
$env:FULFILLMENT_CASES_ENABLED = "1"
$env:FULFILLMENT_BULK_THRESHOLD = "$BulkThreshold"
$env:OWNER_API_KEY = $OwnerKey
$env:VITE_API_BASE = "http://localhost:$ApiPort"
$env:EXTERNAL_RESEARCH_ENABLED = "1"
$env:EXTERNAL_RESEARCH_AUTO_AUTHORIZED = "1"
$env:RESEARCH_POLICY_PROFILE = "demo-safe-auto-v1"
$env:EXTERNAL_RESEARCH_TENANT_ALLOWLIST = "default"
$env:STEAM_REQUIREMENTS_LIVE_ENABLED = "1"
$env:ROUTER_MODEL_ENABLED = "1"
$env:ROUTER_MODEL = "qwen3:14b"
$env:OLLAMA_DEFAULT_MODEL = "qwen3:14b"
$env:USE_OLLAMA_INTENT = "1"
$env:SHOPSQUIRE_RUNTIME_PROFILE = "demo_v2"
$env:VLM_WARMUP_ON_START = "0"
$env:CHAT_UPSTREAM_TIMEOUT_SEC = "45"
$env:RECOMMEND_CORE_MODE = "primary"
$env:RECOMMEND_CART_SERVE = "1"
$env:RECOMMEND_PROCUREMENT_ADVICE_MODE = "on"
$env:RECOMMEND_POLICY_ANSWER_MODE = "on"
$env:RECOMMEND_SUPPORT_HANDOFF_MODE = "on"
$env:RECOMMEND_INVENTORY_READ_MODE = "on"
$env:RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED = "1"
$routerManifest = (Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 10).models |
  Where-Object { $_.name -eq $env:ROUTER_MODEL -or $_.model -eq $env:ROUTER_MODEL } |
  Select-Object -First 1
$routerDigest = [string]$routerManifest.digest
if ($routerDigest -notmatch '^[a-fA-F0-9]{64}$') {
  throw "Ollama did not report a verifiable manifest digest for '$($env:ROUTER_MODEL)'."
}
$env:ROUTER_MODEL_DIGEST = $routerDigest
$env:OLLAMA_DEFAULT_MODEL_DIGEST = $routerDigest
$env:REDIS_URL = "redis://127.0.0.1:6381/0"
$env:CELERY_BROKER_URL = "redis://127.0.0.1:6381/1"
$env:EXTERNAL_RESEARCH_SEARCH_URL = "http://127.0.0.1:8888/search?q={query}&format=json"
$env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = "1"
$env:EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED = "1"
$env:EXTERNAL_RESEARCH_PROVIDER_ID = "local_searxng"
$env:EXTERNAL_RESEARCH_PROVIDER_BILLING_CLASS = "free"
$env:VITE_EXTERNAL_RESEARCH_AUTO_ENABLED = "1"
foreach ($n in "COMMERCE_CATALOG_ENABLED","FULFILLMENT_DEMO_ENABLED","FULFILLMENT_CASES_ENABLED","FULFILLMENT_BULK_THRESHOLD","OWNER_API_KEY","VITE_API_BASE","ROUTER_MODEL_ENABLED","ROUTER_MODEL","SHOPSQUIRE_RUNTIME_PROFILE","VLM_WARMUP_ON_START","CHAT_UPSTREAM_TIMEOUT_SEC","RECOMMEND_CORE_MODE","RECOMMEND_CART_SERVE","RECOMMEND_PROCUREMENT_ADVICE_MODE","RECOMMEND_POLICY_ANSWER_MODE","RECOMMEND_SUPPORT_HANDOFF_MODE","RECOMMEND_INVENTORY_READ_MODE","RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED","REDIS_URL","EXTERNAL_RESEARCH_ENABLED","EXTERNAL_RESEARCH_AUTO_AUTHORIZED","RESEARCH_POLICY_PROFILE","EXTERNAL_RESEARCH_TENANT_ALLOWLIST","EXTERNAL_RESEARCH_SEARCH_URL","STEAM_REQUIREMENTS_LIVE_ENABLED","VITE_EXTERNAL_RESEARCH_AUTO_ENABLED") {
  Write-Host ("  {0}={1}" -f $n, (Get-Item "env:$n").Value)
}

# 3. seed suppliers + canonical catalog ----------------------------------------
Write-Step "Seeding suppliers + canonical price/stock"
& python (Join-Path $Root "scripts/seed_suppliers.py")
if ($LASTEXITCODE -ne 0) { Write-Host ("  seed returned {0} (continuing)" -f $LASTEXITCODE) -ForegroundColor Yellow }

# 4. health checks --------------------------------------------------------------
Write-Step "Health checks"
$apiBase = "http://localhost:$ApiPort"
try {
  $h = Invoke-WebRequest -Uri "$apiBase/health" -TimeoutSec 4 -UseBasicParsing
  Write-Host ("  API /health  -> {0}" -f $h.StatusCode) -ForegroundColor Green
  $hdr = @{ "Origin" = "http://localhost:$AdminPort"; "Access-Control-Request-Method" = "GET" }
  try {
    $pre = Invoke-WebRequest -Uri "$apiBase/health" -Method Options -TimeoutSec 4 -UseBasicParsing -Headers $hdr
    $acao = $pre.Headers["Access-Control-Allow-Origin"]
    if ($acao) { Write-Host ("  CORS for :{0} -> {1}" -f $AdminPort, $acao) -ForegroundColor Green }
    else { Write-Host "  CORS preflight returned no Access-Control-Allow-Origin (check main.py allow_origins)" -ForegroundColor Yellow }
  } catch {
    Write-Host ("  CORS preflight failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
  }
} catch {
  Write-Host "  API not reachable yet - start it (-Launch) then re-run, or it's still booting." -ForegroundColor Yellow
}

# 5. instructions ---------------------------------------------------------------
Write-Step "Open these"
Write-Host ("  Buyer    : http://localhost:{0}" -f $BuyerPort)
Write-Host ("  Operator : http://localhost:{0}   (Procurement + Market Intelligence tabs)" -f $AdminPort)
Write-Host ("  API      : {0}" -f $apiBase)
Write-Host ""
Write-Host "  In the operator browser console, authorize owner endpoints:" -ForegroundColor Cyan
Write-Host ("    localStorage.setItem('ss_owner_key', '{0}')" -f $OwnerKey)
Write-Host ""
Write-Host "  Buyer demo query (qty above canonical stock -> opens the procurement panel):" -ForegroundColor Cyan
Write-Host '    "I need 10 gaming laptops for an esports lab, $1800 each within two weeks"'
Write-Host ""
Write-Host "  When done, restore flags:  ./scripts/start_live_procurement_demo.ps1 -Restore" -ForegroundColor Yellow

# 6. optional: launch the three dev servers (they inherit the env set above) ----
if ($Launch) {
  Write-Step "Launching dev servers (separate windows)"
  $apiCmd   = "cd '$Root'; python -m uvicorn src.app.main:app --port $ApiPort"
  $buyerCmd = "cd '$Root/frontend'; npm run dev -- --port $BuyerPort"
  $adminCmd = "cd '$Root/src/frontend/admin-react'; npm run dev -- --port $AdminPort"
  Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", $apiCmd
  Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", $buyerCmd
  Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", $adminCmd
  $apiReady = $false
  for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
      $health = Invoke-WebRequest -Uri "$apiBase/health" -TimeoutSec 2 -UseBasicParsing
      if ($health.StatusCode -eq 200) { $apiReady = $true; break }
    } catch { }
  }
  if ($apiReady) {
    $warmBody = @{
      model = $env:ROUTER_MODEL
      prompt = "Return only READY"
      stream = $false
      think = $false
      keep_alive = "30m"
      options = @{ num_predict = 4; temperature = 0 }
    } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" -Method Post -ContentType "application/json" -Body $warmBody -TimeoutSec 180 | Out-Null
    Write-Host "  API ready; text router prewarmed after startup." -ForegroundColor Green
  } else {
    Write-Host "  API did not become ready within 60 seconds; run the script again for health checks." -ForegroundColor Yellow
  }
  Write-Host "  Launched API + buyer + admin." -ForegroundColor Green
}
