<#
PowerShell helper to prepare demo environment, seed demo data and start uvicorn (detached).

Usage: run from repo root with an activated venv in PowerShell:
  & .venv\Scripts\Activate.ps1
  .\scripts\demo_setup_and_run.ps1
#>
Push-Location "$PSScriptRoot/.."
try {
    if (-not (Test-Path tmp)) { New-Item -ItemType Directory -Path tmp | Out-Null }
    $dbPath = Join-Path (Get-Location) "tmp\demo.sqlite"
    $absDb = "sqlite+pysqlite:///$(($dbPath -replace '\\','/'))"

    Write-Host "Using demo DB: $dbPath"
    $env:DATABASE_URL = $absDb
    $env:FEATURE_FLAGS_PATH = "config/feature_flags.json"
    # Enable Jaeger for local trace viewing (requires Jaeger running on host)
    $env:JAEGER_ENABLED = "1"
    $env:JAEGER_HOST = "localhost"
    $env:JAEGER_PORT = "6831"
    # UI routes enabled by default for demo
    $env:DISABLE_UI_ROUTES = "0"

    # Resolve Python executable (prefer .venv_new, then .venv, then system python)
    $pythonExe = $null
    $candidates = @(
        ".venv_new\\Scripts\\python.exe",
        ".venv\\Scripts\\python.exe",
        "python"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) { $pythonExe = $cand; break }
    }
    if (-not $pythonExe) {
        Write-Error "No Python interpreter found. Create a venv or install Python."
        return
    }

    $seedOnStartup = $env:SEED_ON_STARTUP
    if ($seedOnStartup -eq $null) { $seedOnStartup = "1" }
    if ($seedOnStartup.ToString().ToLower() -in @("1","true","yes","y")) {
        Write-Host "Seeding demo data..."
        & $pythonExe "scripts/seed_demo_data.py"
    } else {
        Write-Host "Skipping demo seeding (SEED_ON_STARTUP=$seedOnStartup)"
    }

    Write-Host "Starting uvicorn (detached) on port 8080..."
    Start-Process -FilePath $pythonExe -ArgumentList "-m uvicorn src.app.main:create_app --host 127.0.0.1 --port 8080 --factory" -WorkingDirectory (Get-Location) -WindowStyle Hidden
    Write-Host "Server started (background). Wait a few seconds for startup then run scripts/demo_flows.ps1"
} finally {
    Pop-Location
}
