#requires -Version 5.1
<#
ShopSquire PowerShell Demo Bundle
- Starts the API server with UI routes and CV warmup
- Prewarms Ollama (small vs big) and verifies CV readiness
- Seeds a real email incident + ticket
- Opens Admin (Security, Email Incidents) and Storefront pages
- Triggers a recommendation decision and saves Decision Trace proof

Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo_bundle.ps1

Notes:
- Expects virtualenv at .venv and Python 3.10+
- If the server is already running, the script will skip startup
#>

param(
  [string]$Api = "http://127.0.0.1:8080",
  [string]$Python = "$PWD/.venv/Scripts/python.exe",
  [int]$WaitReadySeconds = 20
)

function Wait-Ready($ApiBase, $TimeoutSec) {
  $t0 = Get-Date
  while ((New-TimeSpan -Start $t0 -End (Get-Date)).TotalSeconds -lt $TimeoutSec) {
    try {
      $r = Invoke-RestMethod -Method Get -Uri "$ApiBase/readyz" -TimeoutSec 2
      if ($r.status -eq 'ok') { return $true }
    } catch { }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Start-Server($ApiBase, $PythonPath) {
  $port = [int]([Uri]$ApiBase).Port
  Write-Host "[bundle] starting server on port $port..."
  $env:DATABASE_URL = "sqlite+pysqlite:///$PWD/tmp/e2e.sqlite"
  $env:DISABLE_UI_ROUTES = "0"
  $env:API_PORT = "$port"
  $env:BACKPRESSURE_TEST_DELAY_SEC = "0.2"
  $env:CV_WARMUP_ON_START = "1"
  Start-Process -FilePath $PythonPath -ArgumentList "-m","uvicorn","src.app.main:create_app","--host","127.0.0.1","--port","$port","--factory" -WorkingDirectory $PWD -WindowStyle Hidden | Out-Null
}

function Prewarm-Ollama($ApiBase) {
  Write-Host "[bundle] prewarming Ollama..."
  $headers = @{ 'x-api-key' = 'local-merchant-key' }
  try {
    $simple = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/chat/ollama_test" -Headers $headers -Body (@{ query = 'cheap laptop with good battery' } | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 10
    Write-Host "  simple model=$($simple.model) ms=$($simple.total_duration_ms)"
  } catch { Write-Host "  simple prewarm failed: $($_.Exception.Message)" }
  try {
    $complex = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/chat/ollama_test" -Headers $headers -Body (@{ query = 'compare laptops for video editing with GPU acceleration and color-accurate display' } | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 10
    Write-Host "  complex model=$($complex.model) ms=$($complex.total_duration_ms)"
  } catch { Write-Host "  complex prewarm failed: $($_.Exception.Message)" }
}

function Check-CVReadiness($ApiBase) {
  Write-Host "[bundle] checking CV readiness..."
  $headers = @{ 'x-api-key' = 'local-developer-key' }
  try {
    $cv = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/v1/admin/cv/readiness" -Headers $headers -TimeoutSec 6
    Write-Host "  features: ocr_provider=$($cv.features.ocr_provider) ultralytics=$($cv.features.ultralytics_available)"
  } catch { Write-Host "  cv readiness failed: $($_.Exception.Message)" }
}

function Seed-Incident($ApiBase, $PythonPath) {
  Write-Host "[bundle] seeding email incident..."
  & $PythonPath scripts/demo_mode.py --api $ApiBase | Write-Host
}

function Open-Pages($ApiBase) {
  Write-Host "[bundle] opening admin and storefront pages..."
  Start-Process "$ApiBase/admin"
  Start-Process "$ApiBase/ui/storefront"
  Start-Process "$ApiBase/ui/product/XPS13PLUS"
}

function Trigger-Decision($ApiBase) {
  Write-Host "[bundle] triggering recommendation decision..."
  $headers = @{ 'x-api-key' = 'local-merchant-key' }
  try {
    $resp = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/chat/query" -Headers $headers -Body (@{ query = 'laptops for coding under $1500 with 16GB RAM' } | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 12
    $trace = $resp.decision_trace_id
    Write-Host "  decision_trace_id=$trace products=$(@($resp.products).Count)"
    if (-not (Test-Path -Path "runs")) { New-Item -ItemType Directory -Path "runs" | Out-Null }
    (@{ decision_trace_id = $trace; response = $resp }) | ConvertTo-Json -Depth 6 | Set-Content -Path "runs/demo_decision.json"
    Write-Host "  wrote runs/demo_decision.json"
  } catch {
    Write-Host "  decision trigger failed: $($_.Exception.Message)"
  }
}

# Main
Write-Host "[bundle] API base: $Api"
if (-not (Wait-Ready -ApiBase $Api -TimeoutSec 6)) {
  Start-Server -ApiBase $Api -PythonPath $Python
  if (-not (Wait-Ready -ApiBase $Api -TimeoutSec $WaitReadySeconds)) {
    Write-Host "[bundle] server not ready; aborting"; exit 1
  }
}
Prewarm-Ollama -ApiBase $Api
Check-CVReadiness -ApiBase $Api
Seed-Incident -ApiBase $Api -PythonPath $Python
Trigger-Decision -ApiBase $Api
Open-Pages -ApiBase $Api

Write-Host "[bundle] done. Record your screen with DevTools Network open; match x-request-id headers to runs\request_log.txt and runs\demo_proof.json."
