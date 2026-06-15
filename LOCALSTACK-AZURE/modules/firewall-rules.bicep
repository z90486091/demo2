// Step 5: Firewall Network Rules
param firewallName string
param location string = 'eastus'

resource spokeToSpokeRules 'Microsoft.Network/azureFirewalls@2023-04-01' = {
  name: firewallName
  location: location
  properties: {
    networkRuleCollections: [
      {
        name: 'spoke-to-spoke'
        properties: {
          priority: 200
          action: {
            type: 'Allow'
          }
          rules: [
            {
              name: 'allow-spoke-traffic'
              protocols: ['Any']
              sourceAddresses: ['10.1.0.0/16', '10.2.0.0/16']
              destinationAddresses: ['10.1.0.0/16', '10.2.0.0/16']
              destinationPorts: ['*']
            }
          ]
        }
      }
    ]
  }
}
