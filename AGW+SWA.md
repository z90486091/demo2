# Azure Static Web App and Application Gateway Diagnostics

## Static Web App diagnostic categories

For an Azure Static Web App, the diagnostic categories discussed were:

```text
StaticSiteHttpLogs
StaticSiteDiagnosticLogs
```

`StaticSiteHttpLogs` is used for HTTP request/response metadata, while `StaticSiteDiagnosticLogs` contains platform-related diagnostic events.

## Legacy `AzureDiagnostics` queries

The shared legacy table is:

```kql
AzureDiagnostics
```

Typical filters discussed for Static Web Apps:

```kql
AzureDiagnostics
| where ResourceProvider =~ "MICROSOFT.WEB"
| where ResourceType =~ "STATICWEBS"
| where Category in (
    "StaticSiteHttpLogs",
    "StaticSiteDiagnosticLogs"
)
```

The ARM resource type is:

```text
Microsoft.Web/staticSites
```

The `AzureDiagnostics.ResourceType` value is commonly represented as:

```text
STATICWEBS
```

Because this representation should be verified in the workspace, use:

```kql
AzureDiagnostics
| where TimeGenerated > ago(7d)
| summarize Count = count()
    by ResourceProvider, ResourceType, Category
| order by Count desc
```

Filtering by the full resource ID is generally more reliable:

```kql
AzureDiagnostics
| where ResourceId =~ "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Web/staticSites/<app-name>"
```

`=~` performs a case-insensitive exact match. The placeholders must be replaced with actual values.

## Checking Static Web App diagnostic settings

### Azure portal

1. Open the Static Web App in Azure Portal.
2. Go to **Monitoring → Diagnostic settings**.
3. Confirm that a diagnostic setting exists.
4. Verify that one or both log categories are enabled.
5. Confirm that the destination is the expected Log Analytics workspace.

### Azure CLI

```bash
az staticwebapp show \
  --name "<swa-name>" \
  --resource-group "<resource-group>" \
  --query id \
  --output tsv
```

Then list the diagnostic settings:

```bash
az monitor diagnostic-settings list \
  --resource "<swa-resource-id>" \
  --output json
```

An empty result such as:

```json
[]
```

means that no diagnostic setting is configured for the resource.

## Verifying that logs are arriving

```kql
AzureDiagnostics
| where TimeGenerated > ago(24h)
| where ResourceId =~ "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Web/staticSites/<app-name>"
| summarize Count = count() by Category
```

If resource-specific tables are being used, search by resource ID:

```kql
search *
| where TimeGenerated > ago(24h)
| where _ResourceId =~ "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Web/staticSites/<app-name>"
| summarize Count = count() by $table
```

## Resource-specific versus legacy tables

`AzureDiagnostics` is the shared legacy table. Resource-specific tables provide:

- Clearer service-specific schemas
- Less reliance on suffixes such as `_s`, `_d`, and `_g`
- Potentially better query performance
- Easier maintenance
- More predictable columns

For new diagnostic settings, resource-specific tables are generally preferred.

## Application Gateway resource-specific tables

Expected Application Gateway tables include:

```text
AGWAccessLogs
AGWFirewallLogs
AGWPerformanceLogs
```

The main table for request and response analysis is:

```text
AGWAccessLogs
```

Discover tables containing Application Gateway or Static Web App data:

```kql
search *
| where TimeGenerated > ago(24h)
| where _ResourceId has_any (
    "/providers/Microsoft.Network/applicationGateways/",
    "/providers/Microsoft.Web/staticSites/"
)
| summarize RecordCount = count() by $table
| order by RecordCount desc
```

Inspect the schema:

```kql
AGWAccessLogs
| getschema
```

For legacy logs:

```kql
AzureDiagnostics
| where Category == "ApplicationGatewayAccessLog"
| getschema
```

## Monitoring Static Web App HTTP traffic

A general legacy-table query discussed was:

```kql
AzureDiagnostics
| where TimeGenerated > ago(24h)
| where ResourceProvider =~ "MICROSOFT.WEB"
| where ResourceType =~ "STATICWEBS"
| where Category == "StaticSiteHttpLogs"
| project
    TimeGenerated,
    Resource,
    Category,
    OperationName,
    ResultType,
    ResultDescription,
    CorrelationId,
    ResourceId
| order by TimeGenerated desc
```

Because column names can vary, inspect a sample record first:

```kql
AzureDiagnostics
| where Category == "StaticSiteHttpLogs"
| take 1
```

Then inspect the table schema:

```kql
AzureDiagnostics
| getschema
```

## Investigating possible response data loss

The key comparison is:

```text
Backend response bytes received by Application Gateway
versus
Client response bytes sent by Application Gateway
```

In the legacy Application Gateway access-log schema, the commonly used fields are:

```text
serverResponseBytes_d
clientResponseBytes_d
```

Example:

```kql
let targetTime = datetime(2026-08-28 14:30:00);

AzureDiagnostics
| where Category == "ApplicationGatewayAccessLog"
| where TimeGenerated between (targetTime - 1m .. targetTime + 1m)
| extend
    BackendResponseBytes = todouble(serverResponseBytes_d),
    ClientResponseBytes = todouble(clientResponseBytes_d)
| project
    TimeGenerated,
    requestUri_s,
    httpStatus_d,
    serverStatusCode_d,
    BackendResponseBytes,
    ClientResponseBytes,
    Difference = BackendResponseBytes - ClientResponseBytes,
    IsEqual = BackendResponseBytes == ClientResponseBytes,
    transactionId_g,
    clientIP_s
| order by TimeGenerated asc
```

Interpretation:

- `IsEqual = true`: the two logged byte counts match.
- `Difference > 0`: Application Gateway received more bytes from the backend than it sent to the client.
- `Difference < 0`: the client-side count is larger; this may result from different byte-count definitions, headers, encoding, or transformations.
- `null`: the selected column names may not match the workspace schema.

For a resource-specific table, the equivalent fields may be represented by names such as:

```text
ServerResponseBytes
SentBytes
```

Check the actual schema before querying:

```kql
AGWAccessLogs
| getschema
```

## Important limitation

`StaticSiteHttpLogs` generally provides HTTP metadata, not the complete response body or a definitive response-body hash. Therefore:

- Use SWA logs to confirm the request and backend status.
- Use Application Gateway access logs to compare byte counts.
- Use Application Gateway WAF and performance logs to investigate timeouts, resets, or gateway errors.
- For conclusive proof of payload loss, capture or compare the response at both boundaries using a shared request ID and, ideally, `Content-Length` or a payload hash.

Byte counts may differ legitimately because of:

- Compression
- Chunked transfer encoding
- Headers
- Proxy transformations
- Different definitions of “response bytes” in each log type
- Caching or protocol handling

Therefore, unequal byte counts identify a request for investigation but do not alone prove data loss.
