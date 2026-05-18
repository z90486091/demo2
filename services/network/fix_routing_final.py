import ast

PATH = '/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/api/core/routing/routing.py'

with open(PATH) as f:
    lines = f.readlines()

GET_ROUTES = '''        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks$",
            "method": "virtual_networks__list",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>.*)$",
            "method": "virtual_networks__get",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>[^/]*)/virtualNetworkPeerings$",
            "method": "virtual_network_peerings__list",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>[^/]*)/virtualNetworkPeerings/(?P<peeringName>.*)$",
            "method": "virtual_network_peerings__get",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/azureFirewalls$",
            "method": "azure_firewalls__list",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/azureFirewalls/(?P<firewallName>.*)$",
            "method": "azure_firewalls__get",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/routeTables/(?P<routeTableName>.*)$",
            "method": "route_tables__get",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/publicIPAddresses/(?P<publicIPName>.*)$",
            "method": "public_ip_addresses__get",
        },
'''

PUT_ROUTES = '''        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>.*)$",
            "method": "virtual_networks__create_or_update",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>[^/]*)/virtualNetworkPeerings/(?P<peeringName>.*)$",
            "method": "virtual_network_peerings__create_or_update",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/azureFirewalls/(?P<firewallName>.*)$",
            "method": "azure_firewalls__create_or_update",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/routeTables/(?P<routeTableName>.*)$",
            "method": "route_tables__create_or_update",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/publicIPAddresses/(?P<publicIPName>.*)$",
            "method": "public_ip_addresses__create_or_update",
        },
'''

DELETE_ROUTES = '''        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>.*)$",
            "method": "virtual_networks__delete",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>[^/]*)/virtualNetworkPeerings/(?P<peeringName>.*)$",
            "method": "virtual_network_peerings__delete",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/azureFirewalls/(?P<firewallName>.*)$",
            "method": "azure_firewalls__delete",
        },
'''

# Remove all existing Network entry blocks
new_lines = []
i = 0
while i < len(lines):
    stripped = lines[i].strip()
    if stripped == '        {' and i + 1 < len(lines) and 'Microsoft.Network' in lines[i + 1]:
        depth = 1
        i += 1
        while i < len(lines) and depth > 0:
            s = lines[i].strip()
            if '{' in s:
                depth += s.count('{')
            if '}' in s:
                depth -= s.count('}')
            i += 1
        continue
    new_lines.append(lines[i])
    i += 1

print(f"Removed Network blocks: {len(lines)} -> {len(new_lines)} lines")

content = ''.join(new_lines)
network_count = content.count('Microsoft.Network')
print(f"Microsoft.Network remaining: {network_count}")

if network_count > 0:
    # Find and print where they are
    for j, line in enumerate(content.split('\n')):
        if 'Microsoft.Network' in line:
            print(f"  Remaining at line {j+1}: {line.strip()}")

# Insert routes
markers = [
    ('GET', GET_ROUTES, '    ],\n    "PUT": ['),
    ('PUT', PUT_ROUTES, '    ],\n    "DELETE": ['),
    ('DELETE', DELETE_ROUTES, '    ],\n    "PATCH": ['),
]

for name, routes, marker in markers:
    if marker in content:
        content = content.replace(marker, routes.rstrip('\n') + '\n' + marker, 1)
        print(f"Inserted {name}")
    else:
        print(f"ERROR: {name} marker missing!")

try:
    ast.parse(content)
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR line {e.lineno}: {e.msg}")
    clines = content.split('\n')
    if e.lineno:
        for j in range(max(0, e.lineno - 5), min(len(clines), e.lineno + 3)):
            print(f"  {j+1}: {clines[j]}")

with open(PATH, 'w') as f:
    f.write(content)
