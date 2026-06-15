#!/usr/bin/env python3
import re

ROUTING_PATH = "/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/api/core/routing/routing.py"

with open(ROUTING_PATH, "r") as f:
    content = f.read()

# Insert in GET section: after peering route, before azureFirewalls
get_entry = '''            "method": "virtual_network_peerings__get",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>[^/]*)/subnets/(?P<subnetName>[^/]*)$",
            "method": "virtual_networks_subnets__get",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>[^/]*)/subnets$",
            "method": "virtual_networks_subnets__list",
        },
        {'''

old_get = '''            "method": "virtual_network_peerings__get",
        },
        {'''
content = content.replace(old_get, get_entry, 1)

# Insert in PUT section: after peering route, before azureFirewalls
put_entry = '''            "method": "virtual_network_peerings__create_or_update",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/virtualNetworks/(?P<vnetName>[^/]*)/subnets/(?P<subnetName>[^/]*)$",
            "method": "virtual_networks_subnets__create_or_update",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/azureFirewalls/(?P<firewallName>.*)$",'''

old_put = '''            "method": "virtual_network_peerings__create_or_update",
        },
        {
            "provider": "Microsoft.Network",
            "path": "^/subscriptions/(?P<subscriptionId>[^/]*)/resourceGroups/(?P<resourceGroupName>[^/]*)/providers/Microsoft.Network/azureFirewalls/(?P<firewallName>.*)$",'''

content = content.replace(old_put, put_entry, 1)

with open(ROUTING_PATH, "w") as f:
    f.write(content)

print("Routing patched successfully")
