#!/bin/bash
# Hub-and-Spoke POC — LocalStack deployment script
# Prerequisites:
#   - LocalStack running: docker run --rm -it -p 4566:4566 -p 4510:4510 \
#       -e ACTIVATE_PRO=0 \
#       localstack/localstack-azure-alpha:8a3d8a4e462fe9f3b305f4076a3050e8fd1750de
#   - az bicep installed: az bicep install

set -e

ENDPOINT="http://localhost:4510"
SUB="00000000-0000-0000-0000-000000000000"
RG="rg-hub-spoke"
TOKEN="faketoken"
API_VER="2021-04-01"

echo ""
echo "================================================"
echo " Hub-and-Spoke POC — LocalStack Deployment"
echo "================================================"

# ── Build Bicep → ARM JSON ───────────────────────────
echo ""
echo "▶ Compiling main.bicep..."
az bicep build --file main.bicep --outfile main.json
echo "  ✓ main.json generated"

# ── Create Resource Group ────────────────────────────
echo ""
echo "▶ Creating resource group: $RG..."
curl -s -X PUT \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG?api-version=$API_VER" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"location": "eastus"}' | python3 -m json.tool
echo "  ✓ Resource group created"

# ── Deploy ───────────────────────────────────────────
echo ""
echo "▶ Deploying hub-and-spoke topology..."
DEPLOY_RESULT=$(curl -s -X PUT \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Resources/deployments/hub-spoke-deploy?api-version=$API_VER" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"properties\": {\"mode\": \"Incremental\", \"template\": $(cat main.json)}}")

echo "$DEPLOY_RESULT" | python3 -m json.tool
echo ""

# Poll until done
echo "▶ Waiting for deployment to complete..."
for i in {1..120}; do
  sleep 3
  RESP=$(curl -s \
    "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Resources/deployments/hub-spoke-deploy?api-version=$API_VER" \
    -H "Authorization: Bearer $TOKEN")
  STATUS=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['properties']['provisioningState'])" 2>/dev/null || echo "Unknown")
  echo "  Status: $STATUS"
  if [ "$STATUS" = "Succeeded" ] || [ "$STATUS" = "Failed" ]; then
    break
  fi
  if [ "$STATUS" != "Running" ] && [ "$STATUS" != "Accepted" ]; then
    echo "  Full response for diagnosis:"
    echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"
    break
  fi
done

echo ""
echo "================================================"
echo " Verification"
echo "================================================"

# ── Verify 1: Peering status ─────────────────────────
echo ""
echo "▶ Verify 1: VNet Peering status (hub)..."
curl -s \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/virtualNetworks/vnet-hub/virtualNetworkPeerings?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# ── Verify 2: VNets exist ────────────────────────────
echo ""
echo "▶ Verify 2: All VNets in resource group..."
curl -s \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/virtualNetworks?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
vnets = data.get('value', [])
print(f'  Found {len(vnets)} VNet(s):')
for v in vnets:
    name = v.get('name', '?')
    prefixes = v.get('properties', {}).get('addressSpace', {}).get('addressPrefixes', [])
    print(f'    ✓ {name}: {prefixes}')
"

