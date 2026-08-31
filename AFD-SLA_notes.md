# Azure SLA Analysis & AFD Incident Escalation Design

## 1. Individual Service SLAs

| Service | SLA | Condition |
|---|---|---|
| Azure Front Door (Standard/Premium) | 99.99% | Same SLA across both tiers; Classic retires March 31, 2027 |
| Azure Application Gateway v2 | 99.95% | Requires 2+ instances or autoscale/zone-redundant config; V1 retired April 28, 2026 with **no SLA** |
| Azure Firewall | 99.99% (zone-redundant, 2+ AZs) / 99.95% (single AZ) | Zone-redundant is now default for new firewalls in multi-AZ regions |
| API Management | 99.95% (Basic/Standard v2) / 99.99% (Premium, multi-region) | No SLA on Developer tier |
| Static Web Apps | 99.95% (Standard plan) | No SLA on Free tier |

**Nines reference:**
- 99% = two nines (~7.3 hrs/month downtime)
- 99.9% = three nines (~43 min/month)
- 99.95% = ~22 min/month
- 99.99% = four nines (~4.3 min/month)

## 2. CDN Comparison (AFD vs. Competitors)

| CDN | SLA | Notes |
|---|---|---|
| Azure Front Door | 99.99% | Standard/Premium tiers, same SLA |
| AWS CloudFront | 99.9% | Commercially-reasonable-efforts commitment |
| Cloudflare Business/Enterprise | 100% | Marketing framing — any downtime triggers a credit, not a claim of zero outages (Nov/Dec 2025 incidents took down major sites) |
| Cloudflare Free/Pro | None | No contractual uptime guarantee |

AFD's 99.99% is the more conventional, measurable SLA metric — real-world uptime across providers is broadly comparable regardless of the published number.

## 3. Composite SLA — Hub(AFD → Firewall → AGW → APIM) → Spoke(SWA)

Serial chain, so SLAs multiply:

```
0.9999 × 0.9999 × 0.9995 × 0.9995 × 0.9995 ≈ 0.9983 (99.83%)
```

- ≈ 24.8 min/month downtime allowed at the composite level
- Weakest links: AGW, APIM, SWA all cap at 99.95%
- Firewall in single-AZ mode also drops to 99.95%, worsening the composite further

### Zone vs. Region Redundancy

| Type | Protects against | Cost | Effect on SLA |
|---|---|---|---|
| Zone-redundant (same region, across AZs) | Datacenter failure | No extra cost | Raises component SLA (e.g. AGW/Firewall to 99.99% tier) |
| Multi-region | Full region outage | Cost + complexity (data sync, routing) | Only needed for DR requirements or pushing composite SLA above what zone-redundancy alone achieves |

Redundant components combine as `1 - (1-A) × (1-B)`, not `A × B` — e.g. two 99.95% instances in parallel ≈ 99.9975%.

**Verdict:** Not all hub+spoke components need to be *both* zone- and region-redundant. Zone-redundancy alone is usually sufficient to clear a 99.9% composite target. Region-redundancy is a DR/business-requirement decision, not a pure SLA-math requirement.

## 4. AFD Blip Investigation (Post Cache-Disable)

- **Trigger:** Cache disabled on the AFD route containing 2 specific custom domains
- **Observed:** Brief "blips" on those 2 domains — 1 occurrence in 3 days since the change
- **Related finding:** Synthetic monitor (Site24x7, no scripting capability) caught a blank page on Page2 (Authy login, a shared service) instead of the expected login page, during the flow: Page1 (SWA, protected) → redirect → Page2 (Authy) → on success → Page3 (SWA)
  - Authy itself showed **zero errors/blips** in its own monitoring/logs — points at the Page1→Page2 redirect hop itself (likely AFD-side), not Authy's application
  - Recommended correlation: match synthetic-failure timestamps against AFD access logs (Log Analytics) for that domain/route, filtered to Site24x7's known source IPs, to catch the exact response code/byte count on that hop

### Decision: Not Worth Bandaid-Fixing

- 1 event in 3 days is statistically inside normal transient-blip tolerance for any edge network — not a pattern
- No cache to purge here (cache is intentionally disabled), so there's no cheap mitigation available anyway
- Diminishing returns on further root-causing a non-reproducible single event

### Chosen Path: SLA Threshold Monitor Instead of a Bandaid

Rather than chase individual blips, track cumulative downtime against the actual 99.99% SLA (4.32 min/month) and escalate to Microsoft only on a real breach. This is a legitimate deliverable for management — "investigated, established a monitoring threshold to reopen if it recurs" — rather than silent inaction.

