param prefix string
param location string
param logRetentionDays int = 30
param tags object = {}

var token = toLower(uniqueString(resourceGroup().id, prefix))

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: take('${prefix}-logs-${token}', 63)
  location: location
  properties: {
    retentionInDays: logRetentionDays
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
  tags: tags
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: take('${prefix}-appi-${token}', 260)
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: true
    IngestionMode: 'LogAnalytics'
  }
  tags: tags
}

output workspaceId string = workspace.id
output workspaceCustomerId string = workspace.properties.customerId
@secure()
output workspaceSharedKey string = workspace.listKeys().primarySharedKey
output appInsightsConnectionString string = insights.properties.ConnectionString
