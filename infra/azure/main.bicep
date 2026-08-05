targetScope = 'resourceGroup'

@description('Deployment name prefix; use lowercase letters, digits and hyphens.')
@minLength(3)
param prefix string = 'shopsquire-demo'
param location string = resourceGroup().location
param backendImage string
param webImage string

@secure()
param databaseUrl string
@secure()
param redisUrl string
@secure()
param jwtSigningKey string
@secure()
param celeryHmacKey string
@secure()
param auditChainSecret string
@secure()
param backupEncryptionKey string
@secure()
param merchantApiKey string
@secure()
param ownerApiKey string
@secure()
param developerApiKey string

@description('CIDRs allowed to supply forwarding headers to the internal API.')
param trustedProxyCidrs string = '10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10'
param minApiReplicas int = 1
param maxApiReplicas int = 3
param apiConcurrentRequests int = 20
param appEnv string = 'production'
@minValue(1)
param evidenceRetentionDays int = 30

var token = toLower(uniqueString(subscription().subscriptionId, resourceGroup().id, prefix))
var workspaceName = take('${prefix}-logs-${token}', 63)
var environmentName = take('${prefix}-env-${token}', 60)
var identityName = take('${prefix}-identity-${token}', 128)
var vaultName = take(replace('${prefix}-kv-${token}', '-', ''), 24)
var storageName = take('ssq${replace(prefix, '-', '')}evidence${token}', 24)
var apiName = take('${prefix}-api', 32)
var workerName = take('${prefix}-worker', 32)
var beatName = take('${prefix}-beat', 32)
var webName = take('${prefix}-web', 32)
var migrationName = take('${prefix}-migrate', 32)

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: {
    retentionInDays: 30
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
  }
}

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
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
    sku: {
      family: 'A'
      name: 'standard'
    }
  }
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