Two options considered for the SLA tracker itself:
1. **Site24x7 native SLA monitoring** (Admin → Report Settings → SLA Settings) — built-in, four-decimal-place precision, Composite/Executive Summary SLA reports, no custom build required. Since Site24x7 is already paid for, this is the lower-effort path.
2. **Custom KQL dashboard against AFD Log Analytics** — chosen approach, since it can additionally auto-trigger the escalation workflow below.

## 5. KQL: Monthly AFD SLA Breach Query

```kql
// AFD SLA breach monitor — flags when monthly downtime exceeds 4.32 min (99.99% SLA)
// Table: FrontDoorAccessLog (resource-specific logs). If using AzureDiagnostics
// workspace mode instead, add: | where Category == "FrontDoorAccessLog"
FrontDoorAccessLog
| where TimeGenerated >= startofmonth(now())
| where requestUri_s has "YOUR-CUSTOM-DOMAIN"  // scope to the 2-domain route
| summarize TotalRequests = count(),
            ErrorRequests = countif(httpStatusCode_d >= 500)
          by bin(TimeGenerated, 1m)
| extend IsDownMinute = (TotalRequests > 0 and ErrorRequests == TotalRequests)
| summarize DownMinutes = countif(IsDownMinute),
            ElapsedMinutes = count()
| extend UptimePct = round(100.0 * (ElapsedMinutes - DownMinutes) / ElapsedMinutes, 4)
| extend SLABreached = DownMinutes > 4.32
| project DownMinutes, ElapsedMinutes, UptimePct, SLABreached
```

- "Down minute" = every request in that 1-min bin returned 5xx — matches Microsoft's own SLA calculation methodology, making the number directly comparable/defensible in an escalation
- 4.32 min threshold = 99.99% of 43,200 minutes in a 30-day month
- Swap the `has` filter for both custom domains with `or`

## 6. Escalation Workflow Design

**Goal:** On SLA breach → notify Teams channel + email SRE → start a scheduled Teams meeting (bridge call) with pre-configured human attendees → file an MS Support ticket. No bot participation in the call itself.

### Components

| Piece | Mechanism | Perms/Setup Needed |
|---|---|---|
| Scheduled Query Alert Rule | Log Analytics → Alerts → Scheduled query rule, running the KQL above | None beyond workspace access |
| Teams channel notification | **Incoming Webhook** configured directly on the channel (⋯ → Connectors → Incoming Webhook) | None — anonymous HTTP POST to the webhook URL, no service account or membership required |
| Email to SRE | Office 365 / SMTP connector or plain HTTP action | Standard connector auth |
| Scheduled Teams meeting w/ pre-configured attendees | Microsoft Graph `POST /users/{organizerUpn}/onlineMeetings`, called via the Logic App's managed identity | Requires **`OnlineMeetings.ReadWrite.All`** (application permission) granted to the Logic App's managed identity/service principal, plus an **Application Access Policy** scoping it to just the one organizer mailbox |
| MS Support ticket | Microsoft Graph/ARM `PUT /providers/Microsoft.Support/supportTickets/{ticketName}` | Requires **"Support Request Contributor"** role assignment (subscription scope) on the Logic App's managed identity; requires an active support plan (Developer/Standard/Professional Direct) on the subscription |

### Key clarifications reached during design

- **A Teams meeting is a calendar object** — Graph requires every meeting to have an owning organizer mailbox; there is no "ownerless" meeting in the data model. This is unrelated to bot participation.
- **No bot is needed for either piece of this design.** Channel posting uses an anonymous incoming webhook. Meeting creation uses a real human (the existing channel owner) as "organizer of record" — someone who doesn't need to attend the call, just needs to structurally own the calendar event Graph creates.
- **A real-time dial-out/ring call** (Graph `POST /communications/calls`, the Cloud Communications API) is a *different, unrelated* API that **requires** a bot/application identity to initiate — this was ruled out since the requirement is a scheduled meeting with a join link, not an automated dial-out.
- **"The app" needing permission** = the Logic App's own system-assigned managed identity (auto-created as an Entra ID service principal when `identity: { type: 'SystemAssigned' }` is set in Bicep). This is the same identity already used for the Support Ticket role assignment — one more permission grant on the same principal, not a new app registration.
- **Why admin approval is unavoidable:** any *application* (app-only) Graph permission — as opposed to a delegated, user-signed-in permission — requires one-time consent from a Global Administrator or Privileged Role Administrator in Entra ID. This is a hard platform requirement, not an organizational policy choice, because app-only permissions let the app act unattended, with no user in the loop, at any time.
- If no Global Admin/Privileged Role Admin access is available at all, the fallback is a **delegated** flow instead — the human organizer (or a Power Automate flow running under their own login) creates the meeting themselves, rather than the Logic App creating it unattended on their behalf.

