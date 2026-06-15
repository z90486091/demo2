// Step 1: Hub Virtual Network
// Hosts shared services: firewall, VPN gateway, DNS

param location string = 'eastus'

resource hubVnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'vnet-hub'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.0.0.0/16']
    }
    subnets: [
      {
        name: 'snet-shared-services'
        properties: {
          addressPrefix: '10.0.1.0/24'
        }
      }
      {
        // Azure Firewall requires this exact name
        name: 'AzureFirewallSubnet'
        properties: {
          addressPrefix: '10.0.2.0/24'
        }
      }
      {
        // VPN Gateway requires this exact name
        name: 'GatewaySubnet'
        properties: {
          addressPrefix: '10.0.3.0/27'
        }
      }
    ]
  }
}

output hubVnetId string = hubVnet.id
output hubVnetName string = hubVnet.name
output firewallSubnetId string = hubVnet.properties.subnets[1].id
