Param(
  [string]$ApiBase = "http://127.0.0.1:8080",
  [string]$FrontendBase = "http://127.0.0.1:5173",
  [string]$OllamaBase = "http://127.0.0.1:11434",
  [string]$ApiKey = "local-owner-key",
  [int]$MaxRetries = 40
)

$ErrorActionPreference = "Stop"

function Wait-Url([string]$Url, [int]$Retries = 20, [int]$SleepMs = 1500) {
  for ($i = 0; $i -lt $Retries; $i++) {
    try {
      $r = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 3
      if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
    } catch {
      # retry
    }
    Start-Sleep -Milliseconds $SleepMs
  }
  return $false
}

Write-Host "[start] Launching backend (8080) ..."
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "cd `"$PSScriptRoot\..`"; uvicorn src.app.main:create_app --factory --host 127.0.0.1 --port 8080"
) | Out-Null

Write-Host "[start] Launching frontend (5173) ..."
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "cd `"$PSScriptRoot\..\frontend`"; npm run dev -- --host 127.0.0.1 --port 5173"
) | Out-Null

Write-Host "[start] Waiting for backend health ..."
if (-not (Wait-Url "$ApiBase/healthz" -Retries $MaxRetries -SleepMs 1500)) {
  throw "Backend did not become healthy at $ApiBase/healthz"
}
Write-Host "[ok] Backend healthz ready."

Write-Host "[start] Waiting for frontend ..."
if (-not (Wait-Url $FrontendBase -Retries $MaxRetries -SleepMs 1500)) {
  Write-Warning "Frontend did not respond at $FrontendBase (continuing)."
} else {
  Write-Host "[ok] Frontend ready."
}

Write-Host "[start] Ollama warmup ..."
$models = @("llava:latest", "llama3.2:3b")
foreach ($m in $models) {
  try {
    $payload = @{ model = $m; prompt = "Warmup: reply OK"; stream = $false } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post -Uri "$OllamaBase/api/generate" -ContentType "application/json" -Body $payload -TimeoutSec 60 | Out-Null
    Write-Host "[ok] Ollama warm: $m"
  } catch {
    Write-Warning "Ollama warmup failed for $m"
  }
}

Write-Host "[start] CV warmup (best effort) ..."
try {
  Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/cv/warmup" -Headers @{ "x-api-key" = $ApiKey } -TimeoutSec 60 | Out-Null
  Write-Host "[ok] CV warmup endpoint completed."
} catch {
  Write-Warning "CV warmup failed or unavailable."
}

Write-Host "[start] Readiness check ..."
if (-not (Wait-Url "$ApiBase/readyz" -Retries $MaxRetries -SleepMs 1500)) {
  throw "Readiness check failed at $ApiBase/readyz"
}
$ready = Invoke-RestMethod -Method Get -Uri "$ApiBase/readyz" -TimeoutSec 5
Write-Host ("[ready] status={0}" -f ($ready.status))
if ($ready.components) {
  $ready.components.PSObject.Properties | ForEach-Object {
    Write-Host ("  - {0}: {1}" -f $_.Name, $_.Value.status)
  }
}

Write-Host ""
Write-Host "System started."
Write-Host ("Frontend: {0}" -f $FrontendBase)
Write-Host ("Backend:  {0}" -f $ApiBase)
Write-Host ("Readyz:   {0}/readyz" -f $ApiBase)