# ── Verify 3: Firewall ─────────────────────────────
echo ""
echo "▶ Verify 3: Azure Firewall..."
FW=$(curl -s \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/azureFirewalls/fw-hub?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN")
FW_SUBNET=$(echo "$FW" | python3 -c "import sys,json; d=json.load(sys.stdin); ips=d.get('properties',{}).get('ipConfigurations',[]); print(ips[0]['properties'].get('subnet',{}).get('id','?')) if ips else print('?')" 2>/dev/null)
echo "  ✓ fw-hub (subnet: $FW_SUBNET)"

# ── Verify 4: Route Tables ─────────────────────────
echo ""
echo "▶ Verify 4: Route Tables..."
curl -s \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/routeTables?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
rts = data.get('value', [])
print(f'  Found {len(rts)} route table(s):')
for r in rts:
    print(f'    ✓ {r.get(\"name\",\"?\")}')
"

# ── Verify 5: Public IP ────────────────────────────
echo ""
echo "▶ Verify 5: Public IP Addresses..."
curl -s \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/publicIPAddresses?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
pips = data.get('value', [])
print(f'  Found {len(pips)} public IP(s):')
for p in pips:
    print(f'    ✓ {p.get(\"name\",\"?\")}')
"

# ── Verify 6: Firewall private IP ──────────────────
echo ""
echo "▶ Verify 6: Firewall private IP allocation..."
FW=$(curl -s \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/azureFirewalls/fw-hub?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN")
FW_IP=$(echo "$FW" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ips = d.get('properties',{}).get('ipConfigurations',[])
if ips:
    pvt = ips[0].get('properties',{}).get('privateIPAddress','?')
    print(f'  Firewall private IP: {pvt}')
else:
    print('  No ipConfigurations found')
" 2>/dev/null)
echo "$FW_IP"

# ── Verify 7: Created NIC resource (if any) ───────
echo ""
echo "▶ Verify 7: Network Interfaces..."
curl -s \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
nics = data.get('value', [])
print(f'  Found {len(nics)} NIC(s):')
for n in nics:
    print(f'    {n.get(\"name\",\"?\")}')
"

# ── Verify 8: Create test NICs ────────────────────
echo ""
echo "▶ Verify 8: Creating test NICs for forwarding tests..."
create_nic() {
  local name=$1 subnet_path=$2
  python3 -c "
import subprocess, json
subnet_id = '/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Network/virtualNetworks/$subnet_path'
body = {'location': 'eastus', 'properties': {'ipConfigurations': [{'name': 'ipconfig1', 'properties': {'subnet': {'id': subnet_id}, 'privateIPAllocationMethod': 'Dynamic'}}]}}
url = '$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/$name?api-version=2023-04-01'
r = subprocess.run(['curl', '-s', '-X', 'PUT', url, '-H', 'Authorization: Bearer $TOKEN', '-H', 'Content-Type: application/json', '-d', json.dumps(body)], capture_output=True, text=True)
d = json.loads(r.stdout)
ip = d.get('properties',{}).get('ipConfigurations',[{}])[0].get('properties',{}).get('privateIPAddress','?')
print(ip)
"
}
HUB_NIC_IP=$(create_nic "nic-hub" "vnet-hub/subnets/snet-shared-services")
SP1_NIC_IP=$(create_nic "nic-spoke1" "vnet-spoke-1/subnets/snet-workload")
SP2_NIC_IP=$(create_nic "nic-spoke2" "vnet-spoke-2/subnets/snet-workload")
echo "  nic-hub=$HUB_NIC_IP  nic-spoke1=$SP1_NIC_IP  nic-spoke2=$SP2_NIC_IP"

# ── Verify 9: Simulate Forwarding Tests ───────────
echo ""
echo "▶ Verify 9a: effectiveRouteTable (hub NIC)..."
curl -s \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-hub/effectiveRouteTable?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin)
for r in d.get('value',[]):
    print(f\"  {r['name']:20s} {r['addressPrefix']:18s} {r['nextHopType']}\")
"

echo ""
echo "▶ Verify 9b: Spoke-1 → Spoke-2 via Firewall (UDR)..."
curl -s -X POST \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-spoke1/simulateForwarding?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"networkInterface\": {\"id\": \"/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-spoke1\"}, \"destinationIp\": \"$SP2_NIC_IP\"}" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f\"  reachable={d['reachable']}  matchedRoute={d['matchedRoute']}\")
print(f\"  path={' → '.join(d['path'])}\")
"

echo ""
echo "▶ Verify 9c: Hub → Spoke-1 via Peering..."
curl -s -X POST \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-hub/simulateForwarding?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"networkInterface\": {\"id\": \"/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-hub\"}, \"destinationIp\": \"$SP1_NIC_IP\"}" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f\"  reachable={d['reachable']}  matchedRoute={d['matchedRoute']}\")
print(f\"  path={' → '.join(d['path'])}\")
"

echo ""
echo "▶ Verify 9d: Hub → Internet..."
curl -s -X POST \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-hub/simulateForwarding?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"networkInterface\": {\"id\": \"/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-hub\"}, \"destinationIp\": \"8.8.8.8\"}" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f\"  reachable={d['reachable']}  matchedRoute={d['matchedRoute']}\")
"

echo ""
echo "▶ Verify 9e: Spoke-1 → Local VNet..."
curl -s -X POST \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-spoke1/simulateForwarding?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"networkInterface\": {\"id\": \"/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-spoke1\"}, \"destinationIp\": \"$SP1_NIC_IP\"}" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f\"  reachable={d['reachable']}  matchedRoute={d['matchedRoute']}\")
print(f\"  path={' → '.join(d['path'])}\")
"

echo ""
echo "▶ Verify 9f: Hub → AzureFirewallSubnet IP..."
curl -s -X POST \
  "$ENDPOINT/subscriptions/$SUB/resourcegroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-hub/simulateForwarding?api-version=2023-04-01" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"networkInterface\": {\"id\": \"/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Network/networkInterfaces/nic-hub\"}, \"destinationIp\": \"10.0.2.4\"}" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f\"  reachable={d['reachable']}  matchedRoute={d['matchedRoute']}\")
print(f\"  path={' → '.join(d['path'])}\")
"

echo ""
echo "================================================"
echo " All resources deployed successfully!"
echo "================================================"
