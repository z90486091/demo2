# Insert Network routes into routing.py

GET_ROUTES = r"""        {
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
"""

PUT_ROUTES = r"""        {
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
"""

DELETE_ROUTES = r"""        {
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
"""

with open('/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/api/core/routing/routing.py') as f:
    content = f.read()

# Insert into GET list (before PUT):
old_get_end = '        },\n    ],\n    "PUT": ['
content = content.replace(old_get_end, GET_ROUTES.rstrip('\n') + '\n' + old_get_end, 1)

# Insert into PUT list (before DELETE):
old_put_end = '        },\n    ],\n    "DELETE": ['
content = content.replace(old_put_end, PUT_ROUTES.rstrip('\n') + '\n' + old_put_end, 1)

# Insert into DELETE list (before PATCH):
old_delete_end = '        },\n    ],\n    "PATCH": ['
content = content.replace(old_delete_end, DELETE_ROUTES.rstrip('\n') + '\n' + old_delete_end, 1)

with open('/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/api/core/routing/routing.py', 'w') as f:
    f.write(content)

print("Routes inserted successfully")
