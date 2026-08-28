Below are ready‑to‑paste Kusto Query Language (KQL) snippets you can run in **Log Analytics** (or Azure Monitor → Logs) to follow a single request by the **`trace‑id`** that appears in the `traceparent` header.

All Azure services that emit HTTP diagnostics write the header value into the **`TraceParent`** column (or, when the column is not present, into a generic **`properties_*`** field). The query pattern is the same for each service – filter on the 32‑character trace‑id, then project the columns you need.

> **Important:** The trace‑id is the middle segment of the `traceparent` header  
> `traceparent: 00‑<trace‑id>‑<span‑id>‑01`  
> Example: `00‑4bf92f3577b34da6a3ce929d0e0e4736‑00f067aa0ba902b7‑01` → **trace‑id = `4bf92f3577b34da6a3ce929d0e0e4736`**.

---

## 1️⃣ Front Door

```kusto
FrontDoorAccessLogs
| where TimeGenerated > ago(24h)                     // adjust window as needed
| where isnotempty(TraceParent)                      // column name in Front‑Door logs
| where extract(@"00-([0-9a-f]{32})-", 1, TraceParent) == "<YOUR_TRACE_ID>"
| project
    TimeGenerated,
    RequestUri,
    HttpStatus,
    ClientIp_s,
    BackendHost_s,
    TraceParent,
    RequestId_s     // Front Door’s native request identifier
| order by TimeGenerated asc
```

*If the table is `AzureDiagnostics` for Front Door, replace `FrontDoorAccessLogs` with `AzureDiagnostics` and add `ResourceProvider == "MICROSOFT.CDN"` and `Category == "FrontDoorAccessLog"`.*

---

## 2️⃣ Azure Firewall

Azure Firewall does not log the `traceparent` header by default.  
If you have **Application Rules** with **HTTP logging enabled**, the header appears in the `properties_s` bag:

```kusto
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.NETWORK"
| where Category == "AzureFirewallApplicationRuleLog"
| where isnotempty(properties_s)
| extend traceparent = tostring(parse_json(properties_s).traceparent)
| where isnotempty(traceparent)
| where extract(@"00-([0-9a-f]{32})-", 1, traceparent) == "<YOUR_TRACE_ID>"
| project
    TimeGenerated,
    RuleName,
    SourceIp_s,
    DestinationIp_s,
    DestinationPort_s,
    traceparent,
    Action_s
| order by TimeGenerated asc
```

*If you are only using Network‑Rule logs, the header isn’t captured; you would need to enable **HTTP‑Inspection** rules to see it.*

---

## 3️⃣ Application Gateway

```kusto
AGWAccessLogs
| where TimeGenerated > ago(24h)
| where isnotempty(TraceParent)                     // column appears in recent AGW schema
| where extract(@"00-([0-9a-f]{32})-", 1, TraceParent) == "<YOUR_TRACE_ID>"
| project
    TimeGenerated,
    TransactionId,          // same as x‑appgw‑trace‑id
    RequestUri_s,
    HttpMethod_s,
    HttpStatus_d,
    ClientIP_s,
    BackendPoolName_s,
    BackendSettingName_s,
    TimeTaken_d,
    TraceParent
| order by TimeGenerated asc
```

*If you are still using the legacy `AzureDiagnostics` table:*

```kusto
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.NETWORK"
| where Category == "ApplicationGatewayAccessLog"
| where isnotempty(properties_s)
| extend traceparent = tostring(parse_json(properties_s).traceparent)
| where extract(@"00-([0-9a-f]{32})-", 1, traceparent) == "<YOUR_TRACE_ID>"
| project
    TimeGenerated,
    transactionId_g,
    requestUri_s,
    httpMethod_s,
    httpStatus_d,
    clientIP_s,
    TraceParent = traceparent
| order by TimeGenerated asc
```

---

## 4️⃣ API Management (APIM)

```kusto
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.API MANAGEMENT"
| where Category == "GatewayLogs"
| where isnotempty(TraceParent)
| where extract(@"00-([0-9a-f]{32})-", 1, TraceParent) == "<YOUR_TRACE_ID>"
| project
    TimeGenerated,
    requestId_s,             // APIM’s native request‑id
    operationName_s,
    HttpMethod_s,
    HttpStatusCode_d,
    clientIp_s,
    backendUrl_s,
    TraceParent,
    SpanId_s                 // optional, if you want the APIM span
| order by TimeGenerated asc
```

*If you have Application Insights enabled for APIM, you can also query `requests` table:*

```kusto
requests
| where isnotempty(traceParent)
| where extract(@"00-([0-9a-f]{32})-", 1, traceParent) == "<YOUR_TRACE_ID>"
| project
    timestamp,
    name,
    resultCode,
    duration,
    client_IP,
    operation_Name,
    traceParent,
    operation_Id          // same as trace‑id in AI
| order by timestamp asc
```

