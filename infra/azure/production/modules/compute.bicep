param prefix string
param location string
param edgeSubnetId string
param coreSubnetId string
param workspaceCustomerId string
@secure()
param workspaceSharedKey string
param appInsightsConnectionString string
param identityId string
param identityClientId string
param vaultUri string
param storageName string
param evidenceContainerName string
param redisHost string
param redisPort int = 10000
param backendImage string
param webImage string
param registryServer string
param minWebReplicas int = 2
param maxWebReplicas int = 10
param minApiReplicas int = 2
param maxApiReplicas int = 10
param maxWorkerReplicas int = 10
param apiConcurrentRequests int = 20
param webConcurrentRequests int = 50
param tags object = {}

var token = toLower(uniqueString(resourceGroup().id, prefix))
var edgeEnvironmentName = take('${prefix}-edge-${token}', 60)
var coreEnvironmentName = take('${prefix}-core-${token}', 60)
var apiName = take('${prefix}-api', 32)
var webName = take('${prefix}-web', 32)
var workerName = take('${prefix}-worker', 32)
var beatName = take('${prefix}-beat', 32)
var migrationName = take('${prefix}-migrate', 32)

resource edgeEnvironment 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: edgeEnvironmentName
  location: location
  properties: {
    publicNetworkAccess: 'Disabled'
    zoneRedundant: true
    vnetConfiguration: {
      infrastructureSubnetId: edgeSubnetId
      internal: true
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspaceCustomerId
        sharedKey: workspaceSharedKey
      }
    }
  }
  tags: tags
}

resource coreEnvironment 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: coreEnvironmentName
  location: location
  properties: {
    publicNetworkAccess: 'Disabled'
    zoneRedundant: true
    vnetConfiguration: {
      infrastructureSubnetId: coreSubnetId
      internal: true
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspaceCustomerId
        sharedKey: workspaceSharedKey
      }
    }
  }
  tags: tags
}

var appIdentity = {
  type: 'UserAssigned'
  userAssignedIdentities: { '${identityId}': {} }
}

var runtimeSecrets = [
  { name: 'database-url', keyVaultUrl: '${vaultUri}secrets/database-url', identity: identityId }
  { name: 'database-read-url', keyVaultUrl: '${vaultUri}secrets/database-read-url', identity: identityId }
  { name: 'redis-url', keyVaultUrl: '${vaultUri}secrets/redis-url', identity: identityId }
  { name: 'redis-password', keyVaultUrl: '${vaultUri}secrets/redis-password', identity: identityId }
  { name: 'jwt-signing-key', keyVaultUrl: '${vaultUri}secrets/jwt-signing-key', identity: identityId }
  { name: 'celery-hmac-key', keyVaultUrl: '${vaultUri}secrets/celery-hmac-key', identity: identityId }
  { name: 'audit-chain-secret', keyVaultUrl: '${vaultUri}secrets/audit-chain-secret', identity: identityId }
  { name: 'backup-encryption-key', keyVaultUrl: '${vaultUri}secrets/backup-encryption-key', identity: identityId }
  { name: 'merchant-api-key', keyVaultUrl: '${vaultUri}secrets/merchant-api-key', identity: identityId }
  { name: 'owner-api-key', keyVaultUrl: '${vaultUri}secrets/owner-api-key', identity: identityId }
  { name: 'developer-api-key', keyVaultUrl: '${vaultUri}secrets/developer-api-key', identity: identityId }
]

