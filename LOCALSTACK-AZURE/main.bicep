targetScope = 'resourceGroup'

param location string = 'eastus'

module hub 'modules/hub.bicep' = {
  name: 'deploy-hub'
  params: {
    location: location
  }
}

module spokes 'modules/spokes.bicep' = {
  name: 'deploy-spokes'
  params: {
    location: location
  }
}

module peering 'modules/peering.bicep' = {
  name: 'deploy-peering'
  params: {
    hubVnetName: hub.outputs.hubVnetName
    spoke1VnetName: spokes.outputs.spoke1VnetName
    spoke2VnetName: spokes.outputs.spoke2VnetName
  }
}

module firewall 'modules/firewall.bicep' = {
  name: 'deploy-firewall'
  dependsOn: [peering]
  params: {
    location: location
    firewallSubnetId: hub.outputs.firewallSubnetId
    spoke1VnetName: spokes.outputs.spoke1VnetName
    spoke2VnetName: spokes.outputs.spoke2VnetName
  }
}

module firewallRules 'modules/firewall-rules.bicep' = {
  name: 'deploy-firewall-rules'
  dependsOn: [firewall]
  params: {
    firewallName: firewall.outputs.firewallName
    location: location
  }
}

output hubVnetId string = hub.outputs.hubVnetId
output spoke1VnetId string = spokes.outputs.spoke1VnetId
output spoke2VnetId string = spokes.outputs.spoke2VnetId
output firewallPrivateIp string = firewall.outputs.firewallPrivateIp
