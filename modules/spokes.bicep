// Step 2: Spoke Virtual Networks
// Each spoke is an isolated workload environment

param location string = 'eastus'

resource spoke1Vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'vnet-spoke-1'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.1.0.0/16']
    }
    subnets: [
      {
        name: 'snet-workload'
        properties: {
          addressPrefix: '10.1.1.0/24'
        }
      }
    ]
  }
}

resource spoke2Vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'vnet-spoke-2'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.2.0.0/16']
    }
    subnets: [
      {
        name: 'snet-workload'
        properties: {
          addressPrefix: '10.2.1.0/24'
        }
      }
    ]
  }
}

output spoke1VnetId string = spoke1Vnet.id
output spoke1VnetName string = spoke1Vnet.name
output spoke2VnetId string = spoke2Vnet.id
output spoke2VnetName string = spoke2Vnet.name
