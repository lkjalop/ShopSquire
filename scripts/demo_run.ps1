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

& .\.venv\Scripts\python.exe scripts\seed_demo_data.py | Write-Host

Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList @("-m","uvicorn","src.app.main:app","--host","0.0.0.0","--port","8080") -WorkingDirectory $root | Out-Null

Start-Sleep -Seconds 2

Start-Process "http://localhost:8080/ui/storefront" | Out-Null
Start-Process "http://localhost:8080/ui/product/DEMO-001" | Out-Null
Start-Process "http://localhost:8080/ui/checkout" | Out-Null
Start-Process "http://localhost:8080/ui/status" | Out-Null