resource dbSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: databaseUrl }
}
resource redisSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'redis-url'
  properties: { value: redisUrl }
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
resource merchantKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'merchant-api-key'
  properties: { value: merchantApiKey }
}
resource ownerKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'owner-api-key'
  properties: { value: ownerApiKey }
}
resource developerKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'developer-api-key'
  properties: { value: developerApiKey }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 30
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 30
    }
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
resource blobWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, workloadIdentity.id, 'Storage Blob Data Contributor')
  scope: storage
  properties: {
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

var appIdentity = {
  type: 'UserAssigned'
  userAssignedIdentities: { '${workloadIdentity.id}': {} }
}
var runtimeSecrets = [
  { name: 'database-url', keyVaultUrl: '${vault.properties.vaultUri}secrets/database-url', identity: workloadIdentity.id }
  { name: 'redis-url', keyVaultUrl: '${vault.properties.vaultUri}secrets/redis-url', identity: workloadIdentity.id }
  { name: 'jwt-signing-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/jwt-signing-key', identity: workloadIdentity.id }
  { name: 'celery-hmac-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/celery-hmac-key', identity: workloadIdentity.id }
  { name: 'audit-chain-secret', keyVaultUrl: '${vault.properties.vaultUri}secrets/audit-chain-secret', identity: workloadIdentity.id }
  { name: 'backup-encryption-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/backup-encryption-key', identity: workloadIdentity.id }
  { name: 'merchant-api-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/merchant-api-key', identity: workloadIdentity.id }
  { name: 'owner-api-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/owner-api-key', identity: workloadIdentity.id }
  { name: 'developer-api-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/developer-api-key', identity: workloadIdentity.id }
]
var runtimeEnv = [
  { name: 'APP_ENV', value: appEnv }
  { name: 'AUTO_MIGRATE', value: '0' }
  { name: 'RUN_MIGRATIONS', value: '0' }
  { name: 'DB_MIGRATION_GUARD', value: '1' }
  { name: 'SECRETS_ALLOW_ENV_REF_IN_STRICT', value: '1' }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'DATABASE_URL_REF', value: 'env://DATABASE_URL' }
  { name: 'REDIS_URL', secretRef: 'redis-url' }
  { name: 'REDIS_URL_REF', value: 'env://REDIS_URL' }
  { name: 'CELERY_BROKER_URL', secretRef: 'redis-url' }
  { name: 'CELERY_RESULT_BACKEND', secretRef: 'redis-url' }
  { name: 'JWT_SIGNING_KEY', secretRef: 'jwt-signing-key' }
  { name: 'CELERY_HMAC_KEY', secretRef: 'celery-hmac-key' }
  { name: 'AUDIT_CHAIN_SECRET', secretRef: 'audit-chain-secret' }
  { name: 'BACKUP_ENCRYPTION_KEY', secretRef: 'backup-encryption-key' }
  { name: 'MERCHANT_API_KEY', secretRef: 'merchant-api-key' }
  { name: 'OWNER_API_KEY', secretRef: 'owner-api-key' }
  { name: 'DEVELOPER_API_KEY', secretRef: 'developer-api-key' }
  { name: 'AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE', value: 'azure_blob' }
  { name: 'OBJECT_STORAGE_PROVIDER', value: 'azure' }
  { name: 'AZURE_STORAGE_ACCOUNT_URL', value: 'https://${storage.name}.blob.${az.environment().suffixes.storage}' }
  { name: 'AZURE_STORAGE_CONTAINER', value: evidenceContainer.name }
  { name: 'PAYMENT_EXECUTION_ENABLED', value: '0' }
  { name: 'FULFILLMENT_AUTONOMOUS_SEND', value: '0' }
  { name: 'GEOIP_ALLOW_NETWORK_LOOKUP', value: '0' }
  { name: 'TRUSTED_PROXY_CIDRS', value: trustedProxyCidrs }
  { name: 'RETENTION_CLEANUP_ENABLED', value: '1' }
  { name: 'PG_ENCRYPTION_AT_REST', value: '1' }
  { name: 'DB_POOL_SIZE', value: '5' }
  { name: 'DB_POOL_MAX_OVERFLOW', value: '5' }
  { name: 'DB_POOL_TIMEOUT_SEC', value: '10' }
]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiName
  location: location
  identity: appIdentity
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
      secrets: runtimeSecrets
    }
    template: {
      containers: [{
        name: 'api'
        image: backendImage
        command: ['uvicorn']
        args: ['src.app.main:app', '--host', '0.0.0.0', '--port', '8080', '--limit-concurrency', '40', '--timeout-keep-alive', '5', '--timeout-graceful-shutdown', '30']
        env: runtimeEnv
        resources: { cpu: json('0.5'), memory: '1Gi' }
        probes: [
          { type: 'Liveness', httpGet: { path: '/healthz', port: 8080, scheme: 'HTTP' }, initialDelaySeconds: 20, periodSeconds: 20, timeoutSeconds: 5, failureThreshold: 3 }
          { type: 'Readiness', httpGet: { path: '/readyz', port: 8080, scheme: 'HTTP' }, initialDelaySeconds: 10, periodSeconds: 10, timeoutSeconds: 5, failureThreshold: 3 }
        ]
      }]
      scale: {
        minReplicas: minApiReplicas
        maxReplicas: maxApiReplicas
        rules: [{ name: 'http-concurrency', http: { metadata: { concurrentRequests: string(apiConcurrentRequests) } } }]
      }
    }
  }
  dependsOn: [vaultReader, blobWriter, dbSecret, redisSecret, jwtSecret, celerySecret, auditSecret, backupSecret, merchantKeySecret, ownerKeySecret, developerKeySecret]
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: workerName
  location: location
  identity: appIdentity
  properties: {
    managedEnvironmentId: environment.id
    configuration: { activeRevisionsMode: 'Single', secrets: runtimeSecrets }
    template: {
      containers: [{
        name: 'worker'
        image: backendImage
        command: ['celery']
        args: ['-A', 'src.app.workers.celery_app:celery_app', 'worker', '--loglevel=INFO', '--concurrency=2']
        env: runtimeEnv
        resources: { cpu: json('0.5'), memory: '1Gi' }
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [vaultReader, blobWriter]
}

resource beat 'Microsoft.App/containerApps@2024-03-01' = {
  name: beatName
  location: location
  identity: appIdentity
  properties: {
    managedEnvironmentId: environment.id
    configuration: { activeRevisionsMode: 'Single', secrets: runtimeSecrets }
    template: {
      containers: [{
        name: 'beat'
        image: backendImage
        command: ['python']
        args: ['-m', 'src.app.workers.leased_beat']
        env: runtimeEnv
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [vaultReader, blobWriter]
}

resource migrationJob 'Microsoft.App/jobs@2024-03-01' = {
  name: migrationName
  location: location
  identity: appIdentity
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: runtimeSecrets
    }
    template: {
      containers: [{
        name: 'migrate'
        image: backendImage
        command: ['alembic']
        args: ['-c', 'alembic.ini', 'upgrade', 'head']
        env: runtimeEnv
        resources: { cpu: json('0.5'), memory: '1Gi' }
      }]
    }
  }
  dependsOn: [vaultReader, dbSecret]
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: webName
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8080, transport: 'auto', allowInsecure: false }
    }
    template: {
      containers: [{
        name: 'web'
        image: webImage
        env: [{ name: 'API_UPSTREAM', value: 'https://${api.properties.configuration.ingress.fqdn}' }]
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        probes: [{ type: 'Liveness', httpGet: { path: '/healthz', port: 8080, scheme: 'HTTP' }, periodSeconds: 20, timeoutSeconds: 5 }]
      }]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [{ name: 'http-concurrency', http: { metadata: { concurrentRequests: '50' } } }]
      }
    }
  }
}

output webUrl string = 'https://${web.properties.configuration.ingress.fqdn}'
output apiInternalFqdn string = api.properties.configuration.ingress.fqdn
output migrationJobName string = migrationJob.name
output keyVaultName string = vault.name
output evidenceStorageAccount string = storage.name
