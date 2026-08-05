[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SubscriptionId,
    [Parameter(Mandatory = $true)][string]$ResourceGroup,
    [string]$Prefix = 'shopsquire-prod'
)

$ErrorActionPreference = 'Stop'
$az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
if (-not (Test-Path -LiteralPath $az)) {
    $command = Get-Command az -ErrorAction SilentlyContinue
    if (-not $command) { throw 'Azure CLI is required.' }
    $az = $command.Source
}
function Az([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments) {
    $result = & $az @Arguments
    if ($LASTEXITCODE -ne 0) { throw "az $($Arguments -join ' ') failed" }
    $result
}
function Assert-Equal($Actual, $Expected, [string]$Label) {
    if ([string]$Actual -ne [string]$Expected) { throw "$Label expected '$Expected', got '$Actual'" }
    Write-Host "PASS $Label = $Expected"
}

Az account set --subscription $SubscriptionId
$deployment = Az deployment group list --resource-group $ResourceGroup `
    --query "sort_by([?starts_with(name, 'shopsquire-')], &properties.timestamp)[-1].name" --output tsv
if (-not $deployment) { throw 'No ShopSquire deployment was found.' }
$outputs = Az deployment group show --resource-group $ResourceGroup --name $deployment `
    --query properties.outputs --output json | ConvertFrom-Json

$environments = Az containerapp env list --resource-group $ResourceGroup --output json | ConvertFrom-Json
if (@($environments).Count -ne 2) { throw "Expected two Container Apps environments; found $(@($environments).Count)." }
foreach ($environment in $environments) {
    Assert-Equal $environment.properties.publicNetworkAccess 'Disabled' "ACA $($environment.name) public access"
    Assert-Equal $environment.properties.vnetConfiguration.internal $true "ACA $($environment.name) internal VIP"
    Assert-Equal $environment.properties.zoneRedundant $true "ACA $($environment.name) zone redundancy"
}

$postgres = Az postgres flexible-server list --resource-group $ResourceGroup --output json | ConvertFrom-Json
if (@($postgres).Count -lt 1) { throw 'PostgreSQL Flexible Server was not found.' }
foreach ($server in $postgres) {
    Assert-Equal $server.network.publicNetworkAccess 'Disabled' "PostgreSQL $($server.name) public access"
}

$redis = Az redisenterprise list --resource-group $ResourceGroup --output json | ConvertFrom-Json
if (@($redis).Count -ne 1) { throw 'Expected one Azure Managed Redis cluster.' }
Assert-Equal $redis[0].properties.publicNetworkAccess 'Disabled' 'Managed Redis public access'

$vault = Az keyvault list --resource-group $ResourceGroup --output json | ConvertFrom-Json
Assert-Equal $vault[0].properties.publicNetworkAccess 'Disabled' 'Key Vault public access'
$storage = Az storage account list --resource-group $ResourceGroup --output json | ConvertFrom-Json
Assert-Equal $storage[0].publicNetworkAccess 'Disabled' 'Storage public access'
$registry = Az acr list --resource-group $ResourceGroup --output json | ConvertFrom-Json
Assert-Equal $registry[0].publicNetworkAccess 'Disabled' 'Registry public access'

$privateEndpoints = Az network private-endpoint list --resource-group $ResourceGroup --output json | ConvertFrom-Json
if (@($privateEndpoints).Count -lt 5) { throw "Expected at least five data private endpoints; found $(@($privateEndpoints).Count)." }
Write-Host "PASS private endpoints = $(@($privateEndpoints).Count)"

$migrationJob = $outputs.migrationJobName.value
$migration = Az containerapp job execution list --resource-group $ResourceGroup --name $migrationJob `
    --query "sort_by([], &properties.startTime)[-1].properties.status" --output tsv
Assert-Equal $migration 'Succeeded' 'latest migration execution'

$publicUrl = $outputs.publicUrl.value
$health = Invoke-WebRequest -Uri "$publicUrl/healthz" -TimeoutSec 20 -MaximumRedirection 2
Assert-Equal $health.StatusCode 200 'Front Door health response'
Write-Host "PASS public edge $publicUrl"
Write-Host 'Validation proves deployed topology and health, not restore success or business performance.'
