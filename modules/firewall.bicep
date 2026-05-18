// Step 4: Azure Firewall + Route Tables (UDRs)
// Forces spoke-to-spoke traffic through the hub firewall
// Without this, VNet peering is NOT transitive

param location string = 'eastus'
param firewallSubnetId string
param spoke1VnetName string
param spoke2VnetName string

// Public IP for Azure Firewall
resource firewallPip 'Microsoft.Network/publicIPAddresses@2023-04-01' = {
  name: 'pip-azfw'
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

// Azure Firewall in the hub AzureFirewallSubnet
resource firewall 'Microsoft.Network/azureFirewalls@2023-04-01' = {
  name: 'fw-hub'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'fw-ipconfig'
        properties: {
          subnet: {
            id: firewallSubnetId
          }
          publicIPAddress: {
            id: firewallPip.id
          }
        }
      }
    ]
  }
}

// Route table for Spoke 1
// Sends traffic destined for Spoke 2 through the firewall
resource rtSpoke1 'Microsoft.Network/routeTables@2023-04-01' = {
  name: 'rt-spoke1'
  location: location
  properties: {
    routes: [
      {
        name: 'to-spoke2'
        properties: {
          addressPrefix: '10.2.0.0/16'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: firewall.properties.ipConfigurations[0].properties.privateIPAddress
        }
      }
    ]
  }
}

// Route table for Spoke 2
// Sends traffic destined for Spoke 1 through the firewall (return route)
resource rtSpoke2 'Microsoft.Network/routeTables@2023-04-01' = {
  name: 'rt-spoke2'
  location: location
  properties: {
    routes: [
      {
        name: 'to-spoke1'
        properties: {
          addressPrefix: '10.1.0.0/16'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: firewall.properties.ipConfigurations[0].properties.privateIPAddress
        }
      }
    ]
  }
}

// Associate route table with Spoke 1 workload subnet
resource spoke1Vnet 'Microsoft.Network/virtualNetworks@2023-04-01' existing = {
  name: spoke1VnetName
}

resource spoke1SubnetUpdate 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' = {
  name: 'snet-workload'
  parent: spoke1Vnet
  properties: {
    addressPrefix: '10.1.1.0/24'
    routeTable: {
      id: rtSpoke1.id
    }
  }
}

// Associate route table with Spoke 2 workload subnet
resource spoke2Vnet 'Microsoft.Network/virtualNetworks@2023-04-01' existing = {
  name: spoke2VnetName
}

resource spoke2SubnetUpdate 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' = {
  name: 'snet-workload'
  parent: spoke2Vnet
  properties: {
    addressPrefix: '10.2.1.0/24'
    routeTable: {
      id: rtSpoke2.id
    }
  }
}

output firewallPrivateIp string = firewall.properties.ipConfigurations[0].properties.privateIPAddress
output firewallName string = firewall.name
