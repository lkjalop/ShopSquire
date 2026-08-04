param prefix string
param location string
param webFqdn string
param edgeEnvironmentId string
param requestRateLimitPerMinute int = 300
param tags object = {}

var token = toLower(uniqueString(resourceGroup().id, prefix))

resource profile 'Microsoft.Cdn/profiles@2024-09-01' = {
  name: take('${prefix}-afd-${token}', 260)
  location: 'global'
  sku: { name: 'Premium_AzureFrontDoor' }
  properties: { originResponseTimeoutSeconds: 60 }
  tags: tags
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-09-01' = {
  parent: profile
  name: take('${prefix}-edge-${token}', 50)
  location: 'global'
  properties: { enabledState: 'Enabled' }
  tags: tags
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2024-09-01' = {
  parent: profile
  name: 'shopsquire-web'
  properties: {
    healthProbeSettings: {
      probeIntervalInSeconds: 30
      probePath: '/healthz'
      probeProtocol: 'Https'
      probeRequestType: 'HEAD'
    }
    loadBalancingSettings: {
      additionalLatencyInMilliseconds: 50
      sampleSize: 4
      successfulSamplesRequired: 3
    }
    sessionAffinityState: 'Disabled'
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2024-09-01' = {
  parent: originGroup
  name: 'edge-container-app'
  properties: {
    enabledState: 'Enabled'
    enforceCertificateNameCheck: true
    hostName: webFqdn
    httpPort: 80
    httpsPort: 443
    originHostHeader: webFqdn
    priority: 1
    weight: 1000
    sharedPrivateLinkResource: {
      groupId: 'managedEnvironments'
      privateLink: { id: edgeEnvironmentId }
      privateLinkLocation: location
      requestMessage: 'ShopSquire Front Door private origin'
      status: 'Pending'
    }
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  parent: endpoint
  name: 'application'
  properties: {
    enabledState: 'Enabled'
    forwardingProtocol: 'HttpsOnly'
    httpsRedirect: 'Enabled'
    linkToDefaultDomain: 'Enabled'
    originGroup: { id: originGroup.id }
    patternsToMatch: ['/*']
    supportedProtocols: ['Http', 'Https']
  }
}

resource assetRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  parent: endpoint
  name: 'immutable-assets'
  properties: {
    cacheConfiguration: {
      compressionSettings: {
        contentTypesToCompress: [
          'text/css'
          'text/javascript'
          'application/javascript'
          'application/json'
          'image/svg+xml'
        ]
        isCompressionEnabled: true
      }
      queryStringCachingBehavior: 'IgnoreQueryString'
    }
    enabledState: 'Enabled'
    forwardingProtocol: 'HttpsOnly'
    httpsRedirect: 'Enabled'
    linkToDefaultDomain: 'Enabled'
    originGroup: { id: originGroup.id }
    patternsToMatch: ['/assets/*']
    supportedProtocols: ['Http', 'Https']
  }
}

resource waf 'Microsoft.Network/frontDoorWebApplicationFirewallPolicies@2024-02-01' = {
  name: take(replace('${prefix}-waf-${token}', '-', ''), 128)
  location: 'global'
  sku: { name: 'Premium_AzureFrontDoor' }
  properties: {
    policySettings: {
      enabledState: 'Enabled'
      mode: 'Prevention'
      requestBodyCheck: 'Enabled'
      customBlockResponseStatusCode: 403
    }
    customRules: {
      rules: [{
        name: 'GlobalRateLimit'
        enabledState: 'Enabled'
        priority: 100
        ruleType: 'RateLimitRule'
        rateLimitDurationInMinutes: 1
        rateLimitThreshold: requestRateLimitPerMinute
        action: 'Block'
        matchConditions: [{
          matchVariable: 'SocketAddr'
          operator: 'IPMatch'
          negateCondition: false
          matchValue: ['0.0.0.0/0', '::/0']
          transforms: []
        }]
      }]
    }
    managedRules: {
      managedRuleSets: [
        { ruleSetType: 'Microsoft_DefaultRuleSet', ruleSetVersion: '2.1' }
        { ruleSetType: 'Microsoft_BotManagerRuleSet', ruleSetVersion: '1.1' }
      ]
    }
  }
  tags: tags
}

resource securityPolicy 'Microsoft.Cdn/profiles/securityPolicies@2024-09-01' = {
  parent: profile
  name: 'shopsquire-waf'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: { id: waf.id }
      associations: [{
        domains: [{ id: endpoint.id }]
        patternsToMatch: ['/*']
      }]
    }
  }
}

output frontDoorUrl string = 'https://${endpoint.properties.hostName}'
output frontDoorProfileId string = profile.id
output frontDoorEndpointId string = endpoint.id
output wafPolicyId string = waf.id
