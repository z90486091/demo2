import ast

PATH = '/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/api/core/routing/routing.py'

with open(PATH) as f:
    content = f.read()

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

# Insert after the last },, before the ], that precedes "PUT":
old_get_end = '    ],\n    "PUT": ['
assert old_get_end in content, "GET marker not found"
content = content.replace(old_get_end, GET_ROUTES.rstrip('\n') + '\n' + old_get_end, 1)

old_put_end = '    ],\n    "DELETE": ['
assert old_put_end in content, "PUT marker not found"
content = content.replace(old_put_end, PUT_ROUTES.rstrip('\n') + '\n' + old_put_end, 1)

old_delete_end = '    ],\n    "PATCH": ['
assert old_delete_end in content, "DELETE marker not found"
content = content.replace(old_delete_end, DELETE_ROUTES.rstrip('\n') + '\n' + old_delete_end, 1)

try:
    ast.parse(content)
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR line {e.lineno}: {e.msg}")

with open(PATH, 'w') as f:
    f.write(content)

# Final verification
net_count = content.count('Microsoft.Network')
print(f"Microsoft.Network count: {net_count}")
