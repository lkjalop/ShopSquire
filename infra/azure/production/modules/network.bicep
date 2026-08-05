param prefix string
param location string
param addressSpace string = '10.40.0.0/16'
param edgeSubnetPrefix string = '10.40.0.0/23'
param coreSubnetPrefix string = '10.40.2.0/23'
param privateEndpointSubnetPrefix string = '10.40.4.0/24'
param tags object = {}

var token = toLower(uniqueString(resourceGroup().id, prefix))
var vnetName = take('${prefix}-vnet-${token}', 64)
var natName = take('${prefix}-nat-${token}', 80)
var outboundIpName = take('${prefix}-egress-${token}', 80)

resource outboundIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: outboundIpName
  location: location
  sku: { name: 'Standard' }
  zones: ['1', '2', '3']
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
  tags: tags
}

resource nat 'Microsoft.Network/natGateways@2024-05-01' = {
  name: natName
  location: location
  sku: { name: 'Standard' }
  properties: {
    idleTimeoutInMinutes: 10
    publicIpAddresses: [{ id: outboundIp.id }]
  }
  tags: tags
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: { addressPrefixes: [addressSpace] }
    subnets: [
      {
        name: 'snet-edge-aca'
        properties: {
          addressPrefix: edgeSubnetPrefix
          delegations: [{
            name: 'container-apps'
            properties: { serviceName: 'Microsoft.App/environments' }
          }]
          natGateway: { id: nat.id }
          privateEndpointNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-core-aca'
        properties: {
          addressPrefix: coreSubnetPrefix
          delegations: [{
            name: 'container-apps'
            properties: { serviceName: 'Microsoft.App/environments' }
          }]
          natGateway: { id: nat.id }
          privateEndpointNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
  tags: tags
}

output vnetId string = vnet.id
output edgeSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'snet-edge-aca')
output coreSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'snet-core-aca')
output privateEndpointSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'snet-private-endpoints')
output outboundIpAddress string = outboundIp.properties.ipAddress