var runtimeEnv = [
  { name: 'APP_ENV', value: 'production' }
  { name: 'AUTO_MIGRATE', value: '0' }
  { name: 'RUN_MIGRATIONS', value: '0' }
  { name: 'DB_MIGRATION_GUARD', value: '1' }
  { name: 'SECRETS_ALLOW_ENV_REF_IN_STRICT', value: '1' }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'DATABASE_READ_URL', secretRef: 'database-read-url' }
  { name: 'DATABASE_URL_REF', value: 'env://DATABASE_URL' }
  { name: 'REDIS_URL', secretRef: 'redis-url' }
  { name: 'REDIS_URL_REF', value: 'env://REDIS_URL' }
  { name: 'REDIS_ACL_USERNAME', value: 'default' }
  { name: 'REDIS_ACL_PASSWORD', secretRef: 'redis-password' }
  { name: 'CELERY_BROKER_URL', secretRef: 'redis-url' }
  { name: 'CELERY_RESULT_BACKEND', secretRef: 'redis-url' }
  { name: 'JWT_SIGNING_KEY', secretRef: 'jwt-signing-key' }
  { name: 'CELERY_HMAC_KEY', secretRef: 'celery-hmac-key' }
  { name: 'AUDIT_CHAIN_SECRET', secretRef: 'audit-chain-secret' }
  { name: 'BACKUP_ENCRYPTION_KEY', secretRef: 'backup-encryption-key' }
  { name: 'MERCHANT_API_KEY', secretRef: 'merchant-api-key' }
  { name: 'OWNER_API_KEY', secretRef: 'owner-api-key' }
  { name: 'DEVELOPER_API_KEY', secretRef: 'developer-api-key' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
  { name: 'AZURE_CLIENT_ID', value: identityClientId }
  { name: 'AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE', value: 'azure_blob' }
  { name: 'OBJECT_STORAGE_PROVIDER', value: 'azure' }
  { name: 'AZURE_STORAGE_ACCOUNT_URL', value: 'https://${storageName}.blob.${az.environment().suffixes.storage}' }
  { name: 'AZURE_STORAGE_CONTAINER', value: evidenceContainerName }
  { name: 'RETURN_EVIDENCE_STORAGE_PROVIDER', value: 'azure_blob' }
  { name: 'RETURN_EVIDENCE_AZURE_CONTAINER', value: evidenceContainerName }
  { name: 'RETURN_EVIDENCE_KEY_PROVIDER', value: 'azure_key_vault' }
  { name: 'RETURN_EVIDENCE_KEY_VAULT_URL', value: vaultUri }
  { name: 'RETURN_EVIDENCE_ACTIVE_KEY_ID', value: 'v1' }
  { name: 'RETURN_EVIDENCE_KEY_IDS', value: 'v1' }
  { name: 'PAYMENT_EXECUTION_ENABLED', value: '0' }
  { name: 'FULFILLMENT_AUTONOMOUS_SEND', value: '0' }
  { name: 'GEOIP_ALLOW_NETWORK_LOOKUP', value: '0' }
  { name: 'TRUSTED_PROXY_CIDRS', value: '10.40.0.0/16' }
  { name: 'RETENTION_CLEANUP_ENABLED', value: '1' }
  { name: 'PG_ENCRYPTION_AT_REST', value: '1' }
  { name: 'DB_POOL_SIZE', value: '5' }
  { name: 'DB_POOL_MAX_OVERFLOW', value: '5' }
  { name: 'DB_POOL_TIMEOUT_SEC', value: '10' }
  { name: 'DB_CONNECT_TIMEOUT_SEC', value: '5' }
]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiName
  location: location
  identity: appIdentity
  properties: {
    managedEnvironmentId: coreEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
      secrets: runtimeSecrets
      registries: [{
        server: registryServer
        identity: identityId
      }]
    }
    template: {
      containers: [{
        name: 'api'
        image: backendImage
        command: ['uvicorn']
        args: ['src.app.main:app', '--host', '0.0.0.0', '--port', '8080', '--limit-concurrency', '40', '--timeout-keep-alive', '5', '--timeout-graceful-shutdown', '30']
        env: runtimeEnv
        resources: { cpu: json('1.0'), memory: '2Gi' }
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
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: workerName
  location: location
  identity: appIdentity
  properties: {
    managedEnvironmentId: coreEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: runtimeSecrets
      registries: [{
        server: registryServer
        identity: identityId
      }]
    }
    template: {
      containers: [{
        name: 'worker'
        image: backendImage
        command: ['celery']
        args: ['-A', 'src.app.workers.celery_app:celery_app', 'worker', '--loglevel=INFO', '--concurrency=2']
        env: runtimeEnv
        resources: { cpu: json('1.0'), memory: '2Gi' }
      }]
      scale: {
        minReplicas: 1
        maxReplicas: maxWorkerReplicas
        rules: [{
          name: 'celery-queue-depth'
          custom: {
            type: 'redis'
            metadata: {
              address: '${redisHost}:${redisPort}'
              listName: 'celery'
              listLength: '10'
              enableTLS: 'true'
            }
            auth: [{
              secretRef: 'redis-password'
              triggerParameter: 'password'
            }]
          }
        }]
      }
    }
  }
}

resource beat 'Microsoft.App/containerApps@2024-03-01' = {
  name: beatName
  location: location
  identity: appIdentity
  properties: {
    managedEnvironmentId: coreEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: runtimeSecrets
      registries: [{ server: registryServer, identity: identityId }]
    }
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
}

resource migrationJob 'Microsoft.App/jobs@2024-03-01' = {
  name: migrationName
  location: location
  identity: appIdentity
  properties: {
    environmentId: coreEnvironment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: runtimeSecrets
      registries: [{
        server: registryServer
        identity: identityId
      }]
    }
    template: {
      containers: [{
        name: 'migrate'
        image: backendImage
        command: ['alembic']
        args: ['-c', 'alembic.ini', 'upgrade', 'head']
        env: runtimeEnv
        resources: { cpu: json('1.0'), memory: '2Gi' }
      }]
    }
  }
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: webName
  location: location
  identity: appIdentity
  properties: {
    managedEnvironmentId: edgeEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{
        server: registryServer
        identity: identityId
      }]
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [{
        name: 'web'
        image: webImage
        env: [{ name: 'API_UPSTREAM', value: 'https://${api.properties.configuration.ingress.fqdn}' }]
        resources: { cpu: json('0.5'), memory: '1Gi' }
        probes: [
          { type: 'Liveness', httpGet: { path: '/healthz', port: 8080, scheme: 'HTTP' }, periodSeconds: 20, timeoutSeconds: 5 }
          { type: 'Readiness', httpGet: { path: '/healthz', port: 8080, scheme: 'HTTP' }, periodSeconds: 10, timeoutSeconds: 5 }
        ]
      }]
      scale: {
        minReplicas: minWebReplicas
        maxReplicas: maxWebReplicas
        rules: [{ name: 'http-concurrency', http: { metadata: { concurrentRequests: string(webConcurrentRequests) } } }]
      }
    }
  }
}

output edgeEnvironmentId string = edgeEnvironment.id
output coreEnvironmentId string = coreEnvironment.id
output webFqdn string = web.properties.configuration.ingress.fqdn
output apiFqdn string = api.properties.configuration.ingress.fqdn
output migrationJobName string = migrationJob.name
output apiId string = api.id
output webId string = web.id
output workerId string = worker.id
