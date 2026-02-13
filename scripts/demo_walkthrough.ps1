$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\\.venv\\Scripts\\python.exe")) {
  Write-Error "Virtualenv not found at .\\.venv\\Scripts\\python.exe"
}

$env:PYTHONPATH = $root
$env:LOG_FILE = "logs/shopsquire/api.log"
New-Item -ItemType Directory -Force -Path "logs/shopsquire" | Out-Null

$pgUp = $false
try {
  $pgUp = Test-NetConnection -ComputerName "localhost" -Port 5432 -InformationLevel Quiet
} catch {
  $pgUp = $false
}
if (-not $pgUp) {
  Write-Host "Postgres not reachable; using SQLite demo DB."
  $env:DATABASE_URL = "sqlite:///./tmp/demo.sqlite"
  New-Item -ItemType Directory -Force -Path "tmp" | Out-Null
  & .\.venv\Scripts\python.exe scripts\create_minimal_schema.py | Write-Host
}

Write-Host "Seeding demo data..."
& .\.venv\Scripts\python.exe scripts\seed_demo_data.py | Write-Host

Write-Host "Starting API..."
Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList @("-m","uvicorn","src.app.main:app","--host","0.0.0.0","--port","8080") -WorkingDirectory $root | Out-Null
Start-Sleep -Seconds 2

$base = "http://localhost:8080"
$apiKey = $env:MERCHANT_API_KEY
if (-not $apiKey) { $apiKey = "local-merchant-key" }
$headers = @{ "x-api-key" = $apiKey }

Write-Host "Generating demo events..."
Invoke-RestMethod -Method Get -Uri "$base/api/v1/recommend/suggest?uid=demo-user&query=best%2014%20inch%20laptop%20under%201800%20for%20video%20editing" -Headers $headers | Out-Null
Invoke-RestMethod -Method Get -Uri "$base/api/v1/pricing/suggest?uid=demo-user&cart_total_cents=180000&sku=DEMO-001" -Headers $headers | Out-Null
Invoke-RestMethod -Method Post -Uri "$base/api/v1/incident/alert?topic=security&message=demo%20security%20event&severity=warning" -Headers $headers | Out-Null

try {
  Invoke-RestMethod -Method Post -Uri "$base/api/v1/admin/alertmanager/test" -Headers $headers | Out-Null
} catch {
  Write-Host "AlertManager test failed (stack might not be running)."
}

Start-Process "$base/ui/storefront" | Out-Null
Start-Process "$base/ui/product/DEMO-001" | Out-Null
Start-Process "$base/ui/checkout" | Out-Null
Start-Process "$base/ui/status" | Out-Null
Start-Process "$base/ui/tools" | Out-Null
Start-Process "$base/ui/account" | Out-Null
