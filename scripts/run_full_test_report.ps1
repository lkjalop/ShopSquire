<#
Runs a comprehensive local test run and collects logs into `runs/test_reports`.

Usage:
  powershell -ExecutionPolicy Bypass -File scripts/run_full_test_report.ps1 [-RunPlaywright]

Notes:
 - Expects a Python venv at `.venv` and Node in PATH for Playwright.
 - Sets some stricter env vars to surface silent failures.
#>

# PowerShell param block
param(
  [switch]$RunPlaywright
)

# Use repo root (parent of scripts/) as working directory
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

# reports dir at repo root
$reportsDir = Join-Path $repoRoot "runs\test_reports"
if (-Not (Test-Path $reportsDir)) { New-Item -ItemType Directory -Path $reportsDir | Out-Null }

function Run-Log {
  param(
    [string]$Name,
    [string[]]$Cmd
  )
  $outFile = Join-Path $reportsDir "$Name.txt"
  Write-Host "--- Running: $Name -> $outFile"
  $env:PYTHONUNBUFFERED = '1'
  $env:TEST_TOLERANT_GET_ERRORS = '0'
  $env:PYTHONWARNINGS = 'error'
  try {
    # Invoke command: first element is executable, rest are args
    $exe = $Cmd[0]
    $args = @()
    if ($Cmd.Count -gt 1) { $args = $Cmd[1..($Cmd.Count-1)] }
    & $exe @args 2>&1 | Tee-Object -FilePath $outFile
    $rc = $LASTEXITCODE
  } catch {
    $_ | Out-String | Tee-Object -FilePath $outFile
    $rc = 1
  }
  if ($rc -ne 0) { Write-Host "[FAIL] $Name (exit $rc)" -ForegroundColor Red } else { Write-Host "[OK] $Name" -ForegroundColor Green }
  return $rc
}

# Ensure venv is active if possible
if (Test-Path ".venv/Scripts/Activate.ps1") {
  try { . .venv/Scripts/Activate.ps1 } catch { Write-Host "Could not source venv Activate.ps1: $_" }
}

# 1) Import check
Run-Log "01_imports_check" @('.venv\Scripts\python.exe', 'scripts/check_imports.py')

# 2) Alembic migrations (best-effort)
if (Test-Path "alembic.ini") {
  Run-Log "02_alembic_upgrade_head" @('.venv\Scripts\python.exe', '-m', 'alembic', 'upgrade', 'head') | Out-Null
}

# 3) Focused API tests (fast subset)
$apiJunit = Join-Path $reportsDir 'junit_api.xml'
Run-Log "03_pytest_api" @('.venv\Scripts\python.exe', '-m', 'pytest', 'tests/api', '-q', '--junitxml='+$apiJunit)

# 4) Focused security + decisions tests
$secJunit = Join-Path $reportsDir 'junit_security.xml'
Run-Log "04_pytest_security_decisions" @('.venv\Scripts\python.exe', '-m', 'pytest', 'tests/security', 'tests/decisions', '-q', '--junitxml='+$secJunit)

# 5) Full pytest run (comprehensive)
$fullJunit = Join-Path $reportsDir 'junit_full.xml'
Run-Log "05_pytest_full" @('.venv\Scripts\python.exe', '-m', 'pytest', '-q', '--junitxml='+$fullJunit)

# 6) Optional: run Playwright tests
if ($RunPlaywright) {
  Write-Host "Running Playwright UI tests (this requires Node + Playwright browsers)"
  # Install frontend deps if needed
  if (Test-Path "src/frontend/admin-react/package.json") {
    npm --prefix src/frontend/admin-react ci
    npx --yes playwright install --with-deps
    Run-Log "06_playwright_ui" @('npx', 'playwright', 'test', '--project=chromium', '--reporter=list')
  } else {
    Write-Host "No frontend package.json found; skipping Playwright" -ForegroundColor Yellow
  }
}

# 7) Optional coverage summary (if coverage installed)
if (Get-Command python -ErrorAction SilentlyContinue) {
  try {
    & .venv\Scripts\python.exe -m coverage combine 2>&1 | Out-Null
    & .venv\Scripts\python.exe -m coverage html -d (Join-Path $reportsDir 'coverage_html') 2>&1 | Out-Null
    Write-Host "Coverage HTML written to runs/test_reports/coverage_html" -ForegroundColor Green
  } catch {
    # ignore if coverage not present
  }
}

# 8) Summary
$summary = Join-Path $reportsDir 'summary.txt'
"Test run completed at $(Get-Date -Format o)" | Out-File $summary
Get-ChildItem $reportsDir -File | ForEach-Object { "{0} {1}" -f $_.Name, ((Get-Content $_.FullName -TotalCount 5) -join " `n ") | Out-File $summary -Append }

Write-Host "All logs collected in $reportsDir"
