import json

from localstack.pro.azure.services.core.exceptions import ResourceNotFound
from localstack.pro.azure.services.resources.models import get_resource_group
from localstack.pro.azure.services.network.models import network_stores, NetworkStore


class NetworkImpl:
    service = "Microsoft.Network"

    @staticmethod
    def get_store(subscription_id: str, location: str) -> NetworkStore:
        return network_stores[subscription_id][location]

    def _find_vnet(self, subscription_id: str, vnet_id: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            if vnet_id in store.virtual_networks:
                return store.virtual_networks[vnet_id]
        return None

    def _find_peering(self, subscription_id: str, peering_id: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            if peering_id in store.peerings:
                return store.peerings[peering_id]
        return None

    def _find_firewall(self, subscription_id: str, fw_id: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            if fw_id in store.firewalls:
                return store.firewalls[fw_id]
        return None

    def _find_route_table(self, subscription_id: str, rt_id: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            if rt_id in store.route_tables:
                return store.route_tables[rt_id]
        return None

    def _find_public_ip(self, subscription_id: str, pip_id: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            if pip_id in store.public_ip_addresses:
                return store.public_ip_addresses[pip_id]
        return None

    def _ok(self, body: dict) -> tuple:
        return (200, {"content-type": "application/json"}, json.dumps(body).encode())

    def _list_in_rg(self, subscription_id: str, rg_name: str, store_key: str) -> list[dict]:
        result = []
        stores = network_stores[subscription_id]
        rg_marker = f"/resourceGroups/{rg_name}/"
        for store in stores.values():
            collection = getattr(store, store_key)
            for res_id, resource in collection.items():
                if rg_marker in res_id:
                    result.append(resource)
        return result

    # -- virtualNetworks --

    def virtual_networks__create_or_update(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["vnetName"]
        get_resource_group(sub, rg)

        body = request.get_json(silent=True) or {}
        location = body.get("location", "eastus")
        props = dict(body.get("properties", {}))
        props["provisioningState"] = "Succeeded"
        props.setdefault("addressSpace", {"addressPrefixes": ["10.0.0.0/16"]})
        props.setdefault("subnets", [])

        vnet = {
            "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{name}",
            "name": name,
            "type": "Microsoft.Network/virtualNetworks",
            "location": location,
            "properties": props,
        }

        store = self.get_store(sub, location)
        store.virtual_networks[vnet["id"]] = vnet
        return self._ok(vnet)

    def virtual_networks__get(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["vnetName"]
        vnet_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{name}"
        vnet = self._find_vnet(sub, vnet_id)
        if not vnet:
            raise ResourceNotFound("Microsoft.Network/virtualNetworks", name, rg)
        return self._ok(vnet)

    def virtual_networks__list(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        return self._ok({"value": self._list_in_rg(sub, rg, "virtual_networks")})

    def virtual_networks__delete(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["vnetName"]
        vnet_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{name}"
        for store in network_stores[sub].values():
            if vnet_id in store.virtual_networks:
                del store.virtual_networks[vnet_id]
                return self._ok({})
        raise ResourceNotFound("Microsoft.Network/virtualNetworks", name, rg)

    # -- virtualNetworkPeerings --

    def virtual_network_peerings__create_or_update(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        vnet_name = parameters["vnetName"]
        peering_name = parameters["peeringName"]

        vnet_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}"
        vnet = self._find_vnet(sub, vnet_id)
        if not vnet:
            raise ResourceNotFound("Microsoft.Network/virtualNetworks", vnet_name, rg)

        peering_id = f"{vnet_id}/virtualNetworkPeerings/{peering_name}"
        body = request.get_json(silent=True) or {}
        props = dict(body.get("properties", {}))

        props["provisioningState"] = "Succeeded"
        props["peeringState"] = "Connected"

        remote_id = props.get("remoteVirtualNetwork", {}).get("id", "")
        if remote_id:
            remote = self._find_vnet(sub, remote_id)
            if remote:
                props["remoteAddressSpace"] = {
                    "addressPrefixes": remote.get("properties", {})
                        .get("addressSpace", {})
                        .get("addressPrefixes", [])
                }
        props.setdefault("remoteAddressSpace", {"addressPrefixes": []})
        props.setdefault("allowVirtualNetworkAccess", True)
        props.setdefault("allowForwardedTraffic", True)
        props.setdefault("allowGatewayTransit", True)
        props.setdefault("useRemoteGateways", False)

        peering = {
            "id": peering_id,
            "name": peering_name,
            "type": "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
            "properties": props,
        }

        location = vnet.get("location", "eastus")
        self.get_store(sub, location).peerings[peering_id] = peering
        return self._ok(peering)

    def virtual_network_peerings__get(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        vnet_name = parameters["vnetName"]
        peering_name = parameters["peeringName"]
        peering_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/virtualNetworkPeerings/{peering_name}"
        peering = self._find_peering(sub, peering_id)
        if not peering:
            raise ResourceNotFound("Microsoft.Network/virtualNetworks/virtualNetworkPeerings", peering_name, rg)
        return self._ok(peering)

    def virtual_network_peerings__list(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        vnet_name = parameters["vnetName"]
        prefix = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/virtualNetworkPeerings/"
        result = []
        for store in network_stores[sub].values():
            for p_id, peering in store.peerings.items():
                if p_id.startswith(prefix):
                    result.append(peering)
        return self._ok({"value": result})

    def virtual_network_peerings__delete(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        vnet_name = parameters["vnetName"]
        peering_name = parameters["peeringName"]
        peering_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/virtualNetworkPeerings/{peering_name}"
        for store in network_stores[sub].values():
            if peering_id in store.peerings:
                del store.peerings[peering_id]
                return self._ok({})
        raise ResourceNotFound("Microsoft.Network/virtualNetworks/virtualNetworkPeerings", peering_name, rg)

    # -- azureFirewalls --

    def azure_firewalls__create_or_update(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["firewallName"]
        get_resource_group(sub, rg)

        body = request.get_json(silent=True) or {}
        location = body.get("location", "eastus")
        props = dict(body.get("properties", {}))
        props["provisioningState"] = "Succeeded"
        props.setdefault("ipConfigurations", [
            {
                "name": "fw-ipconfig",
                "properties": {
                    "privateIPAddress": "10.0.2.4",
                    "provisioningState": "Succeeded",
                },
            }
        ])
        props.setdefault("networkRuleCollections", [])

        firewall = {
            "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls/{name}",
            "name": name,
            "type": "Microsoft.Network/azureFirewalls",
            "location": location,
            "properties": props,
        }

        self.get_store(sub, location).firewalls[firewall["id"]] = firewall
        return self._ok(firewall)

    def azure_firewalls__get(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["firewallName"]
        fw_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls/{name}"
        fw = self._find_firewall(sub, fw_id)
        if not fw:
            raise ResourceNotFound("Microsoft.Network/azureFirewalls", name, rg)
        return self._ok(fw)

    def azure_firewalls__list(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        return self._ok({"value": self._list_in_rg(sub, rg, "firewalls")})

    def azure_firewalls__delete(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["firewallName"]
        fw_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls/{name}"
        for store in network_stores[sub].values():
            if fw_id in store.firewalls:
                del store.firewalls[fw_id]
                return self._ok({})
        raise ResourceNotFound("Microsoft.Network/azureFirewalls", name, rg)

    # -- routeTables --

    def route_tables__create_or_update(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["routeTableName"]
        get_resource_group(sub, rg)

        body = request.get_json(silent=True) or {}
        location = body.get("location", "eastus")
        props = dict(body.get("properties", {}))
        props["provisioningState"] = "Succeeded"
        props.setdefault("routes", [])

        rt = {
            "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/routeTables/{name}",
            "name": name,
            "type": "Microsoft.Network/routeTables",
            "location": location,
            "properties": props,
        }

        self.get_store(sub, location).route_tables[rt["id"]] = rt
        return self._ok(rt)

    def route_tables__get(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["routeTableName"]
        rt_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/routeTables/{name}"
        rt = self._find_route_table(sub, rt_id)
        if not rt:
            raise ResourceNotFound("Microsoft.Network/routeTables", name, rg)
        return self._ok(rt)

    # -- publicIPAddresses --

    def public_ip_addresses__create_or_update(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["publicIPName"]
        get_resource_group(sub, rg)

        body = request.get_json(silent=True) or {}
        location = body.get("location", "eastus")
        props = dict(body.get("properties", {}))
        props["provisioningState"] = "Succeeded"
        props.setdefault("publicIPAllocationMethod", "Static")
        props.setdefault("ipAddress", "20.0.0.1")

        pip = {
            "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/publicIPAddresses/{name}",
            "name": name,
            "type": "Microsoft.Network/publicIPAddresses",
            "location": location,
            "sku": body.get("sku", {"name": "Standard"}),
            "properties": props,
        }

        self.get_store(sub, location).public_ip_addresses[pip["id"]] = pip
        return self._ok(pip)

    def public_ip_addresses__get(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["publicIPName"]
        pip_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/publicIPAddresses/{name}"
        pip = self._find_public_ip(sub, pip_id)
        if not pip:
            raise ResourceNotFound("Microsoft.Network/publicIPAddresses", name, rg)
        return self._ok(pip)