---

## 5️⃣ Static Web Apps (SWA) / Backend API

SWA itself does not emit a dedicated `traceparent` column, but **if the backend API is instrumented with Application Insights** (or sends its own logs to a Log‑Analytics workspace) the header arrives unchanged.

### a) Backend API logs (App Insights `requests`)

```kusto
requests
| where isnotempty(traceParent)
| where extract(@"00-([0-9a-f]{32})-", 1, traceParent) == "<YOUR_TRACE_ID>"
| project
    timestamp,
    name,
    resultCode,
    duration,
    client_IP,
    operation_Name,
    traceParent,
    operation_Id
| order by timestamp asc
```

### b) SWA AzureDiagnostics (if you have “Static Web Apps” diagnostics enabled)

```kusto
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.WEB"
| where Category == "StaticWebAppsAccessLog"
| where isnotempty(TraceParent)
| where extract(@"00-([0-9a-f]{32})-", 1, TraceParent) == "<YOUR_TRACE_ID>"
| project
    TimeGenerated,
    requestUri_s,
    httpMethod_s,
    httpStatus_d,
    clientIp_s,
    TraceParent
| order by TimeGenerated asc
```

---

## 6️⃣ Putting it all together – a **single “trace‑timeline”** query

If all logs are in the **same Log‑Analytics workspace**, you can union them to see the full end‑to‑end flow:

```kusto
let traceId = "<YOUR_TRACE_ID>";

let frontDoor = FrontDoorAccessLogs
| where isnotempty(TraceParent)
| where extract(@"00-([0-9a-f]{32})-", 1, TraceParent) == traceId
| project TimeGenerated, Service="FrontDoor", RequestUri=ClientRequestUrl_s, HttpStatus=ClientResponseStatus_s, TraceParent, RequestId=RequestId_s;

let firewall = AzureDiagnostics
| where ResourceProvider == "MICROSOFT.NETWORK"
| where Category == "AzureFirewallApplicationRuleLog"
| extend traceparent = tostring(parse_json(properties_s).traceparent)
| where extract(@"00-([0-9a-f]{32})-", 1, traceparent) == traceId
| project TimeGenerated, Service="Firewall", Rule=RuleName_s, Action=Action_s, TraceParent=traceparent;

let appGw = AGWAccessLogs
| where isnotempty(TraceParent)
| where extract(@"00-([0-9a-f]{32})-", 1, TraceParent) == traceId
| project TimeGenerated, Service="AppGateway", RequestUri=RequestUri_s, HttpStatus=HttpStatus_d, TraceParent, TransactionId=transactionId_g;

let apim = AzureDiagnostics
| where ResourceProvider == "MICROSOFT.API MANAGEMENT"
| where Category == "GatewayLogs"
| where isnotempty(TraceParent)
| where extract(@"00-([0-9a-f]{32})-", 1, TraceParent) == traceId
| project TimeGenerated, Service="APIM", Operation=operationName_s, HttpStatus=HttpStatus_d, TraceParent, RequestId=requestId_s;

let swa = AzureDiagnostics
| where ResourceProvider == "MICROSOFT.WEB"
| where Category == "StaticWebAppsAccessLog"
| where isnotempty(TraceParent)
| where extract(@"00-([0-9a-f]{32})-", 1, TraceParent) == traceId
| project TimeGenerated, Service="SWA", RequestUri=requestUri_s, HttpStatus=httpStatus_d, TraceParent;

union frontDoor, firewall, appGw, apim, swa
| order by TimeGenerated asc
```

The result set lists every hop (Front Door → Firewall → App Gateway → APIM → SWA) with the exact timestamps, native request IDs, and the shared **`trace-id`** – letting you trace the request through the whole hub‑and‑spoke network.

---

### Quick checklist before you run the queries

| ✅ | Item |
|---|---|
| 1 | All services have diagnostics **enabled** and are sending logs to the **same Log‑Analytics workspace**. |
| 2 | The request **contains a `traceparent` header** (most modern SDKs, Azure services, and Azure Front Door automatically emit it). |
| 3 | Your Log‑Analytics workspace schema includes the **`TraceParent`** column; if not, use `properties_s` parsing as shown. |
| 4 | Replace `"<YOUR_TRACE_ID>"` with the 32‑hex value you are tracking (e.g., `4bf92f3577b34da6a3ce929d0e0e4736`). |
| 5 | Adjust the **time window** (`ago(…)`) to bracket the request’s arrival time. |

That’s the complete, Azure‑native way to query by the **trace‑id** across Front Door, Azure Firewall, Application Gateway, API Management, and Static Web Apps.
