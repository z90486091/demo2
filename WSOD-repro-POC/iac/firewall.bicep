// Azure Firewall (Standard) sitting inline between AFD and App Gateway.
// AFD's origin points at the firewall's public IP; a DNAT rule forwards
// :80 to the App Gateway private frontend IP (TLS already terminated at AFD).
param prefix string
param location string
param tags object
param firewallSubnetId string
param appGwPrivateIp string

resource fwPip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${prefix}-fw-pip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: {
      domainNameLabel: '${prefix}-fw-${uniqueString(resourceGroup().id)}'
    }
  }
}

resource fwPolicy 'Microsoft.Network/firewallPolicies@2024-05-01' = {
  name: '${prefix}-fw-policy'
  location: location
  tags: tags
  properties: {
    sku: {
      tier: 'Standard'
    }
  }
}

resource dnatRuleCollectionGroup 'Microsoft.Network/firewallPolicies/ruleCollectionGroups@2024-05-01' = {
  parent: fwPolicy
  name: 'DNATRules'
  properties: {
    priority: 100
    ruleCollections: [
      {
        ruleCollectionType: 'FirewallPolicyNatRuleCollection'
        name: 'afd-to-appgw'
        priority: 100
        action: {
          type: 'Dnat'
        }
        rules: [
          {
            ruleType: 'NatRule'
            name: 'afd-to-appgw-http'
            ipProtocols: ['TCP']
            sourceAddresses: ['*']
            destinationAddresses: [fwPip.properties.ipAddress]
            destinationPorts: ['80']
            translatedAddress: appGwPrivateIp
            translatedPort: '80'
          }
        ]
      }
    ]
  }
}

resource appRuleCollectionGroup 'Microsoft.Network/firewallPolicies/ruleCollectionGroups@2024-05-01' = {
  parent: fwPolicy
  name: 'AppRules'
  properties: {
    priority: 200
    ruleCollections: [
      {
        ruleCollectionType: 'FirewallPolicyFilterRuleCollection'
        name: 'allow-apim-egress'
        priority: 100
        action: {
          type: 'Allow'
        }
        rules: [
          {
            ruleType: 'ApplicationRule'
            name: 'allow-azure-apim'
            protocols: [
              { protocolType: 'Https', port: 443 }
            ]
            sourceAddresses: ['10.20.2.0/24']
            targetFqdns: ['*.azure-api.net']
          }
        ]
      }
    ]
  }
  dependsOn: [
    dnatRuleCollectionGroup
  ]
}

resource fw 'Microsoft.Network/azureFirewalls@2024-05-01' = {
  name: '${prefix}-fw'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'AZFW_VNet'
      tier: 'Standard'
    }
    firewallPolicy: {
      id: fwPolicy.id
    }
    ipConfigurations: [
      {
        name: 'fw-ipconfig'
        properties: {
          subnet: {
            id: firewallSubnetId
          }
          publicIPAddress: {
            id: fwPip.id
          }
        }
      }
    ]
  }
}

output firewallPublicIpAddress string = fwPip.properties.ipAddress
output firewallPublicIpFqdn string = fwPip.properties.dnsSettings.fqdn
