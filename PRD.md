# PRD: Patch LocalStack Azure Image for VNet Peering + Firewall Support

## Context

- **Image**: `localstack/localstack-azure-alpha:8a3d8a4e462fe9f3b305f4076a3050e8fd1750de`
- **Container source**: `/opt/code/localstack/localstack-pro-azure/`
- **Goal**: Patch the running container in-place to support VNet Peering and Azure Firewall (stub level — correct JSON in/out, in-memory state, no real network emulation needed)

## What Is Already Working

- `Microsoft.Network/virtualNetworks` — CREATE + GET work
- `Microsoft.Resources/deployments` — full Bicep deployment pipeline works
- `Microsoft.Resources/resourceGroups` — fully working
- VNet GET by name works, LIST returns empty (bug)

## What Is Broken

### 1. `Microsoft.Network/virtualNetworks/virtualNetworkPeerings`
- All CRUD operations return `{"error": true, "exception": "NotImplementedError", "message": ""}`
- There is NO peering handler file anywhere in the codebase — it is completely absent
- `provider_data.py` lists `virtualNetworks/virtualNetworkPeerings` as a known resource type under `Microsoft.Network` — so routing knows it exists but nothing handles it

### 2. `Microsoft.Network/azureFirewalls`
- Returns `NotImplementedError` on all operations
- Completely absent from the service layer

### 3. `Microsoft.Network/virtualNetworks` LIST
- `GET /subscriptions/{sub}/resourcegroups/{rg}/providers/Microsoft.Network/virtualNetworks`
- Returns `{"value": []}` even when VNets exist
- Individual GET by name works fine

### 4. `Microsoft.Network/routeTables`
- Untested but expected to be missing

---

## Architecture (from source inspection)

The codebase follows a consistent pattern:

```
/localstack/pro/azure/
  api/
    Microsoft_{Service}/
      {Service}_ResourceManager_API.py   ← method stubs (raise NotImplementedError)
      {Service}_ResourceManager_Objects.py ← request/response types
  services/
    {service}/
      provider.py    ← actual implementation
      models.py      ← data models
      exceptions.py  ← custom exceptions
  services/
    store.py         ← global in-memory state store
  api/core/routing/
    routing.py       ← URL → handler mapping
```

Existing working example to copy the pattern from: `services/resources/provider.py`

State is stored in-memory via `store.py`. No database. No persistence across restarts.

---

## Task: What the Agent Must Build

### Step 1: Explore (read before writing anything)

Read these files first to understand exact patterns:
```
/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/provider.py
/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/store.py
/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/api/core/routing/routing.py
/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/models.py
```

Then read an existing working network-adjacent service if one exists, otherwise use resources as the reference.

### Step 2: Fix VNet LIST

File to patch: wherever `virtualNetworks` LIST is handled.

Find it via:
```bash
grep -rn "virtualNetworks\|virtual_networks" /opt/code/localstack/localstack-pro-azure/localstack --include="*.py" | grep -v .venv | grep -v build | grep -v provider_data
```

The fix: make LIST return all VNets stored in the in-memory store for that resource group, same structure as individual GET.

Expected response shape:
```json
{
  "value": [
    {
      "id": "/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{name}",
      "name": "{name}",
      "type": "Microsoft.Network/virtualNetworks",
      "location": "eastus",
      "properties": {
        "provisioningState": "Succeeded",
        "addressSpace": { "addressPrefixes": ["10.0.0.0/16"] },
        "subnets": []
      }
    }
  ]
}
```

### Step 3: Implement VNet Peering CRUD

Create or patch the peering handler. Peerings are sub-resources of VNets.

URL patterns to handle:
```
PUT    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnetName}/virtualNetworkPeerings/{peeringName}
GET    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnetName}/virtualNetworkPeerings/{peeringName}
GET    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnetName}/virtualNetworkPeerings
DELETE /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnetName}/virtualNetworkPeerings/{peeringName}
```

Expected PUT request body:
```json
{
  "properties": {
    "remoteVirtualNetwork": { "id": "/subscriptions/.../virtualNetworks/vnet-spoke-1" },
    "allowVirtualNetworkAccess": true,
    "allowForwardedTraffic": true,
    "allowGatewayTransit": true,
    "useRemoteGateways": false
  }
}
```

