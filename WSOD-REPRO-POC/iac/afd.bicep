// AFD Premium (needed for WAF + advanced diagnostics). Client-facing TLS
// terminates here; origin forwarding protocol is HTTP (matches Firewall
// DNAT :80 -> AppGW :80). Caching left OFF by default for MVP so cache
// behavior can be toggled deliberately during WSOD repro, not implicitly.
param prefix string
param tags object
param originHostname string

resource afdProfile 'Microsoft.Cdn/profiles@2024-09-01' = {
  name: '${prefix}-afd'
  location: 'global'
  tags: tags
  sku: {
    name: 'Premium_AzureFrontDoor'
  }
}

resource afdEndpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-09-01' = {
  parent: afdProfile
  name: '${prefix}-endpoint'
  location: 'global'
  properties: {
    enabledState: 'Enabled'
  }
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2024-09-01' = {
  parent: afdProfile
  name: 'og-firewall'
  properties: {
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
    }
    healthProbeSettings: {
      probePath: '/'
      probeRequestType: 'GET'
      probeProtocol: 'Http'
      probeIntervalInSeconds: 60
    }
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2024-09-01' = {
  parent: originGroup
  name: 'origin-firewall'
  properties: {
    hostName: originHostname
    httpPort: 80
    httpsPort: 443
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: false
  }
}

resource wafPolicy 'Microsoft.Network/frontdoorwebapplicationfirewallpolicies@2024-02-01' = {
  name: '${prefix}wafpolicy'
  location: 'global'
  tags: tags
  sku: {
    name: 'Premium_AzureFrontDoor'
  }
  properties: {
    policySettings: {
      enabledState: 'Enabled'
      mode: 'Prevention'
    }
    managedRules: {
      managedRuleSets: [
        {
          ruleSetType: 'Microsoft_DefaultRuleSet'
          ruleSetVersion: '2.1'
        }
      ]
    }
  }
}

resource securityPolicy 'Microsoft.Cdn/profiles/securityPolicies@2024-09-01' = {
  parent: afdProfile
  name: 'sp-waf'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: {
        id: wafPolicy.id
      }
      associations: [
        {
          domains: [
            {
              id: afdEndpoint.id
            }
          ]
          patternsToMatch: ['/*']
        }
      ]
    }
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  parent: afdEndpoint
  name: 'route-default'
  properties: {
    originGroup: {
      id: originGroup.id
    }
    supportedProtocols: ['Http', 'Https']
    patternsToMatch: ['/*']
    forwardingProtocol: 'HttpOnly'
    httpsRedirect: 'Enabled'
    linkToDefaultDomain: 'Enabled'
    // No cacheConfiguration block: caching stays OFF by default. Add one
    // (queryStringCachingBehavior, compressionSettings) when you deliberately
    // want to test AFD caching behavior during repro.
  }
  dependsOn: [
    origin
  ]
}

output endpointHostname string = afdEndpoint.properties.hostName
