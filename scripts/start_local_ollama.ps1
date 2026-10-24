# Start a dedicated server with the same bounded profile used by start_demo.ps1.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_demo_runtime.ps1')
$listener = Get-NetTCPConnection -LocalPort $demoProfile.ollama_port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw 'The dedicated demo port is occupied. No existing server was adopted or stopped.'
}
$receiptPath = Join-Path $demoRoot '.artifacts/ollama-runtime-receipt.json'
$null = New-Item -ItemType Directory -Force -Path (Split-Path $receiptPath)
$server = Start-Process -FilePath (Get-Command ollama).Source -ArgumentList 'serve' -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $demoRoot '.artifacts/ollama-bounded.stdout.log') `
    -RedirectStandardError (Join-Path $demoRoot '.artifacts/ollama-bounded.stderr.log')
try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        $server.Refresh()
        if ($server.HasExited) { throw 'Bounded Ollama exited before startup completed.' }
        $listener = Get-NetTCPConnection -LocalPort $demoProfile.ollama_port -State Listen -ErrorAction SilentlyContinue
        if ($listener -and @($listener.OwningProcess) -contains $server.Id) { $ready = $true; break }
        Start-Sleep -Milliseconds 200
    }
    if (-not $ready) { throw 'Bounded Ollama did not bind its dedicated port.' }
    @{
        pid = $server.Id
        start_ticks = [string]$server.StartTime.ToUniversalTime().Ticks
        profile_hash = (Get-FileHash (Join-Path $demoRoot 'config/local_demo_runtime.json') -Algorithm SHA256).Hash
        url = $env:OLLAMA_URL
    } | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    Write-Host "Bounded Ollama ready at $env:OLLAMA_URL (PID $($server.Id)). Keep this launcher running."
    Wait-Process -Id $server.Id
} finally {
    # This launcher owns only the process it created.
    $server.Refresh()
    if (-not $server.HasExited) { $server.Kill() }
    if (Test-Path -LiteralPath $receiptPath) {
        $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
        if ($receipt.pid -eq $server.Id) { Remove-Item -LiteralPath $receiptPath }
    }
}
