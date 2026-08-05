[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SubscriptionId,
    [Parameter(Mandatory = $true)][string]$ResourceGroup,
    [Parameter(Mandatory = $true)][string]$BackendImage,
    [Parameter(Mandatory = $true)][string]$WebImage,
    [Parameter(Mandatory = $true)][SecureString]$DatabaseUrl,
    [Parameter(Mandatory = $true)][SecureString]$RedisUrl,
    [string]$Location = 'australiaeast',
    [string]$Prefix = 'shopsquire-demo'
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI is required. Install it, then run az login.'
}

az account set --subscription $SubscriptionId
az extension add --name containerapp --upgrade --allow-preview false --output none
az bicep build --file "$PSScriptRoot/main.bicep" --stdout | Out-Null
az group create --name $ResourceGroup --location $Location --output none
foreach ($namespace in @('Microsoft.App', 'Microsoft.OperationalInsights', 'Microsoft.ManagedIdentity', 'Microsoft.KeyVault', 'Microsoft.Storage')) {
    az provider register --namespace $namespace --wait
}

function New-RandomHex([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToHexString($buffer).ToLowerInvariant()
}

$dbPlain = [System.Net.NetworkCredential]::new('', $DatabaseUrl).Password
$redisPlain = [System.Net.NetworkCredential]::new('', $RedisUrl).Password
$merchantKey = New-RandomHex 32
$ownerKey = New-RandomHex 32
$developerKey = New-RandomHex 32
$deployment = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$PSScriptRoot/main.bicep" `
    --parameters prefix=$Prefix location=$Location backendImage=$BackendImage webImage=$WebImage `
      databaseUrl=$dbPlain redisUrl=$redisPlain jwtSigningKey=$(New-RandomHex 32) `
      celeryHmacKey=$(New-RandomHex 32) auditChainSecret=$(New-RandomHex 32) `
      backupEncryptionKey=$(New-RandomHex 32) merchantApiKey=$merchantKey `
      ownerApiKey=$ownerKey developerApiKey=$developerKey `
    --query properties.outputs `
    --output json

$outputs = $deployment | ConvertFrom-Json
$jobName = $outputs.migrationJobName.value
$execution = az containerapp job start --resource-group $ResourceGroup --name $jobName --output json | ConvertFrom-Json
$executionName = [string]$execution.name
if (-not $executionName) {
    throw 'Azure did not return a migration execution name.'
}

$deadline = [DateTimeOffset]::UtcNow.AddMinutes(15)
do {
    Start-Sleep -Seconds 10
    $status = az containerapp job execution show `
        --resource-group $ResourceGroup `
        --name $jobName `
        --job-execution-name $executionName `
        --query properties.status `
        --output tsv
    Write-Host "Migration $executionName status: $status"
    if ($status -in @('Succeeded', 'Failed')) { break }
} while ([DateTimeOffset]::UtcNow -lt $deadline)

if ($status -ne 'Succeeded') {
    throw "Migration job did not succeed (status=$status). Do not send traffic to this revision."
}
Write-Host "ShopSquire URL: $($outputs.webUrl.value)"
Write-Host "Retrieve the owner UI key when needed: az keyvault secret show --vault-name $($outputs.keyVaultName.value) --name owner-api-key --query value -o tsv"
