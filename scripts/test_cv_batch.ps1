param(
    [string]$ApiBase = "http://127.0.0.1:8080",
    [string]$ApiKey = "local-owner-key",
    [string]$Folder = "C:\AI\ShopSquire\dump\test-cv"
)

$ErrorActionPreference = "Stop"

function Invoke-CVAnalyze([string]$filePath) {
    $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($filePath))
    $caseId = "CASE-BATCH-" + [int][double]::Parse((Get-Date -UFormat %s))
    $body = @{ case_id = $caseId; images_b64 = @($b64); description = 'batch test'; issue_type = 'damage_claim' } | ConvertTo-Json -Depth 6
    $headers = @{ "x-api-key" = $ApiKey }
    return Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/cv/analyze" -Headers $headers -ContentType 'application/json' -Body $body
}

$files = Get-ChildItem -Path $Folder -File | Where-Object { $_.Extension -in @('.png','.jpg','.jpeg','.webp') } | Sort-Object Name
if (-not $files) { Write-Host "No images found in $Folder"; exit 1 }

Write-Host "Testing CV analyze for $($files.Count) images in $Folder" -ForegroundColor Cyan

$results = @()
foreach ($f in $files) {
    try {
        $resp = Invoke-CVAnalyze -filePath $f.FullName
        $ic = $resp.image_consistency
        $qr = $resp.qr_codes
        $ui = $resp.ui_actions
        $status = if ($ic) { $ic.status } else { 'na' }
        $qrSummary = if ($qr) { if ($qr -is [Array]) { ($qr | ForEach-Object { $_.type }) -join ',' } else { $qr.type } } else { '' }
        $chatFlag = if ($ui) { [bool]$ui.chat_with_admin } else { $false }
        $results += [pscustomobject]@{
            File = $f.Name
            Status = $status
            QRCodes = $qrSummary
            ChatWithAdmin = $chatFlag
        }
    } catch {
        $results += [pscustomobject]@{
            File = $f.Name
            Status = 'error'
            QRCodes = ''
            ChatWithAdmin = $false
        }
    }
}

$results | Format-Table -AutoSize

# Emit JSON for tooling
$results | ConvertTo-Json -Depth 4
