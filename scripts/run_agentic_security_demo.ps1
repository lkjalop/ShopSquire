Param(
  [string]$BaseUrl = "http://127.0.0.1:8080",
  [string]$ApiKey = "local-owner-key",
  [string]$TenantId = "demo-tenant"
)

$ErrorActionPreference = "Stop"

function Invoke-JsonPost($Url, $Obj) {
  $json = ($Obj | ConvertTo-Json -Depth 10)
  return curl.exe -sS -X POST "$Url" -H "Content-Type: application/json" -H "x-api-key: $ApiKey" -H "X-Tenant-Id: $TenantId" -d "$json"
}

Write-Host "Health: $BaseUrl/healthz"
curl.exe -sS "$BaseUrl/healthz" | Out-Host

Write-Host "`n1) Email BEC evaluate -> playbook selection -> playbook run"
$email = @{
  tenant_id = $TenantId
  message_id = "<demo-bec@local>"
  from_addr = "CEO <ceo@microsoft.com>"
  reply_to = "finance@micros0ft.com"
  subject = "Urgent wire transfer"
  body = "Please update bank details and wire transfer today."
  external_sender = $true
  spf_result = "pass"
  dkim_result = "pass"
  dmarc_result = "pass"
  dmarc_policy = "reject"
  attachments = @(@{ name="invoice.html"; content_type="text/html"; content_b64="PGh0bWw+PGJvZHk+VEVTVDwvYm9keT48L2h0bWw+" })
}
$resp = Invoke-JsonPost "$BaseUrl/api/v1/email_security/evaluate" $email
$resp | Out-Host

Write-Host "`n2) Outbound C2 simulate -> anomalies"
$outbound = @{
  tenant_id = $TenantId
  agent_id = "agent-demo"
  to = "c2@example.invalid"
  subject = "cGluZw==cGluZw==cGluZw=="
  body = "ok"
  count = 8
  interval_sec = 0.2
  minutes = 60
}
Invoke-JsonPost "$BaseUrl/api/v1/admin/email_security/outbound/simulate" $outbound | Out-Host

Write-Host "`n3) List outbound anomalies"
curl.exe -sS "$BaseUrl/api/v1/admin/email_security/outbound/anomalies?limit=20" -H "x-api-key: $ApiKey" | Out-Host

Write-Host "`n4) Security events (admin)"
curl.exe -sS "$BaseUrl/api/v1/admin/security/events?limit=50" -H "x-api-key: $ApiKey" | Out-Host

