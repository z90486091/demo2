# Hub-and-Spoke POC — LocalStack Azure Network Patch

**Bicep-deployed hub-and-spoke topology with VNet peering, Azure Firewall, route tables (UDRs), firewall rules, and dataplane forwarding simulation — running entirely on LocalStack Azure emulator.**

## Table of Contents

- [Quick Start](#quick-start)
- [Topology](#topology)
- [What Was Added](#what-was-added)
- [Patched Image](#patched-image)
- [ARM Template Processing](#arm-template-processing)
- [Azure Networking Features](#azure-networking-features)
  - [Virtual Networks & Peerings](#virtual-networks--peerings)
  - [Azure Firewall & IPAM](#azure-firewall--ipam)
  - [Route Tables & UDRs](#route-tables--udrs)
  - [Network Interfaces](#network-interfaces)
  - [Effective Route Table](#effective-route-table)
  - [Dataplane Forwarding Simulation](#dataplane-forwarding-simulation)
- [API Endpoints](#api-endpoints)
- [Verification](#verification)
- [Behavior Differences vs Real Azure](#behavior-differences-vs-real-azure)
- [Known Limitations](#known-limitations)
- [Architecture Notes](#architecture-notes)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# 1. Build the patched image (do this once)
docker commit <running-container-id> localstack-azure-patched:hub-spoke-poc

# 2. Run the patched image
docker run --rm -it -p 4566:4566 -p 4510:4510 \
  -e ACTIVATE_PRO=0 \
  localstack-azure-patched:hub-spoke-poc

# 3. Deploy
./deploy.sh
```

Expected output: `All resources deployed successfully!` with `provisioningState: Succeeded`.

---

## Topology

```
┌──────────────────────────────────────────────────────────────┐
│                      rg-hub-spoke                            │
│                                                              │
│  ┌─────────┐   peering    ┌────────────┐   peering  ┌──────┐│
│  │vnet-hub  │◄───────────►│vnet-spoke-1│◄──────────►│spoke-2││
│  │10.0.0/16 │             │10.1.0.0/16 │             │10.2.0 ││
│  │          │             │            │             │       ││
│  │ AzureFW  │             │ snet-wrk   │             │snet   ││
│  │ subnet   │             │  rt-spoke1 │             │rt-s   ││
│  └────┬─────┘             └──────┬─────┘             └───────┘│
│       │                          │                           │
│       └─────────── firewall ─────┘ (UDR: next hop = fw IP)   │
│                      fw-hub                                   │
│                   pip-azfw                                    │
└──────────────────────────────────────────────────────────────┘
```

5 Bicep modules deployed in dependency order:
1. **hub.bicep** — Hub VNet with 3 subnets (shared-services, AzureFirewallSubnet, GatewaySubnet)
2. **spokes.bicep** — Two spoke VNets with workload subnets
3. **peering.bicep** — 4 bidirectional peerings (hub↔spoke1, hub↔spoke2)
4. **firewall.bicep** — Azure Firewall, Public IP, 2 Route Tables, 2 subnet route table associations
5. **firewall-rules.bicep** — Network rule collection on the firewall (allow spoke-to-spoke)

---

## What Was Added (CHANGELOG)

### v1.0 — Initial Networking Fidelity Release

| Area | Change |
|---|---|
| **ARM deployment engine** | `_resolve_reference_expressions()` — parameter-level `[reference()]` resolution in `GlobalDeployment.__init__` |
| **ARM deployment engine** | `Resource._resolve_references()` — resource-payload-level `[reference()]` resolution at PUT time |
| **Network provider** | Full CRUD for VNets, Peerings, Firewalls, RouteTables, PublicIPs, Subnets, NetworkInterfaces |
| **IPAM** | Deterministic private IP allocation engine — Azure-reserved addresses (.0-.3), sequential .4+ allocation |
| **Route computation** | `effectiveRouteTable` endpoint with system + UDR + peering route synthesis, deduplication, and Azure precedence |
| **Forwarding simulation** | `simulateForwarding` endpoint with recursive topology traversal, loop/blackhole/max-hop detection |
| **Firewall traversal** | VirtualAppliance next-hop resolution, firewall-VNet continuation, IP-based fallback |
| **Peering traversal** | Cross-VNet route continuation, remote address space propagation |
| **Route metadata preservation** | `first_matched_route`, `first_next_hop`, `first_next_hop_type` captured at initial match and returned in all terminal hops |
| **Entry points** | `.dist-info/entry_points.txt` plugin metadata for `Microsoft.Network:default` |
| **Routes** | 26 HTTP routes registered in the ARM routing table (GET/PUT/POST/DELETE) |
| **Plugin registration** | `@azure_provider(api="Microsoft.Network")` in `plugins.py` |

---

## Patched Image

### Base Image

```
localstack/localstack-azure-alpha:8a3d8a4e462fe9f3b305f4076a3050e8fd1750de
```

### Saving the Patched Image

```bash
# Find the running container
CONTAINER_ID=$(docker ps -q --filter ancestor=localstack/localstack-azure-alpha:8a3d8a4e462fe9f3b305f4076a3050e8fd1750de)

# Commit the running patched container
docker commit "$CONTAINER_ID" localstack-azure-patched:hub-spoke-poc

# Verify
docker images | grep localstack-azure-patched

# Optional: save to tar for distribution
docker save localstack-azure-patched:hub-spoke-poc | gzip > localstack-azure-patched-hub-spoke-poc.tar.gz
```

### Running the Patched Image

```bash
docker run --rm -it -p 4566:4566 -p 4510:4510 \
  -e ACTIVATE_PRO=0 \
  localstack-azure-patched:hub-spoke-poc
```

---

## ARM Template Processing

**File:** `localstack/pro/azure/services/resources/deployments/models.py`

### Problem

The ARM template parser CLI (`Azure/arm-template-parser`) cannot resolve `[reference(...)]` expressions. Bicep compilation produces templates where nested deployment parameters reference sibling deployment outputs via:

```
[reference(resourceId('Microsoft.Resources/deployments', 'deploy-hub'), '2025-04-01').outputs.hubVnetName.value]
```

And resource properties reference other resources via:

```
[reference(resourceId('Microsoft.Network/virtualNetworks', 'vnet-hub'), '2023-04-01').subnets[1].id]
```

The parser CLI returns empty output when it encounters these, causing `json.loads()` to fail with `"Expecting value: line 1 column 1 (char 0)"` — which kills the nested deployment thread silently.

### Two-Level Reference Resolution

#### Level 1: Parameter References (`_resolve_reference_expressions` in `GlobalDeployment.__init__`)

Runs at deployment creation time, before the ARM template parser is called. Pre-resolves `[reference(...)]` expressions in **deployment parameters** by making live HTTP GET requests through the LocalStack proxy.

**Resolution flow:**

```
Param value: [reference(resourceId('Microsoft.Resources/deployments', 'deploy-hub'), ...).outputs.hubVnetName.value]
    │
    ├── Iteration 1: pattern_deployment matches
    │   └── GET /deployments/deploy-hub → reads outputs.hubVnetName.value
    │   └── resolved = "vnet-hub" (plain string, done)
    │
Param value: [reference(resourceId('Microsoft.Resources/deployments', 'deploy-hub'), ...).outputs.firewallSubnetId.value]
    │
    ├── Iteration 1: pattern_deployment matches
    │   └── GET /deployments/deploy-hub → reads outputs.firewallSubnetId.value
    │   └── resolved = "[reference(resourceId('Microsoft.Network/virtualNetworks', 'vnet-hub'), '2023-04-01').subnets[1].id]"
    │
    ├── Iteration 2: pattern_resource matches
    │   └── GET /virtualNetworks/vnet-hub → navigates properties.subnets[1].id
    │   └── resolved = "/subscriptions/.../virtualNetworks/vnet-hub/subnets/AzureFirewallSubnet"
    │
    └── Final: parameter value is the resolved subnet ID
```

**Key details:**
- Iterative: up to 5 chained resolutions (deployment output → resource reference → ...)
- Navigation starts from `properties` of the GET response because ARM's `reference()` function returns resource properties directly (not the full ARM wrapper with `id`, `name`, `type`, etc.)
- `import re` added at module level (was only locally imported as `_re`, causing `NameError`)
- Log level changed from `DEBUG` to `WARNING` for visibility at default logging level (30)

#### Level 2: Resource Payload References (`_resolve_references` in `Resource.deploy`)

Runs at per-resource deploy time, immediately before the PUT request is sent to the provider. This resolves `[reference(...)]` expressions found **inside resource property payloads** — for example, a route table's `nextHopIpAddress` field that references a firewall's private IP.

```
Resource: routeTable "rt-spoke1"
  └── nextHopIpAddress: [reference(resourceId('Microsoft.Network/azureFirewalls', 'fw-hub'), ...).ipConfigurations[0].properties.privateIPAddress]
      │
      ├── GET /azureFirewalls/fw-hub?api-version=2023-04-01
      ├── navigate: properties.ipConfigurations[0].properties.privateIPAddress
      └── resolved: "10.0.2.4" (actual firewall private IP)
```

**How it works:**
- `Resource._resolve_references()` recursively walks the entire `_resource_data` dict
- For every string value matching `[reference(resourceId('TYPE', 'NAME'), 'API-VER').PATH]`, it issues a GET request to the referenced resource via the LocalStack proxy
- Uses `GlobalDeployment._navigate_json_path()` to drill into the response
- Resolved values are substituted directly into the resource data before PUT submission
- This runs AFTER dependencies are deployed (deployment order is `dependsOn`-aware), so referenced resources should exist

### Additional Fixes

- **`_navigate_json_path`**: Changed `_re.match(...)` to `re.match(...)` (the local `import re as _re` was removed but `_re` was still referenced)
- **Regex in `_resolve_reference_expressions`**: Fixed from `\)\)` (double close-paren) to `\)` (single)

---

## Azure Networking Features

All networking features are implemented in:

- **Models:** `localstack/pro/azure/services/network/models.py` — `NetworkStore` with in-memory state
- **Provider:** `localstack/pro/azure/services/network/provider.py` — `NetworkImpl` with CRUD + route computation + forwarding
- **Registration:** `localstack/pro/azure/services/plugins.py` — `@azure_provider(api="Microsoft.Network")`

### Virtual Networks & Peerings

| Resource | Methods | Notes |
|---|---|---|
| `virtualNetworks` | create_or_update, get, list, delete | Address space, subnets |
| `virtualNetworks/virtualNetworkPeerings` | create_or_update, get, list, delete | `peeringState: "Connected"` at top-level + `properties` |
| `virtualNetworks/subnets` | create_or_update, get, list | ID generation, route table association |

**Subnet ID generation:** When a VNet is created with inline subnets (as Bicep does), the provider iterates through subnets and adds an `id` field:
```
/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet_name}
```
This is required because `reference(...).subnets[1].id` needs to navigate to a real ID. Subnets are also registered in the standalone `store.subnets` collection for direct access.

**PeeringState placement:** `peeringState: "Connected"` is stored at the top level of the peering dict (alongside `id`, `name`, `type`) so that `jq .peeringState` returns `"Connected"` from the GET response, in addition to the `properties.peeringState` field that the LIST endpoint returns.

**Remote address space propagation:** When a peering is created, the provider looks up the remote VNet and copies its `addressPrefixes` into the peering's `properties.remoteAddressSpace`. This is used by the effective route table engine to synthesize peering routes.

### Azure Firewall & IPAM

| Resource | Methods | Notes |
|---|---|---|
| `azureFirewalls` | create_or_update, get, list, delete | Dynamic private IP allocation via IPAM |
| `publicIPAddresses` | create_or_update, get, list | Static public IP |

**Private IP Allocation (IPAM):**
The provider implements a deterministic IPAM engine in `_allocate_private_ip()`:

```python
def _allocate_private_ip(self, subscription_id, subnet_id):
    subnet = find_subnet(subnet_id)
    net = IPv4Network(subnet.addressPrefix, strict=False)
    hosts = list(net.hosts())
    # Azure reserves: .0 (network), .1 (gateway), .2-.3 (Azure reserved)
    allocatable = [str(h) for h in hosts[3:]]   # starts at .4
    for ip in allocatable:
        if ip not in previously_allocated:
            store.private_ip_allocations[subnet_id].append(ip)
            return ip
```

**Allocation rules:**
- Subnet CIDR is parsed via `ipaddress.IPv4Network`
- First 4 addresses (.0, .1, .2, .3) are reserved per Azure convention
- Allocation starts at .4 and increments sequentially
- Allocations are tracked per-subnet in `store.private_ip_allocations`
- IPs are never released (simplified model)
- On container restart, the IPAM resets (in-memory state)

Example: `AzureFirewallSubnet (10.0.2.0/24)` allocates `10.0.2.4` as the first available IP.

### Route Tables & UDRs

| Resource | Methods | Notes |
|---|---|---|
| `routeTables` | create_or_update, get, list | Preserves routes from PUT body |

Route tables store user-defined routes (UDRs) with the following properties per route:
- `name`: Route name (e.g., `to-spoke2`)
- `properties.addressPrefix`: Destination CIDR (e.g., `10.2.0.0/16`)
- `properties.nextHopType`: Always `VirtualAppliance` for Bicep-generated routes
- `properties.nextHopIpAddress`: The resolved firewall private IP (via deployment engine reference resolution)

Subnet-to-route-table association is stored in the subnet's `properties.routeTable.id` field, set during deployment.

### Network Interfaces

| Resource | Methods | Notes |
|---|---|---|
| `networkInterfaces` | create_or_update, get, list | NIC CRUD with IP allocation |
| `networkInterfaces/effectiveRouteTable` | get | Route computation (see below) |
| `networkInterfaces/simulateForwarding` | post | Topology traversal (see below) |

**NIC creation flow:**
1. Parse request body for `ipConfigurations[].properties.subnet.id`
2. Allocate private IP from the referenced subnet via IPAM
3. Set `privateIPAddress`, `privateIPAllocationMethod`, `provisioningState`
4. Store NIC in `store.network_interfaces`

### Effective Route Table

The `effectiveRouteTable` endpoint computes the consolidated route table for a NIC based on its subnet and VNet. Route synthesis occurs in `_compute_effective_routes_for_subnet()`.

**Route sources in priority order:**

| Priority | Source | Route Type | Example |
|---|---|---|---|
| 1 (highest) | User-defined (UDR) | `VirtualAppliance` | `to-spoke2 → 10.0.2.4` |
| 2 | BGP (not implemented) | — | — |
| 3 (default) | System | `VNetLocal` | `10.0.0.0/16 → VNetLocal` |
| 3 (default) | System | `VNetPeering` | `10.1.0.0/16 → VNetPeering` |
| 3 (default) | System | `Internet` | `0.0.0.0/0 → Internet` |

**Deduplication logic:** Routes are deduplicated by `addressPrefix`. User-defined routes override system routes for the same prefix. Within the same source priority, longer prefixes win.

**Route precedence algorithm:**
```
1. Collect all candidate routes:
   a. System: VNet-local prefixes from VNet address space
   b. System: Internet (0.0.0.0/0)
   c. UDR: routes from subnet's associated route table
   d. System: Peering routes from connected VNet peerings

2. Deduplicate:
   for each addressPrefix:
       if conflicting prefixes exist:
           User > Default
           longer prefixlen wins within same source
```

### Dataplane Forwarding Simulation

The `simulateForwarding` endpoint performs recursive topology graph traversal to determine the full forwarding path from a source NIC to a destination IP address.

**Traversal algorithm (`_resolve_route_hop`, recursive):**

```
Input: source NIC, destination IP
  │
  ├── 1. Get source subnet + VNet from NIC
  ├── 2. Detect loops (visited VNets set) + max hops (10)
  ├── 3. Compute effective routes for source subnet
  ├── 4. Longest-prefix match against destination IP
  │
  ├── CASE "VirtualAppliance" (UDR → firewall)
  │   ├── Find firewall by next-hop IP
  │   ├── Add "fw:{name}" to path
  │   ├── Get firewall's subnet + VNet
  │   ├── Recurse from firewall's VNet
  │   └── Fallback: find VNet by IP if firewall not found
  │
  ├── CASE "VNetPeering" (peering to another VNet)
  │   ├── Resolve remote VNet from peering
  │   ├── Add "peering:{name}" to path
  │   ├── Recurse from remote VNet (no UDRs)
  │   └──
  │
  ├── CASE "VNetLocal" (destination in same VNet)
  │   ├── Find destination subnet by IP
  │   ├── Add "subnet:{name}" to path
  │   ├── Find NIC at destination IP
  │   ├── Add "nic:{name}" if found
  │   └── Terminate: reachable
  │
  ├── CASE "Internet"
  │   └── Terminate: reachable via Internet
  │
  └── Error cases:
      ├── No matching route → Blackhole
      ├── VNet revisited → Loop detected
      ├── Hops > 10 → Max hops exceeded
      └── Unknown next hop type
```

**Path format (list of strings):**
```
["source-nic", "subnet:source-subnet", "rt:route-table", "fw:firewall",
 "peering:peering-name", "subnet:dest-subnet", "nic:dest-nic"]
```

**Loop detection:** Tracks visited VNet IDs in a `set`. If the same VNet is encountered twice, returns `"Routing loop detected"`.

**Max-hop protection:** Hard limit of 10 recursive hops. Returns `"Max hops exceeded"` if exceeded.

**Blackhole detection:** If longest-prefix match returns no route at any hop, returns `"Blackhole — no matching route"`.

**Next-hop metadata preservation:** The `first_matched_route`, `first_next_hop`, and `first_next_hop_type` are captured from the initial route selection and preserved across all recursive calls. Terminal handlers (VNetLocal, Internet) return the original metadata rather than overwriting with `None`.

**Firewall resolution fallback:** If the next-hop IP doesn't match any known firewall (e.g., due to stale IP in a route table after container restart), the engine falls back to `_find_subnet_by_ip_any_vnet()` to locate the VNet containing that IP by scanning all VNet address spaces. If the IP falls in an `AzureFirewall*` subnet, it's labeled as a firewall hop; otherwise as `nva:{ip}`.

### Models

```python
class NetworkStore:
    virtual_networks: dict[str, dict]       # key: resource ID
    peerings: dict[str, dict]               # key: resource ID
    firewalls: dict[str, dict]              # key: resource ID
    route_tables: dict[str, dict]           # key: resource ID
    public_ip_addresses: dict[str, dict]    # key: resource ID
    subnets: dict[str, dict]                # key: resource ID
    network_interfaces: dict[str, dict]     # key: resource ID
    private_ip_allocations: dict[str, list] # key: subnet ID
```

All state is in-memory — no persistence across container restarts. Each method in the provider accesses the store via `self.get_store(subscription_id, location)`.

### Provider Registration

**File:** `localstack/pro/azure/services/plugins.py`

```python
@azure_provider(api="Microsoft.Network")
def network(...):
    ...
```

This registers the `NetworkImpl` provider with LocalStack's service discovery under the `Microsoft.Network` API namespace.

---

## Routing

**File:** `localstack/pro/azure/api/core/routing/routing.py`

26 routes added for the `Microsoft.Network` namespace under GET, PUT, POST, and DELETE sections:

### GET Routes

| Route | Handler |
|---|---|
| `/.../virtualNetworks` | `virtual_networks__list` |
| `/.../virtualNetworks/{vnetName}` | `virtual_networks__get` |
| `/.../virtualNetworks/{vnetName}/virtualNetworkPeerings` | `virtual_network_peerings__list` |
| `/.../virtualNetworks/{vnetName}/virtualNetworkPeerings/{peeringName}` | `virtual_network_peerings__get` |
| `/.../azureFirewalls` | `azure_firewalls__list` |
| `/.../azureFirewalls/{firewallName}` | `azure_firewalls__get` |
| `/.../routeTables` | `route_tables__list` |
| `/.../routeTables/{routeTableName}` | `route_tables__get` |
| `/.../publicIPAddresses` | `public_ip_addresses__list` |
| `/.../publicIPAddresses/{publicIPName}` | `public_ip_addresses__get` |
| `/.../virtualNetworks/{vnetName}/subnets` | `virtual_networks_subnets__list` |
| `/.../virtualNetworks/{vnetName}/subnets/{subnetName}` | `virtual_networks_subnets__get` |
| `/.../networkInterfaces` | `network_interfaces__list` |
| `/.../networkInterfaces/{nicName}` | `network_interfaces__get` |
| `/.../networkInterfaces/{nicName}/effectiveRouteTable` | `network_interfaces__effective_route_table` |

### PUT Routes

All above resource types have `*__create_or_update` handlers (VNets, Peerings, Firewalls, Route Tables, Public IPs, Subnets, Network Interfaces).

### POST Routes

| Route | Handler |
|---|---|
| `/.../networkInterfaces/{nicName}/simulateForwarding` | `network_interfaces__simulate_forwarding` |

### DELETE Routes

VNets, Peerings, Firewalls have `*__delete` handlers.

### Route Matching Notes

- PUT routes are matched before GET routes in the routing table since they share the same URL pattern
- The `simulateForwarding` route uses `networkInterfaceName` capture group with `[^/]*` regex (not `.*`) to avoid ambiguity with other paths
- Network interface routes are registered in both GET and PUT sections with the correct HTTP method

---

## API Endpoints

All endpoints follow the `{base}/subscriptions/{subId}/resourceGroups/{rgName}/providers/Microsoft.Network/{resourceType}` pattern.

**Base URL:** `http://localhost:4510`
**Subscription:** `00000000-0000-0000-0000-000000000000`
**Header:** `Authorization: Bearer faketoken`

### Virtual Networks

```bash
# List
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/virtualNetworks?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .

# Get
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/virtualNetworks/vnet-hub?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .
```

### VNet Peerings

```bash
# List
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/virtualNetworks/vnet-hub/virtualNetworkPeerings?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .

# Get (peeringState must be "Connected")
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/virtualNetworks/vnet-hub/virtualNetworkPeerings/hub-to-spoke1?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq '.peeringState'
```

### Subnets

```bash
# List
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/virtualNetworks/vnet-hub/subnets?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .
```

### Azure Firewall

```bash
# Get (shows private IP, public IP, subnet)
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/azureFirewalls/fw-hub?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .
```

### Route Tables

```bash
# List
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/routeTables?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .

# Get (shows UDRs with next hop IPs)
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/routeTables/rt-spoke1?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .
```

### Public IPs

```bash
# List
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/publicIPAddresses?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .
```

### Network Interfaces

```bash
# List
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/networkInterfaces?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .

# Effective Route Table
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/networkInterfaces/nic-vm-spoke1/effectiveRouteTable?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq .

# Simulate Forwarding
curl -s -X POST "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-hub-spoke/providers/Microsoft.Network/networkInterfaces/nic-vm-spoke1/simulateForwarding?api-version=2023-04-01" -H "Authorization: Bearer faketoken" -H "Content-Type: application/json" -d '{"destinationIp":"10.2.0.4"}' | jq .
```

---

## Verification

### Automated (deploy.sh)

```bash
./deploy.sh
```

Checks:
- Resource group creation
- Deployment completes with `provisioningState: Succeeded`
- VNet peerings return `peeringState: Connected`
- All 3 VNets exist (hub, spoke-1, spoke-2)
- Firewall exists with correct subnet ID
- Route tables exist (rt-spoke1, rt-spoke2)
- Public IP exists (pip-azfw)

### Manual Smoke Tests

```bash
# Quick health check
SUB="00000000-0000-0000-0000-000000000000"
RG="rg-hub-spoke"
BASE="http://localhost:4510"
H="Authorization: Bearer faketoken"

# 1. List All 3 VNets
# curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/virtualNetworks?api-version=2023-04-01" -H "$H" | jq '[.[].name] | sort'

# 1.a
curl -s "${BASE_URL}/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Network/virtualNetworks?api-version=${API_VERSION}" \
  -H "${AUTH_HEADER}" | jq -r '.value[].id | split("/")[-1]'

# OR 

# 1.b
curl -s "${BASE_URL}/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Network/virtualNetworks?api-version=${API_VERSION}" \
  -H "${AUTH_HEADER}" | jq -r '.value[].name'

# 2.0 List all vnet peerings
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/virtualNetworks/vnet-hub/virtualNetworkPeerings?api-version=2023-04-01" -H "$H" | jq '.value[].id'

# 2.1 Peerings are Connected
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/virtualNetworks/vnet-hub/virtualNetworkPeerings/hub-to-spoke1?api-version=2023-04-01" -H "$H" | jq '.peeringState'
# Expected: "Connected"

# 3.0 List firewalls
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/azureFirewalls?api-version=2023-11-01" -H "$H" | jq -r '.value[] | .id,.name'

# 3.1 Firewall has private IP
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/azureFirewalls/fw-hub?api-version=2023-04-01" -H "$H" | jq '.properties.ipConfigurations[0].properties.privateIPAddress'

# 4.0 List routetables
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/routeTables?api-version=2023-04-01" -H "$H" | jq -r '.value[].name'
# Expected: rt-spoke1, rt-spoke2

# 4.1 Route tables have routes
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/routeTables/rt-spoke1?api-version=2023-04-01" -H "$H" | jq '.properties.routes | length'
# Expected: >= 1

# 5.0 List NICs
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces?api-version=2023-04-01" -H "$H" | jq -r '.value[].name'
# Expected: nic-hub, nic-spoke1, nic-spoke2

# 5.1 Effective routes on a NIC
curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-vm-spoke1/effectiveRouteTable?api-version=2023-04-01" -H "$H" | jq '.routes[].addressPrefix'

curl -s "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-vm-spoke2/effectiveRouteTable?api-version=2023-04-01" -H "$H" | jq '.routes[].addressPrefix'

# 6. Forwarding simulation
# curl -s -X POST "$BASE/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-vm-spoke1/simulateForwarding?api-version=2023-04-01" -H "$H" -H "Content-Type: application/json" -d '{"destinationIp":"10.2.0.4"}' | jq .

curl -s -X POST "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-spoke1/simulateForwarding?api-version=2024-05-01" \
  -H "Authorization: Bearer test" \
  -H "Content-Type: application/json" \
  -d '{
    "destinationIp": "10.2.1.4"
  }' \
| jq

# Expected: reachable:true
```

---

## Behavior Differences vs Real Azure

| Behavior | Emulator | Real Azure |
|---|---|---|
| **State persistence** | In-memory only; lost on container restart | Durable ARM backend |
| **Network emulation** | Stub — correct JSON schema, no actual packet forwarding | Full dataplane with VXLAN, hardware switches |
| **Firewall rules** | Stored but never enforced | Full L3-L7 inspection, NAT, SNAT |
| **IPAM** | Deterministic .4+ sequential, never releases | Azure DHCP, dynamic with leases |
| **Route table nextHopIpAddress** | Raw `[reference(...)]` expression text | Resolved IP at deployment time |
| **Peering traffic** | Simulated in forwarding topology traversal | Actual Azure backbone routing |
| **BGP routes** | Not implemented | Full dynamic routing |
| **Auth** | Bearer token not validated | Azure AD + RBAC |
| **Subnet ID generation** | Inline during VNet creation | Already present in ARM templates |
| **Concurrent deployments** | Sequential (single-threaded) | Parallel with optimistic concurrency |
| **Duplicate resource IDs** | Allowed (two firewall entries) | Rejected with conflict error |

---

## Known Limitations

| Issue | Impact | Workaround |
|---|---|---|
| Route table `nextHopIpAddress` is the raw `[reference(...)]` expression | Cosmetic: the value is the expression text, not a real IP | Not needed for POC — no actual routing happens |
| Two firewall entries from separate modules | `deploy-firewall` and `deploy-firewall-rules` both create the same firewall resource | Harmless for POC; lists show 2 entries for fw-hub |
| State lost on container restart | All deployed resources disappear | Must re-run `deploy.sh` after each restart |
| No auth validation | Any bearer token works | Matches LocalStack Azure emulator behavior |
| IPs never freed | IPAM pool exhausts on long-running instances | Restart container to reset |
| No NSG support | Security rules not implemented | Not required for this POC |

---

## Architecture Notes

- **No real network emulation**: All resources are stubs — correct JSON in/out, in-memory state, no packet forwarding, no service chaining, no actual firewall rules enforced
- **State is ephemeral**: Stored in Python dicts, lost on container restart
- **Plugin discovery**: Requires BOTH `@azure_provider` decorator AND entry point in `.dist-info/entry_points.txt`
- **ARM reference resolution**: The `_resolve_reference_expressions()` method is the most critical piece — without it, nested deployments fail silently and the deployment hangs on "Running" forever
- **Subnet IDs are generated**: VNet creation adds `id` fields to inline subnets because the Bicep template doesn't include them and `reference()` navigation needs them
- **Two-level reference chain**: Deployments can be nested 2 levels deep when resolving `[reference(...).outputs.X.value]` where X itself contains `[reference(...)]` — the iterative resolver handles this with up to 5 resolution iterations
- **Route deduplication matters**: Without deduplication, peering routes duplicate VNet-local routes for the same prefix, causing incorrect longest-prefix-match results
- **PeeringState at dual levels**: `peeringState: "Connected"` is stored at both top-level and `properties.peeringState` to satisfy both GET (`[]` access) and LIST (JSONPath) consumers

---

## Development

### Applying Patches to a Fresh Container

```bash
# 1. Start the base image
docker run --rm -it -p 4566:4566 -p 4510:4510 \
  -e ACTIVATE_PRO=0 \
  localstack/localstack-azure-alpha:8a3d8a4e462fe9f3b305f4076a3050e8fd1750de

# 2. Copy patched files
CONTAINER_ID=$(docker ps -ql)
PATCH_DIR="localstack-patches/localstack/pro/azure"

docker cp "$PATCH_DIR/services/resources/deployments/models.py" \
  "$CONTAINER_ID:/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/deployments/models.py"

docker cp "$PATCH_DIR/services/network/models.py" \
  "$CONTAINER_ID:/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/network/models.py"

docker cp "$PATCH_DIR/services/network/provider.py" \
  "$CONTAINER_ID:/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/network/provider.py"

docker cp "$PATCH_DIR/services/plugins.py" \
  "$CONTAINER_ID:/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/plugins.py"

docker cp "$PATCH_DIR/api/core/routing/routing.py" \
  "$CONTAINER_ID:/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/api/core/routing/routing.py"

# 3. Update entry_points.txt
docker cp "$PATCH_DIR/.venv-dist-info/entry_points.txt" \
  "$CONTAINER_ID:/opt/code/localstack/localstack-pro-azure/.venv/lib/python3.11/site-packages/localstack_azure-4.0.4.dist-info/entry_points.txt"

# 4. Restart
docker restart "$CONTAINER_ID"

# 5. Deploy
./deploy.sh
```

### File Reference

All patched files are saved in `localstack-patches/` with full relative paths preserved. The base path within the container is `/opt/code/localstack/localstack-pro-azure/`.

```
localstack-patches/
  localstack/pro/azure/
    services/
      resources/deployments/models.py    ← Deployment engine (reference resolution)
      network/
        models.py                       ← NetworkStore (new)
        provider.py                     ← NetworkImpl CRUD (new)
      plugins.py                       ← @azure_provider registration
    api/core/routing/routing.py         ← 26 Network routes
    .venv-dist-info/entry_points.txt    ← Package metadata entry point
```

---

## Troubleshooting

### Deployment Hangs at "Running"

**Cause:** ARM reference resolution failure — nested deployment parameter contains a `[reference(...)]` that couldn't be resolved.

**Check:**
```bash
# Look for "Deployment failed" or resolution errors
docker logs "$CONTAINER_ID" 2>&1 | grep -i "reference\|resolve\|deployment.*fail"
```

**Fix:** Ensure `_resolve_reference_expressions()` is called before the ARM template parser. Verify the regex patterns match the template's reference format:
- Deployment reference: `[reference(resourceId('Microsoft.Resources/deployments', '...'), ...).outputs.X.value]`
- Resource reference: `[reference(resourceId('Microsoft.Network/...', '...'), ...).path.to.property]`

### Plugin Not Loading (All Routes Return NotImplementedError)

**Cause:** Entry point missing from `.dist-info/entry_points.txt`.

**Fix:**
```bash
# Verify the entry exists inside the container
docker exec "$CONTAINER_ID" grep "Microsoft.Network" /opt/code/localstack/localstack-pro-azure/.venv/lib/python3.11/site-packages/localstack_azure-4.0.4.dist-info/entry_points.txt
# Expected: Microsoft.Network:default = localstack.pro.azure.services.plugins:network
```

### PeeringState Not "Connected"

**Cause:** Peering was created without the top-level `peeringState` field.

**Check:**
```bash
curl -s "http://localhost:4510/subscriptions/.../virtualNetworks/vnet-hub/virtualNetworkPeerings/hub-to-spoke1?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq 'keys'
```

**Fix:** Ensure `peeringState: "Connected"` is set at both `response["peeringState"]` and `response["properties"]["peeringState"]` in the provider's `create_or_update` handler.

### Forwarding Simulation Returns "Blackhole"

**Cause:** Either (a) the route table has no UDR matching the destination, (b) the peering is missing `remoteAddressSpace`, or (c) no NIC exists at the destination.

**Check:**
```bash
# Verify effective routes on source NIC
curl -s "http://localhost:4510/subscriptions/.../networkInterfaces/<nic>/effectiveRouteTable?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq '.routes[].addressPrefix'

# Verify peering has remoteAddressSpace
curl -s "http://localhost:4510/subscriptions/.../virtualNetworks/vnet-hub/virtualNetworkPeerings/hub-to-spoke1?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq '.properties.remoteAddressSpace'

# Verify destination NIC exists
curl -s "http://localhost:4510/subscriptions/.../networkInterfaces?api-version=2023-04-01" -H "Authorization: Bearer faketoken" | jq '[.[].properties.ipConfigurations[].properties.privateIPAddress]'
```

### IPAM Exhausted

All IPs in a subnet have been allocated.

**Check subnet usage:**
```bash
# No direct endpoint; check logs
docker logs "$CONTAINER_ID" 2>&1 | grep -i "ipam\|allocate.*ip\|no.*available"
```

**Fix:** Restart the container to reset IP state, or increase the subnet CIDR.
