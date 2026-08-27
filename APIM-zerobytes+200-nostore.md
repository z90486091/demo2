## TLDR: Consolidating — here are the two final files (policy XML + Bicep module) as plain blocks, no diff noise, since both were new files from the start.

### `policies/apim-empty-body-rewrite.xml` (new file):

```xml
<policies>
    <inbound>
        <base />
    </inbound>
    <backend>
        <base />
    </backend>
    <outbound>
        <base />
        <choose>
            <when condition="@{
                if (context.Response.StatusCode != 200) return false;
                var body = context.Response.Body?.As<string>(preserveContent: true);
                return string.IsNullOrEmpty(body);
            }">
                <!-- 502 is outside AFD's default cacheable status-code set
                     (200/203/300/301/302/404/410) — only the status is
                     rewritten, all SWA headers/payload pass through untouched -->
                <set-status code="502" reason="Bad Gateway" />
            </when>
        </choose>
    </outbound>
    <on-error>
        <base />
    </on-error>
</policies>
```
`modules/apim-policy.bicep` (new file):

```bicep
@description('Existing APIM instance')
param apimServiceName string

@description('Existing API within APIM')
param apiName string

@description('Enable the zero-byte-200-to-502 rewrite policy')
param enableEmptyBodyRewrite bool = false

resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' existing = {
  name: apimServiceName
}

resource api 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' existing = {
  parent: apim
  name: apiName
}

resource emptyBodyPolicy 'Microsoft.ApiManagement/service/apis/policies@2023-05-01-preview' = if (enableEmptyBodyRewrite) {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('./policies/apim-empty-body-rewrite.xml')
  }
}
```
`env.bicep.param` — this one is legitimately a diff, since it's an existing file each repo already has:

```diff
--- a/env.bicep.param
+++ b/env.bicep.param
@@ -12,3 +12,6 @@ param apimServiceName = 'apim-myservice-prod'
 param apiName = 'my-swa-api'
+
+// Rewrites zero-byte 200 responses from SWA to 502 to prevent AFD caching
+param enableEmptyBodyRewrite = true
```
