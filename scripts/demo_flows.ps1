<#
Run a small set of demo flows against a running local server (http://127.0.0.1:8080).
Sends requests that produce decision logs, traceable activity, and a ticket creation.

Usage:
  .\scripts\demo_flows.ps1
#>
$base = "http://127.0.0.1:8080"
# Use `DEMO_API_KEY` env var if present, otherwise default to local developer key
$apiKey = $env:DEMO_API_KEY
if (-not $apiKey) { $apiKey = 'local-developer-key' }
$hdr = @{ 'x-api-key' = $apiKey }
Write-Host "Demo flows -> $base (using x-api-key: $($apiKey.Substring(0,[Math]::Min(8,$apiKey.Length)))...)"

function TryGet([string]$url) {
    try {
        $res = Invoke-RestMethod -Uri $url -Method Get -Headers $hdr -TimeoutSec 30
        return $res
    } catch {
        Write-Host "GET $url failed: $_"
        return $null
    }
}

function TryPost([string]$url, $body) {
    try {
        $res = Invoke-RestMethod -Uri $url -Method Post -Body $body -ContentType 'application/json' -Headers $hdr -TimeoutSec 30
        return $res
    } catch {
        Write-Host "POST $url failed: $_"
        return $null
    }
}

Write-Host "1) Recommend suggest (NLP rerank path)"
$r1 = TryGet "$base/api/v1/recommend/suggest?uid=demo-user&query=Top%205%20laptops%20under%201500"
Write-Host "Response:`n"; $r1 | ConvertTo-Json -Depth 5

Write-Host "2) Pricing suggest (orchestrator -> decision log)"
$r2 = TryGet "$base/api/v1/pricing/suggest?uid=demo-user&cart_total_cents=120000"
Write-Host "Response:`n"; $r2 | ConvertTo-Json -Depth 5

Write-Host "3) Create a demo ticket (ticketing agent logs decision)"
$r3 = TryPost "$base/api/v1/incident/ticket?topic=security&title=DemoTicket&description=Created%20by%20demo&priority=p2" $null
Write-Host "Response:`n"; $r3 | ConvertTo-Json -Depth 5

Write-Host "4) List recent decisions (admin)"
$r4 = TryGet "$base/api/v1/admin/decisions?limit=10"
Write-Host "Response:`n"; $r4 | ConvertTo-Json -Depth 5

if ($r1 -and $r1.proposal) { if ($r1.proposal.trace_id) { Write-Host "Trace link: http://localhost:16686/trace/$($r1.proposal.trace_id)" } }
if ($r2 -and $r2.proposal) { if ($r2.proposal.trace_id) { Write-Host "Trace link: http://localhost:16686/trace/$($r2.proposal.trace_id)" } }

Write-Host "Demo flows complete. Inspect admin UI (/ui/status) and Jaeger (if running) to view traces and decision logs."
