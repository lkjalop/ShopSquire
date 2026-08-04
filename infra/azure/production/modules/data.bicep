@minLength(3)
param prefix string
param location string
param vnetId string
param privateEndpointSubnetId string
param postgresAdminLogin string = 'shopsquire_admin'
@secure()
param postgresAdminPassword string
param postgresSkuName string = 'Standard_D2ds_v5'
param postgresStorageGb int = 128
param postgresBackupRetentionDays int = 14
param enablePostgresHa bool = true
param enableReadReplica bool = false
param redisSkuName string = 'Balanced_B0'
@minLength(5)
@maxLength(50)
param registryName string
param evidenceRetentionDays int = 30
param tags object = {}

var token = toLower(uniqueString(subscription().subscriptionId, resourceGroup().id, prefix))
var postgresName = take('${prefix}-pg-${token}', 63)
var replicaName = take('${prefix}-pgr-${token}', 63)
var redisName = take('${prefix}-redis-${token}', 60)
var vaultName = take(replace('${prefix}-kv-${token}', '-', ''), 24)
var storageName = take('ssq${replace(prefix, '-', '')}${token}', 24)

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresName
  location: location
  sku: {
    name: postgresSkuName
    tier: 'GeneralPurpose'
  }
  properties: {
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    version: '16'
    availabilityZone: '1'
    network: {
      publicNetworkAccess: 'Disabled'
    }
    highAvailability: {
      mode: enablePostgresHa ? 'ZoneRedundant' : 'Disabled'
      standbyAvailabilityZone: enablePostgresHa ? '2' : null
    }
    storage: {
      storageSizeGB: postgresStorageGb
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: postgresBackupRetentionDays
      geoRedundantBackup: 'Disabled'
    }
    maintenanceWindow: {
      customWindow: 'Enabled'
      dayOfWeek: 0
      startHour: 16
      startMinute: 0
    }
  }
  tags: tags
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'shopsquire'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource readReplica 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = if (enableReadReplica) {
  name: replicaName
  location: location
  sku: {
    name: postgresSkuName
    tier: 'GeneralPurpose'
  }
  properties: {
    createMode: 'Replica'
    sourceServerResourceId: postgres.id
    version: '16'
    network: {
      publicNetworkAccess: 'Disabled'
    }
  }
  tags: tags
}

resource redis 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: redisName
  location: location
  sku: { name: redisSkuName }
  properties: {
    encryption: {}
    highAvailability: 'Enabled'
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
  }
  tags: tags
}

resource redisDatabase 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: redis
  name: 'default'
  properties: {
    accessKeysAuthentication: 'Enabled'
    clientProtocol: 'Encrypted'
    clusteringPolicy: 'OSSCluster'
    evictionPolicy: 'VolatileLRU'
    modules: []
    port: 10000
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: vaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 30
    publicNetworkAccess: 'Disabled'
    sku: { family: 'A', name: 'standard' }
  }
  tags: tags
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_ZRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
    }
  }
  tags: tags
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 30 }
    containerDeleteRetentionPolicy: { enabled: true, days: 30 }
  }
}

resource evidenceContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'evidence'
  properties: { publicAccess: 'None' }
}

resource evidenceImmutability 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2023-05-01' = {
  parent: evidenceContainer
  name: 'default'
  properties: {
    allowProtectedAppendWrites: false
    immutabilityPeriodSinceCreationInDays: evidenceRetentionDays
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: { name: 'Premium' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Disabled'
    policies: {
      retentionPolicy: { days: 30, status: 'enabled' }
      quarantinePolicy: { status: 'enabled' }
      trustPolicy: { type: 'Notary', status: 'disabled' }
    }
  }
  tags: tags
}

var zones = [
  { name: 'postgres', zone: 'privatelink.postgres.database.azure.com' }
  { name: 'redis', zone: 'privatelink.redis.azure.net' }
  { name: 'vault', zone: 'privatelink.vaultcore.azure.net' }
  { name: 'blob', zone: 'privatelink.blob.${az.environment().suffixes.storage}' }
  { name: 'registry', zone: 'privatelink.azurecr.io' }
]

resource privateZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for item in zones: {
  name: item.zone
  location: 'global'
  tags: tags
}]

resource zoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (item, i) in zones: {
  parent: privateZones[i]
  name: '${prefix}-${item.name}-vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnetId }
  }
}]

module postgresEndpoint 'privateEndpoint.bicep' = {
  name: '${prefix}-postgres-private-endpoint'
  params: {
    name: take('${prefix}-pe-postgres', 80)
    location: location
    subnetId: privateEndpointSubnetId
    targetResourceId: postgres.id
    groupId: 'postgresqlServer'
    privateDnsZoneId: privateZones[0].id
    tags: tags
  }
}

module replicaEndpoint 'privateEndpoint.bicep' = if (enableReadReplica) {
  name: '${prefix}-replica-private-endpoint'
  params: {
    name: take('${prefix}-pe-pg-replica', 80)
    location: location
    subnetId: privateEndpointSubnetId
    targetResourceId: readReplica.id
    groupId: 'postgresqlServer'
    privateDnsZoneId: privateZones[0].id
    tags: tags
  }
}

module redisEndpoint 'privateEndpoint.bicep' = {
  name: '${prefix}-redis-private-endpoint'
  params: {
    name: take('${prefix}-pe-redis', 80)
    location: location
    subnetId: privateEndpointSubnetId
    targetResourceId: redis.id
    groupId: 'redisEnterprise'
    privateDnsZoneId: privateZones[1].id
    tags: tags
  }
}

module vaultEndpoint 'privateEndpoint.bicep' = {
  name: '${prefix}-vault-private-endpoint'
  params: {
    name: take('${prefix}-pe-vault', 80)
    location: location
    subnetId: privateEndpointSubnetId
    targetResourceId: vault.id
    groupId: 'vault'
    privateDnsZoneId: privateZones[2].id
    tags: tags
  }
}

module blobEndpoint 'privateEndpoint.bicep' = {
  name: '${prefix}-blob-private-endpoint'
  params: {
    name: take('${prefix}-pe-blob', 80)
    location: location
    subnetId: privateEndpointSubnetId
    targetResourceId: storage.id
    groupId: 'blob'
    privateDnsZoneId: privateZones[3].id
    tags: tags
  }
}

module registryEndpoint 'privateEndpoint.bicep' = {
  name: '${prefix}-registry-private-endpoint'
  params: {
    name: take('${prefix}-pe-registry', 80)
    location: location
    subnetId: privateEndpointSubnetId
    targetResourceId: registry.id
    groupId: 'registry'
    privateDnsZoneId: privateZones[4].id
    tags: tags
  }
}

output postgresId string = postgres.id
output postgresHost string = '${postgres.name}.postgres.database.azure.com'
output postgresDatabase string = database.name
output readReplicaHost string = enableReadReplica ? '${readReplica.name}.postgres.database.azure.com' : ''
output redisId string = redis.id
output redisHost string = '${redis.name}.${location}.redis.azure.net'
output redisPort int = redisDatabase.properties.port
@secure()
output redisPrimaryKey string = redisDatabase.listKeys().primaryKey
output vaultId string = vault.id
output vaultName string = vault.name
output vaultUri string = vault.properties.vaultUri
output storageId string = storage.id
output storageName string = storage.name
output evidenceContainerName string = evidenceContainer.name
output registryId string = registry.id
output registryName string = registry.name
output registryLoginServer string = registry.properties.loginServer
output readReplicaId string = enableReadReplica ? readReplica.id : ''
