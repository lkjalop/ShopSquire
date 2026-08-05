[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$SubscriptionId,
    [Parameter(Mandatory = $true)][string]$ResourceGroup,
    [Parameter(Mandatory = $true)][string]$BackendImage,
    [Parameter(Mandatory = $true)][string]$WebImage,
    [Parameter(Mandatory = $true)][string]$OwnerEmail,
    [string]$Location = 'australiaeast',
    [string]$Prefix = 'shopsquire-prod',
    [int]$MonthlyBudgetAmount = 1500,
    [switch]$EnableReadReplica,
    [switch]$DisablePostgresHa,
    [switch]$SkipWhatIf,
    [string]$SecretBundlePath = "$PSScriptRoot\.shopsquire-production.secrets.clixml"
)

$ErrorActionPreference = 'Stop'
$az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
if (-not (Test-Path -LiteralPath $az)) {
    $azCommand = Get-Command az -ErrorAction SilentlyContinue
    if (-not $azCommand) { throw 'Azure CLI is required. Install it and run az login.' }
    $az = $azCommand.Source
}

function Invoke-Az {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $az @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: az $($Arguments -join ' ')" }
}

function New-RandomSecret([int]$Bytes = 32) {
    $buffer = [byte[]]::new($Bytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    ConvertTo-SecureString ([Convert]::ToHexString($buffer).ToLowerInvariant()) -AsPlainText -Force
}

function Reveal([SecureString]$Value) {
    [System.Net.NetworkCredential]::new('', $Value).Password
}

$secretPath = [System.IO.Path]::GetFullPath($SecretBundlePath)
if (Test-Path -LiteralPath $secretPath) {
    $secrets = Import-Clixml -LiteralPath $secretPath
} else {
    if ($env:OS -ne 'Windows_NT') {
        throw 'First deployment must run on Windows or use a pre-created SecretBundlePath; CLIXML protection is user/machine scoped.'
    }
    $secrets = [pscustomobject]@{
        postgresAdminPassword = New-RandomSecret
        jwtSigningKey = New-RandomSecret
        celeryHmacKey = New-RandomSecret
        auditChainSecret = New-RandomSecret
        backupEncryptionKey = New-RandomSecret
        returnEvidenceKey = New-RandomSecret
        merchantApiKey = New-RandomSecret
        ownerApiKey = New-RandomSecret
        developerApiKey = New-RandomSecret
        budgetStartDate = [DateTimeOffset]::UtcNow.ToString('yyyy-MM-01')
    }
    $secrets | Export-Clixml -LiteralPath $secretPath
    Write-Warning "Created deployment secret bundle at $secretPath. It is DPAPI-protected for this Windows user and machine. Back it up securely; never commit it."
}
if (-not $secrets.PSObject.Properties['returnEvidenceKey']) {
    $secrets | Add-Member -NotePropertyName returnEvidenceKey -NotePropertyValue (New-RandomSecret)
    $secrets | Export-Clixml -LiteralPath $secretPath
    Write-Warning 'Added the versioned return-evidence envelope key to the protected deployment bundle.'
}

Invoke-Az account set --subscription $SubscriptionId
Invoke-Az extension add --name containerapp --upgrade --allow-preview false --output none
foreach ($namespace in @(
    'Microsoft.App', 'Microsoft.Cdn', 'Microsoft.Cache', 'Microsoft.Compute',
    'Microsoft.Consumption', 'Microsoft.ContainerRegistry', 'Microsoft.DBforPostgreSQL',
    'Microsoft.Insights', 'Microsoft.KeyVault', 'Microsoft.ManagedIdentity',
    'Microsoft.Network', 'Microsoft.OperationalInsights', 'Microsoft.Storage'
)) {
    Invoke-Az provider register --namespace $namespace --wait --output none
}

Invoke-Az bicep build --file "$PSScriptRoot\main.bicep" --stdout | Out-Null
Invoke-Az group create --name $ResourceGroup --location $Location --output none

$parameterPath = Join-Path ([System.IO.Path]::GetTempPath()) "shopsquire-$([guid]::NewGuid().ToString('N')).parameters.json"
$parameterObject = @{
    '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'
    parameters = @{
        prefix = @{ value = $Prefix }
        location = @{ value = $Location }
        backendImage = @{ value = $BackendImage }
        webImage = @{ value = $WebImage }
        ownerEmail = @{ value = $OwnerEmail }
        monthlyBudgetAmount = @{ value = $MonthlyBudgetAmount }
        enableReadReplica = @{ value = [bool]$EnableReadReplica }
        enablePostgresHa = @{ value = -not [bool]$DisablePostgresHa }
        postgresAdminPassword = @{ value = Reveal $secrets.postgresAdminPassword }
        jwtSigningKey = @{ value = Reveal $secrets.jwtSigningKey }
        celeryHmacKey = @{ value = Reveal $secrets.celeryHmacKey }
        auditChainSecret = @{ value = Reveal $secrets.auditChainSecret }
        backupEncryptionKey = @{ value = Reveal $secrets.backupEncryptionKey }
        returnEvidenceKey = @{ value = Reveal $secrets.returnEvidenceKey }
        merchantApiKey = @{ value = Reveal $secrets.merchantApiKey }
        ownerApiKey = @{ value = Reveal $secrets.ownerApiKey }
        developerApiKey = @{ value = Reveal $secrets.developerApiKey }
        budgetStartDate = @{ value = [string]$secrets.budgetStartDate }
    }
}

try {
    $parameterObject | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $parameterPath -Encoding utf8
    if (-not $SkipWhatIf) {
        Invoke-Az deployment group what-if --resource-group $ResourceGroup `
            --template-file "$PSScriptRoot\main.bicep" `
            --parameters "@$parameterPath" --result-format ResourceIdOnly
    }
    if (-not $PSCmdlet.ShouldProcess($ResourceGroup, 'Deploy production ShopSquire Azure topology')) { return }
    $deployment = Invoke-Az deployment group create --resource-group $ResourceGroup `
        --name "shopsquire-$([DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss'))" `
        --template-file "$PSScriptRoot\main.bicep" `
        --parameters "@$parameterPath" --query properties.outputs --output json | ConvertFrom-Json
} finally {
    $resolvedTemp = [System.IO.Path]::GetFullPath($parameterPath)
    $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedTemp.StartsWith($resolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedTemp)) {
        Remove-Item -LiteralPath $resolvedTemp -Force
    }
}

$edgeEnvironmentId = Invoke-Az resource list --resource-group $ResourceGroup `
    --resource-type Microsoft.App/managedEnvironments `
    --query "[?contains(name, 'edge')].id | [0]" --output tsv
if ($edgeEnvironmentId) {
    $connections = Invoke-Az network private-endpoint-connection list --id $edgeEnvironmentId `
        --query "[?properties.privateLinkServiceConnectionState.status=='Pending'].id" --output tsv
    foreach ($connectionId in @($connections)) {
        if ($connectionId) {
            Invoke-Az network private-endpoint-connection approve --id $connectionId `
                --description 'Approved ShopSquire Front Door private origin' --output none
        }
    }
}

# Internal Container Apps environments require a private wildcard zone for
# callers in sibling subnets. Create it after the environment exposes its
# generated default domain and internal load-balancer address.
$coreEnvironmentId = $deployment.coreEnvironmentId.value
$coreEnvironmentName = Split-Path -Leaf $coreEnvironmentId
$coreDomain = Invoke-Az containerapp env show --resource-group $ResourceGroup --name $coreEnvironmentName `
    --query properties.defaultDomain --output tsv
$coreIp = Invoke-Az containerapp env show --resource-group $ResourceGroup --name $coreEnvironmentName `
    --query properties.staticIp --output tsv
if (-not $coreDomain -or -not $coreIp) { throw 'Core Container Apps private DNS inputs were not returned.' }
Invoke-Az network private-dns zone create --resource-group $ResourceGroup --name $coreDomain --output none
Invoke-Az network private-dns link vnet create --resource-group $ResourceGroup --zone-name $coreDomain `
    --name "$Prefix-core-environment-link" --virtual-network $deployment.vnetId.value `
    --registration-enabled false --output none
Invoke-Az network private-dns record-set a create --resource-group $ResourceGroup --zone-name $coreDomain `
    --name '*' --ttl 60 --output none
$existingCoreIps = Invoke-Az network private-dns record-set a show --resource-group $ResourceGroup `
    --zone-name $coreDomain --name '*' --query 'aRecords[].ipv4Address' --output tsv
if ($coreIp -notin @($existingCoreIps)) {
    Invoke-Az network private-dns record-set a add-record --resource-group $ResourceGroup --zone-name $coreDomain `
        --record-set-name '*' --ipv4-address $coreIp --output none
}

$jobName = $deployment.migrationJobName.value
$execution = Invoke-Az containerapp job start --resource-group $ResourceGroup --name $jobName --output json | ConvertFrom-Json
$executionName = [string]$execution.name
$deadline = [DateTimeOffset]::UtcNow.AddMinutes(20)
do {
    Start-Sleep -Seconds 10
    $status = Invoke-Az containerapp job execution show --resource-group $ResourceGroup `
        --name $jobName --job-execution-name $executionName --query properties.status --output tsv
    Write-Host "Migration $executionName status: $status"
    if ($status -in @('Succeeded', 'Failed')) { break }
} while ([DateTimeOffset]::UtcNow -lt $deadline)
if ($status -ne 'Succeeded') { throw "Migration failed or timed out (status=$status); traffic must remain blocked." }

$publicUrl = $deployment.publicUrl.value
$smokeDeadline = [DateTimeOffset]::UtcNow.AddMinutes(10)
do {
    try {
        $response = Invoke-WebRequest -Uri "$publicUrl/healthz" -TimeoutSec 15 -MaximumRedirection 2
        if ($response.StatusCode -eq 200) { break }
    } catch { Start-Sleep -Seconds 15 }
} while ([DateTimeOffset]::UtcNow -lt $smokeDeadline)
if (-not $response -or $response.StatusCode -ne 200) { throw "Front Door smoke check did not become healthy: $publicUrl/healthz" }

Write-Host "ShopSquire: $publicUrl"
Write-Host "Stable outbound IP: $($deployment.outboundIpAddress.value)"
Write-Host "Migration execution: $executionName ($status)"
Write-Host 'Payment execution and autonomous supplier sending remain disabled by default.'
