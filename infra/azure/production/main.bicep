targetScope = 'resourceGroup'

@description('Lowercase deployment prefix.')
@minLength(3)
@maxLength(20)
param prefix string = 'shopsquire-prod'
param location string = resourceGroup().location
param backendImage string
param webImage string
param ownerEmail string
param environmentName string = 'production'
param monthlyBudgetAmount int = 1500
param enableReadReplica bool = false
param enablePostgresHa bool = true
param postgresSkuName string = 'Standard_D2ds_v5'
param redisSkuName string = 'Balanced_B0'
param minWebReplicas int = 2
param maxWebReplicas int = 10
param minApiReplicas int = 2
param maxApiReplicas int = 10
param maxWorkerReplicas int = 10
param evidenceRetentionDays int = 30
param requestRateLimitPerMinute int = 300
@secure()
param postgresAdminPassword string
@secure()
param jwtSigningKey string
@secure()
param celeryHmacKey string
@secure()
param auditChainSecret string
@secure()
param backupEncryptionKey string
@secure()
param returnEvidenceKey string
@secure()
param merchantApiKey string
@secure()
param ownerApiKey string
@secure()
param developerApiKey string
@description('Stable budget start in ISO 8601, generated once by the deployer.')
param budgetStartDate string

var tags = {
  application: 'shopsquire'
  environment: environmentName
  managedBy: 'bicep'
  costCenter: 'shopsquire-platform'
  dataClassification: 'confidential'
}
var postgresAdminLogin = 'shopsquire_admin'
var resourceToken = toLower(uniqueString(subscription().subscriptionId, resourceGroup().id, prefix))
var vaultName = take(replace('${prefix}-kv-${resourceToken}', '-', ''), 24)
var storageName = take('ssq${replace(prefix, '-', '')}${resourceToken}', 24)
var registryName = replace('ssqacr${prefix}${resourceToken}', '-', '')

module network 'modules/network.bicep' = {
  name: '${prefix}-network'
  params: {
    prefix: prefix
    location: location
    tags: tags
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: '${prefix}-monitoring'
  params: {
    prefix: prefix
    location: location
    tags: tags
  }
}

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: take('${prefix}-runtime-${uniqueString(resourceGroup().id, prefix)}', 128)
  location: location
  tags: tags
}

module data 'modules/data.bicep' = {
  name: '${prefix}-data'
  params: {
    prefix: prefix
    location: location
    vnetId: network.outputs.vnetId
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    postgresAdminLogin: postgresAdminLogin
    postgresAdminPassword: postgresAdminPassword
    postgresSkuName: postgresSkuName
    enablePostgresHa: enablePostgresHa
    enableReadReplica: enableReadReplica
    redisSkuName: redisSkuName
    registryName: registryName
    evidenceRetentionDays: evidenceRetentionDays
    tags: tags
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: vaultName
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageName
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource vaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, workloadIdentity.id, 'Key Vault Secrets User')
  scope: vault
  properties: {
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource blobWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, workloadIdentity.id, 'Storage Blob Data Contributor')
  scope: storage
  properties: {
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

resource registryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, workloadIdentity.id, 'AcrPull')
  scope: registry
  properties: {
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

var databaseUrl = 'postgresql+psycopg2://${postgresAdminLogin}:${uriComponent(postgresAdminPassword)}@${data.outputs.postgresHost}:5432/${data.outputs.postgresDatabase}?sslmode=require'
var databaseReadUrl = enableReadReplica
  ? 'postgresql+psycopg2://${postgresAdminLogin}:${uriComponent(postgresAdminPassword)}@${data.outputs.readReplicaHost}:5432/${data.outputs.postgresDatabase}?sslmode=require'
  : databaseUrl
var redisPassword = data.outputs.redisPrimaryKey
var redisUrl = 'rediss://default:${uriComponent(redisPassword)}@${data.outputs.redisHost}:${data.outputs.redisPort}/0'

resource dbSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: databaseUrl }
}
resource dbReadSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-read-url'
  properties: { value: databaseReadUrl }
}
resource redisSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'redis-url'
  properties: { value: redisUrl }
}
resource redisPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'redis-password'
  properties: { value: redisPassword }
}
resource jwtSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'jwt-signing-key'
  properties: { value: jwtSigningKey }
}
resource celerySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'celery-hmac-key'
  properties: { value: celeryHmacKey }
}
resource auditSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'audit-chain-secret'
  properties: { value: auditChainSecret }
}
resource backupSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'backup-encryption-key'
  properties: { value: backupEncryptionKey }
}
resource returnEvidenceSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'return-evidence-key-v1'
  properties: { value: returnEvidenceKey }
}
resource merchantSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'merchant-api-key'
  properties: { value: merchantApiKey }
}
resource ownerSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'owner-api-key'
  properties: { value: ownerApiKey }
}
resource developerSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'developer-api-key'
  properties: { value: developerApiKey }
}

