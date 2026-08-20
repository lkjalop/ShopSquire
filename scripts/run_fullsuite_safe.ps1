<#
.SYNOPSIS
  Memory-safe full test suite runner.
  - Runs each test shard in a fresh subprocess.
  - Pauses between heavy shards to let Python GC and the OS reclaim memory.
  - Skips shards that require live infrastructure unless explicitly opted in.
  - Logs results to scripts/runs/.

.NOTES
  Run shards sequentially because each pytest shard loads the FastAPI app.
#>

$ErrorActionPreference = 'Continue'
$runE2E = $env:RUN_E2E -eq '1'
$runBrowser = $env:RUN_BROWSER -eq '1'
$resumeAfter = $env:FULLSUITE_RESUME_AFTER

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
if ($runE2E) { $all += $e2eShards }
if ($runBrowser) { $all += @('tests/redteam') }
if ($resumeAfter) {
  $resumeIndex = [array]::IndexOf($all, $resumeAfter)
  if ($resumeIndex -lt 0) {
    throw "FULLSUITE_RESUME_AFTER target was not found: $resumeAfter"
  }
  if ($resumeIndex -ge ($all.Count - 1)) {
    $all = @()
  } else {
    $all = $all[($resumeIndex + 1)..($all.Count - 1)]
  }
}

$outDir = Join-Path $PSScriptRoot 'runs'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$logFile = Join-Path $outDir "fullsuite_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

$failures = @()
$passes = @()

"=== ShopSquire Full Suite: $(Get-Date) ===" | Tee-Object -FilePath $logFile

foreach ($t in $all) {
  if (-not (Test-Path $t)) { continue }

  $freeGB = [math]::Round(
    (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
  if ($freeGB -lt 8) {
    Write-Warning "Low memory ($freeGB GB free) before shard '$t'; waiting 15s..."
    Start-Sleep 15
    $freeGB = [math]::Round(
      (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
    if ($freeGB -lt 6) {
      Write-Warning "Still low ($freeGB GB). Skipping shard to avoid OOM: $t"
      $failures += "$t [SKIPPED-LOW-MEM]"
      continue
    }
  }

  "`n=== RUNNING: $t (free RAM: $freeGB GB) ===" |
    Tee-Object -FilePath $logFile -Append
  $result = & python -m pytest -q --tb=short $t 2>&1
  $code = $LASTEXITCODE
  $result | Tee-Object -FilePath $logFile -Append

  if ($code -eq 0 -or $code -eq 5) {
    $passes += $t
    "=== PASS: $t ===" | Tee-Object -FilePath $logFile -Append
  } else {
    $failures += $t
    "=== FAIL($code): $t ===" | Tee-Object -FilePath $logFile -Append
  }

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
