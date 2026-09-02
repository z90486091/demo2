// ============================================================================
// main.bicep — WSOD Triage MVP (net-new, self-contained hub/spoke)
// Hub:   AFD (Premium, WAF) -> Azure Firewall (DNAT) -> App Gateway -> APIM
// Spoke: APIM backend -> Static Web App (Angular 20 PWA / NGSW)
//
// ASSUMPTIONS (flag if wrong):
// - APIM Consumption tier = pure PaaS, no VNet injection. AppGW backend pool
//   targets the APIM Consumption gateway FQDN over the public internet path;
//   AFW does NOT sit in front of APIM's control plane, only in front of AppGW.
// - TLS terminates at AFD; AFD->Firewall->AppGW->APIM hops run HTTP for MVP
//   simplicity (no cert/Key Vault plumbing). Flip to HTTPS + cert later.
// - No auth on APIM APIs (open), per your answer.
// - deployed with `az deployment sub create` (subscription-scope, creates RG)
// ============================================================================
targetScope = 'subscription'

@description('Short prefix for resource names, e.g. wsod')
param prefix string = 'wsod'

@description('Azure region for all resources')
param location string = 'eastus2'

@description('Tags applied to all resources')
param tags object = {
  project: 'wsod-triage-mvp'
  env: 'sandbox'
}

var rgName = '${prefix}-rg'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
  tags: tags
}

module network 'modules/network.bicep' = {
  name: 'network'
  scope: rg
  params: {
    prefix: prefix
    location: location
    tags: tags
  }
}

module firewall 'modules/firewall.bicep' = {
  name: 'firewall'
  scope: rg
  params: {
    prefix: prefix
    location: location
    tags: tags
    firewallSubnetId: network.outputs.firewallSubnetId
    appGwPrivateIp: network.outputs.appGwStaticPrivateIp
  }
}

module appgateway 'modules/appgateway.bicep' = {
  name: 'appgateway'
  scope: rg
  params: {
    prefix: prefix
    location: location
    tags: tags
    appGwSubnetId: network.outputs.appGwSubnetId
    appGwStaticPrivateIp: network.outputs.appGwStaticPrivateIp
    apimGatewayFqdn: apim.outputs.gatewayHostname
  }
}

module apim 'modules/apim.bicep' = {
  name: 'apim'
  scope: rg
  params: {
    prefix: prefix
    location: location
    tags: tags
    publisherEmail: 'triage-mvp@example.com'
    publisherName: 'WSOD Triage MVP'
    swaDefaultHostname: swa.outputs.defaultHostname
  }
}

module afd 'modules/afd.bicep' = {
  name: 'afd'
  scope: rg
  params: {
    prefix: prefix
    tags: tags
    originHostname: firewall.outputs.firewallPublicIpFqdn
  }
}

module swa 'modules/swa.bicep' = {
  name: 'swa'
  scope: rg
  params: {
    prefix: prefix
    location: location
    tags: tags
  }
}

output afdEndpointHostname string = afd.outputs.endpointHostname
output firewallPublicIp string = firewall.outputs.firewallPublicIpAddress
output appGwPrivateIp string = appgateway.outputs.privateIpAddress
output apimGatewayUrl string = apim.outputs.gatewayHostname
output swaDefaultHostname string = swa.outputs.defaultHostname
output apimGoodApiPath string = '/good'
output apimZeroByteApiPath string = '/zero'
