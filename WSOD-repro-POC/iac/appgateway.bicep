// App Gateway Standard_v2. Listens HTTP:80 on a static private frontend IP
// (reached via Firewall DNAT). Backend pool = APIM Consumption gateway FQDN
// over HTTPS with hostname override (APIM requires SNI match).
// NOTE: v2 SKU still requires a public frontend IP config to provision even
// when unused for traffic — it is not attached to any listener here.
param prefix string
param location string
param tags object
param appGwSubnetId string
param appGwStaticPrivateIp string
param apimGatewayFqdn string

resource appGwPip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${prefix}-agw-pip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource appGw 'Microsoft.Network/applicationGateways@2024-05-01' = {
  name: '${prefix}-agw'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'Standard_v2'
      tier: 'Standard_v2'
    }
    autoscaleConfiguration: {
      minCapacity: 0
      maxCapacity: 2
    }
    gatewayIPConfigurations: [
      {
        name: 'gw-ipconfig'
        properties: {
          subnet: {
            id: appGwSubnetId
          }
        }
      }
    ]
    frontendIPConfigurations: [
      {
        name: 'private-fe'
        properties: {
          privateIPAllocationMethod: 'Static'
          privateIPAddress: appGwStaticPrivateIp
          subnet: {
            id: appGwSubnetId
          }
        }
      }
      {
        name: 'public-fe'
        properties: {
          publicIPAddress: {
            id: appGwPip.id
          }
        }
      }
    ]
    frontendPorts: [
      {
        name: 'port-80'
        properties: {
          port: 80
        }
      }
    ]
    backendAddressPools: [
      {
        name: 'apim-pool'
        properties: {
          backendAddresses: [
            {
              fqdn: apimGatewayFqdn
            }
          ]
        }
      }
    ]
    backendHttpSettingsCollection: [
      {
        name: 'apim-https-settings'
        properties: {
          port: 443
          protocol: 'Https'
          cookieBasedAffinity: 'Disabled'
          pickHostNameFromBackendAddress: true
          requestTimeout: 30
          probe: {
            id: resourceId('Microsoft.Network/applicationGateways/probes', '${prefix}-agw', 'apim-probe')
          }
        }
      }
    ]
    probes: [
      {
        name: 'apim-probe'
        properties: {
          protocol: 'Https'
          path: '/status-0123456789abcdef'
          interval: 30
          timeout: 30
          unhealthyThreshold: 3
          pickHostNameFromBackendHttpSettings: true
        }
      }
    ]
    httpListeners: [
      {
        name: 'http-listener'
        properties: {
          frontendIPConfiguration: {
            id: resourceId('Microsoft.Network/applicationGateways/frontendIPConfigurations', '${prefix}-agw', 'private-fe')
          }
          frontendPort: {
            id: resourceId('Microsoft.Network/applicationGateways/frontendPorts', '${prefix}-agw', 'port-80')
          }
          protocol: 'Http'
        }
      }
    ]
    requestRoutingRules: [
      {
        name: 'apim-routing-rule'
        properties: {
          ruleType: 'Basic'
          priority: 100
          httpListener: {
            id: resourceId('Microsoft.Network/applicationGateways/httpListeners', '${prefix}-agw', 'http-listener')
          }
          backendAddressPool: {
            id: resourceId('Microsoft.Network/applicationGateways/backendAddressPools', '${prefix}-agw', 'apim-pool')
          }
          backendHttpSettings: {
            id: resourceId('Microsoft.Network/applicationGateways/backendHttpSettingsCollection', '${prefix}-agw', 'apim-https-settings')
          }
        }
      }
    ]
  }
}

output privateIpAddress string = appGwStaticPrivateIp
output appGwId string = appGw.id
