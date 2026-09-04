// Spoke: Static Web App hosting the Angular 20 PWA (NGSW). Standard tier
// (not Free) so custom domains / private endpoints can be added later
// without re-provisioning. Deploy source is out-of-band (GH Actions / SWA CLI) —
// this module only provisions the resource.
param prefix string
param location string
param tags object

resource swa 'Microsoft.Web/staticSites@2024-04-01' = {
  name: '${prefix}-swa'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    buildProperties: {
      skipGithubActionWorkflowGeneration: true
    }
  }
}

output defaultHostname string = swa.properties.defaultHostname
output swaName string = swa.name
