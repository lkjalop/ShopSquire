<#
.SYNOPSIS
  Memory-safe full test suite runner.
  - Runs each test shard in a fresh subprocess (already the case with pytest)
  - Pauses between heavy shards to let Python GC and OS reclaim memory
  - Skips shards that require live infrastructure (Playwright, browser, e2e)
    unless explicitly opted-in via $env:RUN_E2E=1
  - Logs results to scripts/runs/ (not .testlogs/ - which is gitignored as local)

.NOTES
  32 GB RAM machine: VSCode (~7 GB) + WSL2 (6 GB cap via .wslconfig) already
  consumes ~13 GB. Each pytest shard with full FastAPI app = ~1.5-2 GB.
  Run shards sequentially, not in parallel.
#>

$ErrorActionPreference = 'Continue'
$runE2E   = $env:RUN_E2E   -eq '1'
$runBrowser = $env:RUN_BROWSER -eq '1'

# Ordered from fastest/cheapest to most expensive
$coreShards = @(
  'tests/services',
  'tests/api',
  'tests/security',
  'tests/cv',
  'tests/email',
  'tests/chaos',
  'tests/integration',
  'tests/chat',
  'tests/ci',
  'tests/evals',
  'tests/load',
  'tests/ml',
  'tests/nlp',
  'tests/playbooks',
  'tests/policy',
  'tests/recruiting',
  'tests/tasks',
  'tests/workers'
)

$e2eShards = @(
  'tests/e2e',
  'tests/pw',
  'tests/browser'
)

$rootFiles = Get-ChildItem tests -File -Filter 'test_*.py' |
  Select-Object -ExpandProperty FullName

$all = $coreShards + $rootFiles
if ($runE2E)    { $all += $e2eShards }
if ($runBrowser) { $all += @('tests/redteam') }

$outDir = Join-Path $PSScriptRoot 'runs'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$logFile = Join-Path $outDir "fullsuite_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

$failures = @()
$passes   = @()

"=== ShopSquire Full Suite: $(Get-Date) ===" | Tee-Object -FilePath $logFile

foreach ($t in $all) {
  if (-not (Test-Path $t)) { continue }

  # --- memory guard: warn if free RAM < 8 GB before each shard ---
  $freeGB = [math]::Round(
    (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
  if ($freeGB -lt 8) {
    Write-Warning "Low memory ($freeGB GB free) before shard '$t' — waiting 15s..."
    Start-Sleep 15
    $freeGB = [math]::Round(
      (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
    if ($freeGB -lt 6) {
      Write-Warning "Still low ($freeGB GB). Skipping shard to avoid OOM: $t"
      $failures += "$t [SKIPPED-LOW-MEM]"
      continue
    }
  }

  Write-Host "`n=== RUNNING: $t (free RAM: $freeGB GB) ===" -ForegroundColor Cyan
  $result = & python -m pytest -q --tb=short $t 2>&1
  $code   = $LASTEXITCODE
  $result | Tee-Object -FilePath $logFile -Append

  if ($code -eq 0 -or $code -eq 5) {
    # exit 5 = no tests collected — treat as pass
    $passes += $t
    Write-Host "=== PASS: $t ===" -ForegroundColor Green
  } else {
    $failures += $t
    Write-Host "=== FAIL($code): $t ===" -ForegroundColor Red
  }

  # Brief pause between shards so Python GC/OS can reclaim memory
  Start-Sleep 2
}

"`n===== SHARD SUMMARY =====" | Tee-Object -FilePath $logFile -Append
"Passed : $($passes.Count)" | Tee-Object -FilePath $logFile -Append
"Failed : $($failures.Count)" | Tee-Object -FilePath $logFile -Append
if ($failures.Count -gt 0) {
  "Failed shards:" | Tee-Object -FilePath $logFile -Append
  $failures | ForEach-Object { "  - $_" | Tee-Object -FilePath $logFile -Append }
  exit 1
}
exit 0
