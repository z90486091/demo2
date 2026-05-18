#!/usr/bin/env python3

PROVIDER_PATH = "/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/network/provider.py"

with open(PROVIDER_PATH, "r") as f:
    content = f.read()

subnet_methods = '''

    # -- subnets --

    def _find_vnet_store(self, subscription_id: str, vnet_id: str) -> tuple[dict | None, Any]:
        for store in network_stores[subscription_id].values():
            if vnet_id in store.virtual_networks:
                return store.virtual_networks[vnet_id], store
        return None, None

    def virtual_networks_subnets__create_or_update(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        vnet_name = parameters["vnetName"]
        subnet_name = parameters["subnetName"]
        vnet_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}"
        vnet, store = self._find_vnet_store(sub, vnet_id)
        if not vnet:
            raise ResourceNotFound("Microsoft.Network/virtualNetworks", vnet_name, rg)

        body = request.get_json(silent=True) or {}
        props = dict(body.get("properties", {}))
        props["provisioningState"] = "Succeeded"

        subnet_id = f"{vnet_id}/subnets/{subnet_name}"
        subnet = {
            "id": subnet_id,
            "name": subnet_name,
            "type": "Microsoft.Network/virtualNetworks/subnets",
            "properties": props,
        }

        # Update or add to VNet's subnets list
        vnet_props = vnet.setdefault("properties", {})
        vnet_subnets = vnet_props.setdefault("subnets", [])
        found = False
        for i, s in enumerate(vnet_subnets):
            if s.get("name") == subnet_name:
                vnet_subnets[i] = subnet
                found = True
                break
        if not found:
            vnet_subnets.append(subnet)
        # Also store standalone in the subnet collection
        store.subnets[subnet_id] = subnet
        return self._ok(subnet)

    def virtual_networks_subnets__get(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        vnet_name = parameters["vnetName"]
        subnet_name = parameters["subnetName"]
        subnet_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/subnets/{subnet_name}"
        # Check store first, then VNet properties
        for store in network_stores[sub].values():
            if subnet_id in store.subnets:
                return self._ok(store.subnets[subnet_id])
        vnet_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}"
        for store in network_stores[sub].values():
            if vnet_id in store.virtual_networks:
                vnet = store.virtual_networks[vnet_id]
                for s in vnet.get("properties", {}).get("subnets", []):
                    if s.get("name") == subnet_name:
                        return self._ok(s)
        raise ResourceNotFound("Microsoft.Network/virtualNetworks/subnets", subnet_name, rg)

    def virtual_networks_subnets__list(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        vnet_name = parameters["vnetName"]
        vnet_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}"
        for store in network_stores[sub].values():
            if vnet_id in store.virtual_networks:
                subnets = store.virtual_networks[vnet_id].get("properties", {}).get("subnets", [])
                return self._ok({"value": subnets})
        return self._ok({"value": []})
'''

# Insert before the end of the class (before last newline)
content = content.rstrip() + "\n" + subnet_methods.strip() + "\n"

with open(PROVIDER_PATH, "w") as f:
    f.write(content)

print("Provider patched with subnet methods")
