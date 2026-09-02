// Net-new VNet: AzureFirewallSubnet (required exact name) + AppGatewaySubnet
param prefix string
param location string
param tags object

var vnetAddressSpace = '10.20.0.0/16'
var firewallSubnetPrefix = '10.20.1.0/26'
var appGwSubnetPrefix = '10.20.2.0/24'

// Deterministic static IP for AppGW's private frontend so the Firewall
// module can reference it for DNAT without a circular module dependency.
var appGwStaticPrivateIp = '10.20.2.4'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${prefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [vnetAddressSpace]
    }
    subnets: [
      {
        name: 'AzureFirewallSubnet'
        properties: {
          addressPrefix: firewallSubnetPrefix
        }
      }
      {
        name: 'AppGatewaySubnet'
        properties: {
          addressPrefix: appGwSubnetPrefix
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output firewallSubnetId string = vnet.properties.subnets[0].id
output appGwSubnetId string = vnet.properties.subnets[1].id
output appGwStaticPrivateIp string = appGwStaticPrivateIp
