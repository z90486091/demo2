// Step 3: VNet Peering
// Peering is bidirectional — must configure both sides
// Gateway transit: hub allows spokes to use its VPN gateway

param hubVnetName string
param spoke1VnetName string
param spoke2VnetName string

resource hubVnet 'Microsoft.Network/virtualNetworks@2023-04-01' existing = {
  name: hubVnetName
}

resource spoke1Vnet 'Microsoft.Network/virtualNetworks@2023-04-01' existing = {
  name: spoke1VnetName
}

resource spoke2Vnet 'Microsoft.Network/virtualNetworks@2023-04-01' existing = {
  name: spoke2VnetName
}

// Hub → Spoke 1
resource hubToSpoke1 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2023-04-01' = {
  name: 'hub-to-spoke1'
  parent: hubVnet
  properties: {
    remoteVirtualNetwork: {
      id: spoke1Vnet.id
    }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: true   // Hub shares its VPN gateway with spokes
    useRemoteGateways: false
  }
}

// Spoke 1 → Hub
resource spoke1ToHub 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2023-04-01' = {
  name: 'spoke1-to-hub'
  parent: spoke1Vnet
  dependsOn: [hubToSpoke1]
  properties: {
    remoteVirtualNetwork: {
      id: hubVnet.id
    }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: false
    useRemoteGateways: true     // Spoke uses hub's VPN gateway
  }
}

// Hub → Spoke 2
resource hubToSpoke2 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2023-04-01' = {
  name: 'hub-to-spoke2'
  parent: hubVnet
  properties: {
    remoteVirtualNetwork: {
      id: spoke2Vnet.id
    }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: true
    useRemoteGateways: false
  }
}

// Spoke 2 → Hub
resource spoke2ToHub 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2023-04-01' = {
  name: 'spoke2-to-hub'
  parent: spoke2Vnet
  dependsOn: [hubToSpoke2]
  properties: {
    remoteVirtualNetwork: {
      id: hubVnet.id
    }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: false
    useRemoteGateways: true
  }
}

output hubToSpoke1PeeringName string = hubToSpoke1.name
output hubToSpoke2PeeringName string = hubToSpoke2.name
