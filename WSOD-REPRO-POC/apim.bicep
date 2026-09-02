// APIM Consumption tier (serverless, no VNet injection).
// API 1 "/good"  -> passthrough backend to the SWA default hostname.
// API 2 "/zero"  -> mock policy, always HTTP 200 with an empty (0-byte) body.
//                   Used to isolate whether zero-byte-200s originate upstream
//                   of APIM (AFD/FW/AGW caching/mangling) vs. downstream (SWA).
param prefix string
param location string
param tags object
param publisherEmail string
param publisherName string
param swaDefaultHostname string

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: '${prefix}-apim-${uniqueString(resourceGroup().id)}'
  location: location
  tags: tags
  sku: {
    name: 'Consumption'
    capacity: 0
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource goodApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'good-api'
  properties: {
    displayName: 'Good API (passthrough to SWA)'
    path: 'good'
    protocols: ['https']
    subscriptionRequired: false
    serviceUrl: 'https://${swaDefaultHostname}'
  }
}

resource goodApiOperation 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: goodApi
  name: 'passthrough-all'
  properties: {
    displayName: 'Passthrough all'
    method: 'GET'
    urlTemplate: '/*'
  }
}

resource zeroApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'zero-byte-api'
  properties: {
    displayName: 'Zero-byte 200 (mock)'
    path: 'zero'
    protocols: ['https']
    subscriptionRequired: false
    serviceUrl: 'https://example.invalid'
  }
}

resource zeroApiOperation 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: zeroApi
  name: 'always-200-empty'
  properties: {
    displayName: 'Always 200, empty body'
    method: 'GET'
    urlTemplate: '/*'
  }
}

resource zeroApiOperationPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-05-01' = {
  parent: zeroApiOperation
  name: 'policy'
  properties: {
    format: 'xml'
    value: '''
<policies>
  <inbound>
    <base />
    <return-response>
      <set-status code="200" reason="OK" />
      <set-header name="Content-Length" exists-action="override">
        <value>0</value>
      </set-header>
      <set-body>@("")</set-body>
    </return-response>
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
'''
  }
}

output gatewayHostname string = replace(replace(apim.properties.gatewayUrl, 'https://', ''), '/', '')