Expected PUT/GET response:
```json
{
  "id": "/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnetName}/virtualNetworkPeerings/{peeringName}",
  "name": "{peeringName}",
  "type": "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
  "properties": {
    "provisioningState": "Succeeded",
    "peeringState": "Connected",
    "remoteVirtualNetwork": { "id": "..." },
    "allowVirtualNetworkAccess": true,
    "allowForwardedTraffic": true,
    "allowGatewayTransit": true,
    "useRemoteGateways": false,
    "remoteAddressSpace": { "addressPrefixes": [] }
  }
}
```

Key: `peeringState` must be `"Connected"` immediately — no async, no polling.

LIST response wraps in `{"value": [...]}`.

### Step 4: Implement Azure Firewall CRUD (stub)

URL patterns:
```
PUT    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls/{firewallName}
GET    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls/{firewallName}
GET    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls
DELETE /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls/{firewallName}
```

Expected GET response (minimal stub — enough for Bicep deployment to succeed):
```json
{
  "id": "/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls/{name}",
  "name": "{name}",
  "type": "Microsoft.Network/azureFirewalls",
  "location": "eastus",
  "properties": {
    "provisioningState": "Succeeded",
    "ipConfigurations": [
      {
        "name": "fw-ipconfig",
        "properties": {
          "privateIPAddress": "10.0.2.4",
          "provisioningState": "Succeeded"
        }
      }
    ],
    "networkRuleCollections": []
  }
}
```

The private IP `10.0.2.4` is the first usable IP in AzureFirewallSubnet `10.0.2.0/24` — hardcode it for the POC.

### Step 5: Implement Route Tables CRUD (stub)

URL patterns:
```
PUT    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/routeTables/{routeTableName}
GET    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/routeTables/{routeTableName}
```

Expected response:
```json
{
  "id": "...",
  "name": "{name}",
  "type": "Microsoft.Network/routeTables",
  "location": "eastus",
  "properties": {
    "provisioningState": "Succeeded",
    "routes": []
  }
}
```

### Step 6: Fix Public IP CRUD (needed by Firewall)

URL patterns:
```
PUT    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/publicIPAddresses/{name}
GET    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/publicIPAddresses/{name}
```

Stub response:
```json
{
  "id": "...",
  "name": "{name}",
  "type": "Microsoft.Network/publicIPAddresses",
  "location": "eastus",
  "sku": { "name": "Standard" },
  "properties": {
    "provisioningState": "Succeeded",
    "publicIPAllocationMethod": "Static",
    "ipAddress": "20.0.0.1"
  }
}
```

---

## How to Apply the Patch

All edits are to Python files inside the running container. After editing:

```bash
# Find the process and restart just the relevant service (or restart the whole container)
# Preferred: edit files in-place and send SIGHUP or restart the gateway

docker exec d8b9946ea431 kill -HUP 1
# If that doesn't work:
docker restart d8b9946ea431
```

Or copy patched files in:
```bash
docker cp patched_provider.py d8b9946ea431:/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/network/provider.py
```

---

## Verification After Patch

Run these curls — all must return valid JSON with `provisioningState: Succeeded`:

```bash
SUB="00000000-0000-0000-0000-000000000000"
RG="rg-hub-spoke"
BASE="http://localhost:4510"
H="Authorization: Bearer faketoken"

# 1. VNet LIST
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/virtualNetworks?api-version=2023-04-01" -H "$H"

# 2. Peering GET
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/virtualNetworks/vnet-hub/virtualNetworkPeerings/hub-to-spoke1?api-version=2023-04-01" -H "$H"

# 3. Peering LIST
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/virtualNetworks/vnet-hub/virtualNetworkPeerings?api-version=2023-04-01" -H "$H"

# 4. Firewall GET
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/azureFirewalls/fw-hub?api-version=2023-04-01" -H "$H"

# 5. Full deploy.sh must complete with all Succeeded
cd /path/to/hub-spoke-poc && ./deploy.sh
```

All 4 peerings must show `"peeringState": "Connected"`.
Firewall must return `"provisioningState": "Succeeded"` with `privateIPAddress: "10.0.2.4"`.

---

## Success Criteria

- [ ] `./deploy.sh` completes without hanging
- [ ] VNet LIST returns all 3 VNets (hub, spoke-1, spoke-2)
- [ ] All 4 peerings return `Connected`
- [ ] Firewall returns `Succeeded` with private IP
- [ ] Route tables return `Succeeded`
- [ ] Deployment final status is `Succeeded` not `Running`