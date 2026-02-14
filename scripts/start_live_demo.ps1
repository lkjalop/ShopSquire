Param(
  [string]$ApiKey = "local-owner-key",
  [string]$TenantId = "demo-tenant",
  [string]$ApiBase = "http://127.0.0.1:8080",
  [string]$OllamaBase = "http://127.0.0.1:11434",
  [switch]$StartFrontend
)

$ErrorActionPreference = "Stop"

function Wait-HttpOk([string]$Url, [int]$TimeoutSec = 60) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 3
      return $true
    } catch {
      Start-Sleep -Milliseconds 750
    }
  }
  return $false
}

Write-Host "[demo] Bringing up docker compose stack..."
docker compose up -d | Out-Null

Write-Host "[demo] Waiting for API health..."
if (-not (Wait-HttpOk "$ApiBase/healthz" 75)) {
  throw "API did not become healthy at $ApiBase/healthz"
}
Write-Host "[demo] API is healthy."

try {
  Write-Host "[demo] CV warmup..."
  Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/cv/warmup" -Headers @{ "x-api-key" = $ApiKey } -TimeoutSec 10 | Out-Null
} catch {
  Write-Host "[demo] CV warmup skipped/failed (non-fatal)."
}

try {
  Write-Host "[demo] CV readiness snapshot..."
  $cv = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/v1/admin/cv/readiness" -Headers @{ "x-api-key" = $ApiKey } -TimeoutSec 10
  Write-Host ("[demo] CV deps: pytesseract={0} cv2={1} paddleocr={2}" -f $cv.deps.pytesseract.ok, $cv.deps.cv2.ok, $cv.deps.paddleocr.ok)
} catch {
  Write-Host "[demo] CV readiness unavailable (non-fatal)."
}

Write-Host "[demo] Prewarming Ollama models..."
$envLines = Get-Content -Path ".env" -ErrorAction SilentlyContinue
$ollamaDefault = ($envLines | Where-Object { $_ -match '^OLLAMA_DEFAULT_MODEL=' } | Select-Object -First 1) -replace '^OLLAMA_DEFAULT_MODEL=', ''
$ollamaBig = ($envLines | Where-Object { $_ -match '^OLLAMA_BIG_MODEL=' } | Select-Object -First 1) -replace '^OLLAMA_BIG_MODEL=', ''
if (-not $ollamaDefault) { $ollamaDefault = "vanta-research/apollo-astralis-4b:latest" }
if (-not $ollamaBig) { $ollamaBig = "llama3.2:3b" }

foreach ($m in @($ollamaDefault, $ollamaBig) | Select-Object -Unique) {
  try {
    $payload = @{
      model = $m
      prompt = "Warmup: reply with OK"
      stream = $false
      options = @{ num_predict = 16 }
    } | ConvertTo-Json -Compress
    $resp = Invoke-RestMethod -Method Post -Uri "$OllamaBase/api/generate" -ContentType "application/json" -Body $payload -TimeoutSec 30
    $txt = ($resp.response + "").Trim()
    Write-Host ("[demo] Ollama warmup {0}: {1}" -f $m, ($txt.Substring(0, [Math]::Min(40, $txt.Length))))
  } catch {
    Write-Host ("[demo] Ollama warmup failed for {0} (non-fatal)." -f $m)
  }
}

if ($StartFrontend) {
  Write-Host "[demo] Starting frontend dev server in a new terminal..."
  Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd `"$PSScriptRoot\\..\\frontend`"; npm run dev"
  ) | Out-Null
}

Write-Host ""
Write-Host "[demo] Open these:"
Write-Host ("- API UI storefront: {0}/ui/" -f $ApiBase)
Write-Host ("- Forensics console: {0}/ui/forensics" -f $ApiBase)
Write-Host "- Grafana: http://127.0.0.1:3005"
Write-Host "- Prometheus: http://127.0.0.1:9090"
Write-Host ""
Write-Host "[demo] Live test endpoints:"
Write-Host ("- Email eval: {0}/api/v1/email_security/evaluate" -f $ApiBase)
Write-Host ("- Decision trace: {0}/api/v1/decisions/{decision_id}" -f $ApiBase)
Write-Host ("- Decision events (SSE): {0}/api/v1/decisions/{decision_id}/events/stream" -f $ApiBase)
Write-Host ("- CV upload: {0}/api/v1/cv/upload" -f $ApiBase)

