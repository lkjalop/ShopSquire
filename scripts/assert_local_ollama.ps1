# Operational launch provenance, not a security attestation against a local admin.
# Caller first loads local_demo_runtime.ps1; client env alone cannot bound a server.
$receiptPath = Join-Path $demoRoot '.artifacts/ollama-runtime-receipt.json'
if (-not (Test-Path -LiteralPath $receiptPath)) {
    throw 'No bounded server receipt. Run scripts/start_local_ollama.ps1 in another terminal first.'
}
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$server = Get-Process -Id $receipt.pid -ErrorAction SilentlyContinue
$listener = Get-NetTCPConnection -LocalPort $demoProfile.ollama_port -State Listen -ErrorAction SilentlyContinue
$profileHash = (Get-FileHash (Join-Path $demoRoot 'config/local_demo_runtime.json') -Algorithm SHA256).Hash
if (-not $server -or $server.ProcessName -ne 'ollama' -or
    [string]$server.StartTime.ToUniversalTime().Ticks -ne $receipt.start_ticks -or
    $receipt.profile_hash -ne $profileHash -or $receipt.url -ne $env:OLLAMA_URL -or
    -not (@($listener.OwningProcess) -contains $server.Id)) {
    throw 'Bounded server receipt is stale or mismatched. Restart scripts/start_local_ollama.ps1.'
}
$null = Invoke-RestMethod -Uri ($env:OLLAMA_URL + '/api/version') -TimeoutSec 5