### Remaining Action Items

1. Confirm which specific human (existing Teams channel owner) will serve as `organizerUpn` for scheduled meetings
2. Identify who holds Global Admin / Privileged Role Admin in the tenant to request the scoped `OnlineMeetings.ReadWrite.All` Application Access Policy grant
3. Confirm an active Azure support plan exists on the subscription (required for the Support Ticket API call to succeed)
4. Populate the Incoming Webhook URL, attendee list, and `problemClassificationId` (one-time lookup for Azure Front Door's service ID) into the Logic App parameters

## 7. Full Code

### `kql/afd-sla-monitor.kql`

```kql
// AFD SLA breach monitor — flags when monthly downtime exceeds 4.32 min (99.99% SLA)
// Table: FrontDoorAccessLog (resource-specific logs). If using AzureDiagnostics
// workspace mode instead, add: | where Category == "FrontDoorAccessLog"
FrontDoorAccessLog
| where TimeGenerated >= startofmonth(now())
| where requestUri_s has "YOUR-CUSTOM-DOMAIN-1" or requestUri_s has "YOUR-CUSTOM-DOMAIN-2"
| summarize TotalRequests = count(),
            ErrorRequests = countif(httpStatusCode_d >= 500)
          by bin(TimeGenerated, 1m)
| extend IsDownMinute = (TotalRequests > 0 and ErrorRequests == TotalRequests)
| summarize DownMinutes = countif(IsDownMinute),
            ElapsedMinutes = count()
| extend UptimePct = round(100.0 * (ElapsedMinutes - DownMinutes) / ElapsedMinutes, 4)
| extend SLABreached = DownMinutes > 4.32
| project DownMinutes, ElapsedMinutes, UptimePct, SLABreached
```

### `infra/afd-sla-escalation.bicep`

```bicep
param workspaceId string
param logicAppId string
param logicAppTriggerCallbackUrl string
param actionGroupEmail string = 'sre-team@yourorg.com'

// Action Group — routes the alert to the Logic App (Teams webhook + meeting + ticket workflow)
resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-afd-sla-breach'
  location: 'global'
  properties: {
    groupShortName: 'AFDSLA'
    enabled: true
    emailReceivers: [
      { name: 'sre-email', emailAddress: actionGroupEmail, useCommonAlertSchema: true }
    ]
    logicAppReceivers: [
      {
        name: 'afd-sla-escalation-logicapp'
        resourceId: logicAppId
        callbackUrl: logicAppTriggerCallbackUrl
        useCommonAlertSchema: true
      }
    ]
  }
}

// Scheduled Query Alert Rule — runs the SLA-breach KQL, fires when SLABreached == true
resource slaAlertRule 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'afd-sla-4-32-min-breach'
  location: resourceGroup().location
  properties: {
    displayName: 'AFD Monthly SLA Breach (>4.32 min)'
    description: 'Fires when cumulative AFD downtime for the monitored route exceeds the 99.99% SLA threshold for the current calendar month.'
    severity: 1
    enabled: true
    evaluationFrequency: 'PT1H'
    windowSize: 'PT1H'
    scopes: [
      workspaceId
    ]
    criteria: {
      allOf: [
        {
          query: loadTextContent('../kql/afd-sla-monitor.kql')
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          resourceIdColumn: ''
          dimensions: []
        }
      ]
    }
    actions: {
      actionGroups: [
        actionGroup.id
      ]
    }
  }
}

output actionGroupId string = actionGroup.id
output alertRuleId string = slaAlertRule.id
```

### `infra/logicapp-sla-escalation.bicep`

```bicep
param location string = resourceGroup().location

resource logicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'la-afd-sla-escalation'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    definition: json(loadTextContent('../workflows/sla-ticket-workflow.json'))
  }
}

// Support Request Contributor — required to file MS Support tickets via API
resource supportRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, logicApp.id, 'support-contributor')
  scope: subscription()
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7c0feaea-b8ce-4ba9-8be3-05a7188e6d6d' // built-in "Support Request Contributor"
    )
    principalId: logicApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// NOTE: OnlineMeetings.ReadWrite.All (application permission) cannot be granted via Bicep —
// it requires manual admin consent in Entra ID, scoped to the organizer mailbox via an
// Application Access Policy. See section 6 "Remaining Action Items".

output logicAppPrincipalId string = logicApp.identity.principalId
output logicAppId string = logicApp.id
```

### `workflows/sla-ticket-workflow.json`

```json
{
  "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "webhookUrl": { "type": "string", "defaultValue": "<INCOMING_WEBHOOK_URL>" },
    "organizerUpn": { "type": "string", "defaultValue": "<EXISTING_TEAMS_CHANNEL_OWNER_UPN>" },
    "attendees": {
      "type": "array",
      "defaultValue": [
        { "upn": "sre1@yourorg.com", "role": "presenter" },
        { "upn": "sre2@yourorg.com", "role": "presenter" },
        { "upn": "netops@yourorg.com", "role": "attendee" }
      ]
    },
    "sreEmail": { "type": "string", "defaultValue": "sre-team@yourorg.com" },
    "problemClassificationId": { "type": "string", "defaultValue": "<LOOKED_UP_ONCE_FOR_AFD>" }
  },
  "triggers": {
    "manual": {
      "type": "Request",
      "kind": "Http",
      "inputs": {
        "schema": {}
      }
    }
  },
  "actions": {
    "Post_to_Teams_Channel": {
      "type": "Http",
      "runAfter": {},
      "inputs": {
        "method": "POST",
        "uri": "@parameters('webhookUrl')",
        "headers": { "Content-Type": "application/json" },
        "body": {
          "@@type": "MessageCard",
          "@@context": "http://schema.org/extensions",
          "themeColor": "FF0000",
          "title": "AFD SLA Breach — 4.32 min threshold crossed",
          "text": "@{triggerBody()?['data']?['essentials']?['alertRule']}. Bridge call starting shortly."
        }
      }
    },
    "Send_Email_to_SRE": {
      "type": "Http",
      "runAfter": { "Post_to_Teams_Channel": ["Succeeded"] },
      "inputs": {
        "method": "POST",
        "uri": "https://graph.microsoft.com/v1.0/users/@{parameters('organizerUpn')}/sendMail",
        "authentication": { "type": "ManagedServiceIdentity" },
        "body": {
          "message": {
            "subject": "AFD SLA breach — bridge call created",
            "body": { "contentType": "Text", "content": "See Teams channel for details and join link." },
            "toRecipients": [ { "emailAddress": { "address": "@parameters('sreEmail')" } } ]
          }
        }
      }
    },
    "Create_Teams_Meeting": {
      "type": "Http",
      "runAfter": { "Send_Email_to_SRE": ["Succeeded"] },
      "inputs": {
        "method": "POST",
        "uri": "https://graph.microsoft.com/v1.0/users/@{parameters('organizerUpn')}/onlineMeetings",
        "authentication": { "type": "ManagedServiceIdentity" },
        "body": {
          "subject": "AFD SLA Breach — Incident Bridge",
          "startDateTime": "@utcNow()",
          "endDateTime": "@addHours(utcNow(), 1)",
          "participants": {
            "attendees": "@array(parameters('attendees'))"
          }
        }
      }
    },
    "Post_Bridge_Link_to_Channel": {
      "type": "Http",
      "runAfter": { "Create_Teams_Meeting": ["Succeeded"] },
      "inputs": {
        "method": "POST",
        "uri": "@parameters('webhookUrl')",
        "headers": { "Content-Type": "application/json" },
        "body": {
          "@@type": "MessageCard",
          "@@context": "http://schema.org/extensions",
          "title": "Bridge call ready",
          "text": "Join: @{body('Create_Teams_Meeting')?['joinUrl']}"
        }
      }
    },
    "Create_Support_Ticket": {
      "type": "Http",
      "runAfter": { "Post_Bridge_Link_to_Channel": ["Succeeded"] },
      "inputs": {
        "method": "PUT",
        "uri": "https://management.azure.com/providers/Microsoft.Support/supportTickets/@{guid()}?api-version=2020-04-01",
        "authentication": { "type": "ManagedServiceIdentity" },
        "body": {
          "properties": {
            "title": "Azure Front Door SLA Breach",
            "description": "Cumulative downtime exceeded 4.32 min (99.99% SLA) for the current calendar month on the affected AFD route. See attached KQL output.",
            "severity": "moderate",
            "problemClassificationId": "@parameters('problemClassificationId')",
            "contactDetails": {
              "firstName": "SRE",
              "lastName": "Team",
              "preferredContactMethod": "email",
              "primaryEmailAddress": "@parameters('sreEmail')",
              "country": "US",
              "preferredTimeZone": "Pacific Standard Time",
              "preferredSupportLanguage": "en-US"
            }
          }
        }
      }
    }
  },
  "outputs": {}
}
```
