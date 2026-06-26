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
$flags | ConvertTo-Json -Depth 50 | Set-Content $FlagsPath -Encoding utf8
Write-Host ("  FULFILLMENT_CASES_ENABLED=true  FULFILLMENT_BULK_THRESHOLD={0}  (backup: {1})" -f $BulkThreshold, $FlagsBak)

# 2. process env (the os.getenv flags; child processes inherit these) ----------
Write-Step "Setting process env"
$env:PYTHONPATH = $Root
$env:COMMERCE_CATALOG_ENABLED = "1"
$env:FULFILLMENT_DEMO_ENABLED = "1"
$env:FULFILLMENT_CASES_ENABLED = "1"
$env:FULFILLMENT_BULK_THRESHOLD = "$BulkThreshold"
$env:OWNER_API_KEY = $OwnerKey
$env:VITE_API_BASE = "http://localhost:$ApiPort"
foreach ($n in "COMMERCE_CATALOG_ENABLED","FULFILLMENT_DEMO_ENABLED","FULFILLMENT_CASES_ENABLED","FULFILLMENT_BULK_THRESHOLD","OWNER_API_KEY","VITE_API_BASE") {
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
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $apiCmd
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $buyerCmd
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $adminCmd
  Write-Host "  Launched API + buyer + admin. Give them ~10s, then re-run without -Launch for health checks." -ForegroundColor Green
}
