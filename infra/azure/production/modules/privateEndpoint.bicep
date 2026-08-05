param name string
param location string
param subnetId string
param targetResourceId string
param groupId string
param privateDnsZoneId string
param tags object = {}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: name
  location: location
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [{
      name: '${name}-connection'
      properties: {
        privateLinkServiceId: targetResourceId
        groupIds: [groupId]
      }
    }]
  }
  tags: tags
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{
      name: 'default'
      properties: { privateDnsZoneId: privateDnsZoneId }
    }]
  }
}

output endpointId string = endpoint.id