module compute 'modules/compute.bicep' = {
  name: '${prefix}-compute'
  params: {
    prefix: prefix
    location: location
    edgeSubnetId: network.outputs.edgeSubnetId
    coreSubnetId: network.outputs.coreSubnetId
    workspaceCustomerId: monitoring.outputs.workspaceCustomerId
    workspaceSharedKey: monitoring.outputs.workspaceSharedKey
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    identityId: workloadIdentity.id
    identityClientId: workloadIdentity.properties.clientId
    vaultUri: data.outputs.vaultUri
    storageName: data.outputs.storageName
    evidenceContainerName: data.outputs.evidenceContainerName
    redisHost: data.outputs.redisHost
    redisPort: data.outputs.redisPort
    backendImage: backendImage
    webImage: webImage
    registryServer: data.outputs.registryLoginServer
    minWebReplicas: minWebReplicas
    maxWebReplicas: maxWebReplicas
    minApiReplicas: minApiReplicas
    maxApiReplicas: maxApiReplicas
    maxWorkerReplicas: maxWorkerReplicas
    tags: tags
  }
  dependsOn: [
    vaultReader
    blobWriter
    registryPull
    dbSecret
    dbReadSecret
    redisSecret
    redisPasswordSecret
    jwtSecret
    celerySecret
    auditSecret
    backupSecret
    merchantSecret
    ownerSecret
    developerSecret
  ]
}

module edge 'modules/edge.bicep' = {
  name: '${prefix}-front-door'
  params: {
    prefix: prefix
    location: location
    webFqdn: compute.outputs.webFqdn
    edgeEnvironmentId: compute.outputs.edgeEnvironmentId
    requestRateLimitPerMinute: requestRateLimitPerMinute
    tags: tags
  }
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: take('${prefix}-operations', 260)
  location: 'global'
  properties: {
    groupShortName: 'ShopSqOps'
    enabled: true
    emailReceivers: [{
      name: 'platform-owner'
      emailAddress: ownerEmail
      useCommonAlertSchema: true
    }]
  }
  tags: tags
}

resource postgresCpuAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${prefix}-postgres-cpu-high'
  location: 'global'
  properties: {
    description: 'PostgreSQL CPU is above 70 percent for 15 minutes.'
    severity: 2
    enabled: true
    scopes: [data.outputs.postgresId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'cpu-high'
        criterionType: 'StaticThresholdCriterion'
        metricName: 'cpu_percent'
        metricNamespace: 'Microsoft.DBforPostgreSQL/flexibleServers'
        operator: 'GreaterThan'
        threshold: 70
        timeAggregation: 'Average'
      }]
    }
    actions: [{ actionGroupId: actionGroup.id }]
    autoMitigate: true
  }
  tags: tags
}

resource postgresStorageAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${prefix}-postgres-storage-high'
  location: 'global'
  properties: {
    description: 'PostgreSQL storage exceeds 80 percent.'
    severity: 1
    enabled: true
    scopes: [data.outputs.postgresId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'storage-high'
        criterionType: 'StaticThresholdCriterion'
        metricName: 'storage_percent'
        metricNamespace: 'Microsoft.DBforPostgreSQL/flexibleServers'
        operator: 'GreaterThan'
        threshold: 80
        timeAggregation: 'Average'
      }]
    }
    actions: [{ actionGroupId: actionGroup.id }]
    autoMitigate: true
  }
  tags: tags
}

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: '${prefix}-monthly-budget'
  properties: {
    amount: monthlyBudgetAmount
    category: 'Cost'
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
      endDate: '2035-12-31'
    }
    notifications: {
      Actual75: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 75
        thresholdType: 'Actual'
        contactEmails: [ownerEmail]
        contactGroups: [actionGroup.id]
      }
      Forecast100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [ownerEmail]
        contactGroups: [actionGroup.id]
      }
    }
  }
}

output publicUrl string = edge.outputs.frontDoorUrl
output outboundIpAddress string = network.outputs.outboundIpAddress
output migrationJobName string = compute.outputs.migrationJobName
output coreApiFqdn string = compute.outputs.apiFqdn
output keyVaultName string = data.outputs.vaultName
output containerRegistry string = data.outputs.registryLoginServer
output postgresHost string = data.outputs.postgresHost
output postgresReadHost string = data.outputs.readReplicaHost
output redisHost string = data.outputs.redisHost
output coreEnvironmentId string = compute.outputs.coreEnvironmentId
output vnetId string = network.outputs.vnetId
