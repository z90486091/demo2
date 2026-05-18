import ipaddress
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

    def _find_subnet(self, subscription_id: str, subnet_id: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            if subnet_id in store.subnets:
                return store.subnets[subnet_id]
        return None

    def _find_nic(self, subscription_id: str, nic_id: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            if nic_id in store.network_interfaces:
                return store.network_interfaces[nic_id]
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

    # ── IPAM (Private IP Allocation) ──────────────────────────────────

    def _parse_cidr(self, cidr: str) -> tuple | None:
        try:
            net = ipaddress.IPv4Network(cidr, strict=False)
            return net
        except Exception:
            return None

    def _allocate_private_ip(self, subscription_id: str, subnet_id: str) -> str | None:
        subnet = self._find_subnet(subscription_id, subnet_id)
        if not subnet:
            return None
        addr_prefix = subnet.get("properties", {}).get("addressPrefix", "")
        net = self._parse_cidr(addr_prefix)
        if not net:
            return None

        hosts = list(net.hosts())
        if len(hosts) < 5:
            return None
        # Azure reserves: .0 network, .1 gateway, .2-.3 Azure reserved
        # First allocatable is index 3 (the 4th host = .4)
        allocatable = [str(h) for h in hosts[3:]]

        # Check existing allocations for this subnet
        allocated = set()
        for store in network_stores[subscription_id].values():
            if subnet_id in store.private_ip_allocations:
                allocated = set(store.private_ip_allocations[subnet_id])

        for ip in allocatable:
            if ip not in allocated:
                # Persist the allocation
                for store in network_stores[subscription_id].values():
                    if subnet_id in store.subnets or subnet_id in store.private_ip_allocations:
                        if subnet_id not in store.private_ip_allocations:
                            store.private_ip_allocations[subnet_id] = []
                        store.private_ip_allocations[subnet_id].append(ip)
                        return ip
                # If no existing store found, allocate on any store
                for store in network_stores[subscription_id].values():
                    if subnet_id not in store.private_ip_allocations:
                        store.private_ip_allocations[subnet_id] = []
                    store.private_ip_allocations[subnet_id].append(ip)
                    return ip
        return None

    # ── virtualNetworks ──────────────────────────────────────────────

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

        vnet_subnets = vnet.get("properties", {}).get("subnets", [])
        for subnet in vnet_subnets:
            subnet_name = subnet.get("name")
            if subnet_name and "id" not in subnet:
                subnet["id"] = "{}".format(vnet["id"] + "/subnets/" + subnet_name)
            if subnet.get("id"):
                store.subnets[subnet["id"]] = subnet

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

    # ── virtualNetworkPeerings ──────────────────────────────────────

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
            "peeringState": props["peeringState"],
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

    # ── azureFirewalls ──────────────────────────────────────────────

    def _find_firewall_subnet_id(self, props: dict) -> str | None:
        ip_configs = props.get("ipConfigurations", [])
        for cfg in ip_configs:
            subnet = cfg.get("properties", {}).get("subnet", {})
            if isinstance(subnet, dict):
                sid = subnet.get("id", "")
                if sid:
                    return sid
        return None

    def azure_firewalls__create_or_update(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["firewallName"]
        get_resource_group(sub, rg)

        body = request.get_json(silent=True) or {}
        location = body.get("location", "eastus")
        props = dict(body.get("properties", {}))
        props["provisioningState"] = "Succeeded"

        # Allocate private IP from attached subnet
        subnet_id = self._find_firewall_subnet_id(props)
        private_ip = None
        if subnet_id:
            private_ip = self._allocate_private_ip(sub, subnet_id)
        if not private_ip:
            private_ip = "10.0.1.4"  # fallback

        props.setdefault("ipConfigurations", [
            {
                "name": "fw-ipconfig",
                "properties": {
                    "privateIPAddress": private_ip,
                    "provisioningState": "Succeeded",
                },
            }
        ])
        # Update ipConfigurations that already exist with the allocated IP
        for cfg in props.get("ipConfigurations", []):
            cfg_props = cfg.setdefault("properties", {})
            if "privateIPAddress" not in cfg_props or cfg_props["privateIPAddress"] in (None, ""):
                cfg_props["privateIPAddress"] = private_ip
            if "provisioningState" not in cfg_props:
                cfg_props["provisioningState"] = "Succeeded"

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

    # ── routeTables ─────────────────────────────────────────────────

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

    def route_tables__list(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        return self._ok({"value": self._list_in_rg(sub, rg, "route_tables")})

    # ── publicIPAddresses ───────────────────────────────────────────

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

    def public_ip_addresses__list(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        return self._ok({"value": self._list_in_rg(sub, rg, "public_ip_addresses")})

    # ── subnets ─────────────────────────────────────────────────────

    def _find_vnet_store(self, subscription_id: str, vnet_id: str) -> tuple:
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
        store.subnets[subnet_id] = subnet
        return self._ok(subnet)

    def virtual_networks_subnets__get(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        vnet_name = parameters["vnetName"]
        subnet_name = parameters["subnetName"]
        subnet_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/subnets/{subnet_name}"
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

    # ── networkInterfaces ──────────────────────────────────────────

    def network_interfaces__create_or_update(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["networkInterfaceName"]
        get_resource_group(sub, rg)

        body = request.get_json(silent=True) or {}
        location = body.get("location", "eastus")
        props = dict(body.get("properties", {}))
        props["provisioningState"] = "Succeeded"
        props.setdefault("ipConfigurations", [])

        # Allocate private IPs for each ipConfiguration
        for ip_cfg in props.get("ipConfigurations", []):
            ip_props = ip_cfg.setdefault("properties", {})
            subnet_id = ip_props.get("subnet", {}).get("id", "")
            if subnet_id and ("privateIPAddress" not in ip_props or not ip_props["privateIPAddress"]):
                allocated = self._allocate_private_ip(sub, subnet_id)
                if allocated:
                    ip_props["privateIPAddress"] = allocated
            ip_props.setdefault("privateIPAllocationMethod", "Dynamic")
            ip_props.setdefault("provisioningState", "Succeeded")

        # Set default privateIPAddress if ipConfigurations is empty
        if not props.get("ipConfigurations"):
            props["ipConfigurations"] = [
                {
                    "name": "ipconfig1",
                    "properties": {
                        "privateIPAddress": "10.0.0.4",
                        "privateIPAllocationMethod": "Dynamic",
                        "provisioningState": "Succeeded",
                    },
                }
            ]

        nic = {
            "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{name}",
            "name": name,
            "type": "Microsoft.Network/networkInterfaces",
            "location": location,
            "properties": props,
        }

        self.get_store(sub, location).network_interfaces[nic["id"]] = nic
        return self._ok(nic)

    def network_interfaces__get(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["networkInterfaceName"]
        nic_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{name}"
        nic = self._find_nic(sub, nic_id)
        if not nic:
            raise ResourceNotFound("Microsoft.Network/networkInterfaces", name, rg)
        return self._ok(nic)

    def network_interfaces__list(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        return self._ok({"value": self._list_in_rg(sub, rg, "network_interfaces")})

    # ── Effective Route Table Engine ───────────────────────────────

    def _get_subnet_route_table(self, subnet: dict) -> dict | None:
        rt_ref = subnet.get("properties", {}).get("routeTable", {})
        rt_id = ""
        if isinstance(rt_ref, dict):
            rt_id = rt_ref.get("id", "")
        if not rt_id:
            return None
        for store in network_stores.values():
            for s in store.values():
                if rt_id in s.route_tables:
                    return s.route_tables[rt_id]
        return None

    def _get_vnet_by_subnet_id(self, subscription_id: str, subnet_id: str) -> dict | None:
        parts = subnet_id.split("/virtualNetworks/")
        if len(parts) < 2:
            return None
        vnet_part = parts[1].split("/subnets/")[0]
        vnet_id = parts[0] + "/virtualNetworks/" + vnet_part
        for store in network_stores[subscription_id].values():
            if vnet_id in store.virtual_networks:
                return store.virtual_networks[vnet_id]
        return None

    def _get_vnet_peerings(self, subscription_id: str, vnet_id: str) -> list[dict]:
        prefix = vnet_id + "/virtualNetworkPeerings/"
        peerings = []
        for store in network_stores[subscription_id].values():
            for p_id, peering in store.peerings.items():
                if p_id.startswith(prefix):
                    peerings.append(peering)
        return peerings

    def _cidr_prefix_to_int(self, cidr: str) -> int:
        try:
            net = ipaddress.IPv4Network(cidr, strict=False)
            return net.prefixlen
        except Exception:
            return 0

    def _get_nic_subnet_id(self, nic: dict) -> str | None:
        for ip_cfg in nic.get("properties", {}).get("ipConfigurations", []):
            sid = ip_cfg.get("properties", {}).get("subnet", {}).get("id", "")
            if sid:
                return sid
        return None

    def _find_subnet_by_ip_in_vnet(self, vnet: dict, ip: str) -> dict | None:
        for subnet in vnet.get("properties", {}).get("subnets", []):
            prefix = subnet.get("properties", {}).get("addressPrefix", "")
            if prefix and self._ip_in_prefix(ip, prefix):
                return subnet
        return None

    def _find_nic_by_ip(self, subscription_id: str, ip: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            for nic_id, nic in store.network_interfaces.items():
                for cfg in nic.get("properties", {}).get("ipConfigurations", []):
                    cfg_ip = cfg.get("properties", {}).get("privateIPAddress", "")
                    if cfg_ip == ip:
                        return nic
        return None

    def _find_peering_by_name_in_vnet(self, subscription_id: str, vnet: dict, peering_name: str) -> dict | None:
        peerings = self._get_vnet_peerings(subscription_id, vnet["id"])
        for p in peerings:
            if p.get("name") == peering_name:
                return p
        return None

    def _compute_effective_routes_for_subnet(self, subscription_id: str, subnet: dict | None, vnet: dict, include_udr: bool = True) -> list[dict]:
        effective_routes = []

        vnet_prefixes = vnet.get("properties", {}).get("addressSpace", {}).get("addressPrefixes", [])
        for prefix in vnet_prefixes:
            effective_routes.append({
                "name": "VNet-local",
                "source": "Default",
                "state": "Active",
                "addressPrefix": prefix,
                "nextHopType": "VNetLocal",
                "nextHopIpAddress": "",
            })

        effective_routes.append({
            "name": "Internet",
            "source": "Default",
            "state": "Active",
            "addressPrefix": "0.0.0.0/0",
            "nextHopType": "Internet",
            "nextHopIpAddress": "",
        })

        if include_udr and subnet:
            rt = self._get_subnet_route_table(subnet)
            if rt:
                for route in rt.get("properties", {}).get("routes", []):
                    route_props = route.get("properties", {})
                    effective_routes.append({
                        "name": route.get("name", "UDR"),
                        "source": "User",
                        "state": "Active",
                        "addressPrefix": route_props.get("addressPrefix", ""),
                        "nextHopType": route_props.get("nextHopType", "VirtualAppliance"),
                        "nextHopIpAddress": route_props.get("nextHopIpAddress", ""),
                    })

        peerings = self._get_vnet_peerings(subscription_id, vnet["id"])
        for peering in peerings:
            peering_props = peering.get("properties", {})
            if peering_props.get("peeringState") != "Connected":
                continue
            if not peering_props.get("allowVirtualNetworkAccess", True):
                continue
            remote_address_space = peering_props.get("remoteAddressSpace", {}).get("addressPrefixes", [])
            for prefix in remote_address_space:
                effective_routes.append({
                    "name": peering.get("name", "Peering"),
                    "source": "Default",
                    "state": "Active",
                    "addressPrefix": prefix,
                    "nextHopType": "VNetPeering",
                    "nextHopIpAddress": "",
                })

        seen = {}
        for route in effective_routes:
            prefix = route["addressPrefix"]
            source_prio = 0 if route["source"] == "User" else 1
            prefix_len = self._cidr_prefix_to_int(prefix)
            if prefix not in seen:
                seen[prefix] = route
            else:
                existing = seen[prefix]
                existing_source_prio = 0 if existing["source"] == "User" else 1
                existing_prefix_len = self._cidr_prefix_to_int(existing["addressPrefix"])
                if source_prio < existing_source_prio:
                    seen[prefix] = route
                elif source_prio == existing_source_prio and prefix_len > existing_prefix_len:
                    seen[prefix] = route

        return list(seen.values())

    def network_interfaces__effective_route_table(self, parameters: dict) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["networkInterfaceName"]
        nic_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{name}"
        nic = self._find_nic(sub, nic_id)
        if not nic:
            raise ResourceNotFound("Microsoft.Network/networkInterfaces", name, rg)

        subnet_id = self._get_nic_subnet_id(nic)
        if not subnet_id:
            return self._ok({"value": []})

        subnet = self._find_subnet(sub, subnet_id)
        if not subnet:
            return self._ok({"value": []})

        vnet = self._get_vnet_by_subnet_id(sub, subnet_id)
        if not vnet:
            return self._ok({"value": []})

        routes = self._compute_effective_routes_for_subnet(sub, subnet, vnet, include_udr=True)
        return self._ok({"value": routes})

    # ── Dataplane Forwarding Simulation ────────────────────────────

    def _ip_in_prefix(self, ip: str, prefix: str) -> bool:
        try:
            addr = ipaddress.IPv4Address(ip)
            net = ipaddress.IPv4Network(prefix, strict=False)
            return addr in net
        except Exception:
            return False

    def _longest_prefix_match(self, routes: list[dict], target_ip: str) -> dict | None:
        best = None
        best_len = -1
        for route in routes:
            prefix = route.get("addressPrefix", "")
            if not prefix:
                continue
            if self._ip_in_prefix(target_ip, prefix):
                plen = self._cidr_prefix_to_int(prefix)
                if plen > best_len:
                    best = route
                    best_len = plen
        return best

    def _resolve_next_hop(self, route: dict) -> str | None:
        nht = route.get("nextHopType", "")
        if nht == "VirtualAppliance":
            return route.get("nextHopIpAddress", "")
        if nht in ("VNetLocal", "VNetPeering", "Internet"):
            return None
        return None

    def _find_firewall_by_ip(self, subscription_id: str, ip: str) -> dict | None:
        for store in network_stores[subscription_id].values():
            for fw_id, fw in store.firewalls.items():
                for cfg in fw.get("properties", {}).get("ipConfigurations", []):
                    cfg_ip = cfg.get("properties", {}).get("privateIPAddress", "")
                    if cfg_ip == ip:
                        return fw
        return None

    def _find_vnet_by_ip(self, subscription_id: str, ip: str) -> dict | tuple | None:
        for store in network_stores[subscription_id].values():
            for vnet_id, vnet in store.virtual_networks.items():
                prefixes = vnet.get("properties", {}).get("addressSpace", {}).get("addressPrefixes", [])
                for prefix in prefixes:
                    if self._ip_in_prefix(ip, prefix):
                        return vnet
        return None

    def _find_subnet_by_ip_any_vnet(self, subscription_id: str, ip: str) -> dict | tuple | None:
        for store in network_stores[subscription_id].values():
            for vnet_id, vnet in store.virtual_networks.items():
                prefixes = vnet.get("properties", {}).get("addressSpace", {}).get("addressPrefixes", [])
                for prefix in prefixes:
                    if self._ip_in_prefix(ip, prefix):
                        for subnet in vnet.get("properties", {}).get("subnets", []):
                            s_prefix = subnet.get("properties", {}).get("addressPrefix", "")
                            if s_prefix and self._ip_in_prefix(ip, s_prefix):
                                return subnet, vnet
        return None, None

    def _traverse_forwarding_path(
        self,
        subscription_id: str,
        source_nic: dict,
        dest_ip: str,
        visited_vnets: set,
        hop_count: int,
        max_hops: int,
    ) -> dict:
        src_name = source_nic.get("name", "?")
        path = [src_name]

        subnet_id = self._get_nic_subnet_id(source_nic)
        subnet = self._find_subnet(subscription_id, subnet_id) if subnet_id else None
        vnet = self._get_vnet_by_subnet_id(subscription_id, subnet_id) if subnet_id else None

        if not vnet:
            return {
                "reachable": False,
                "error": "Source NIC not attached to a VNet",
                "matchedRoute": None, "nextHop": None, "nextHopType": None, "path": path,
            }

        if subnet and subnet.get("name"):
            path.append(f"subnet:{subnet['name']}")

        routes = self._compute_effective_routes_for_subnet(subscription_id, subnet, vnet, include_udr=True)
        return self._resolve_route_hop(
            path, subscription_id, subnet, vnet, routes, dest_ip, visited_vnets, hop_count, max_hops,
        )

    def _resolve_route_hop(
        self,
        path: list,
        subscription_id: str,
        subnet: dict | None,
        vnet: dict,
        routes: list[dict],
        dest_ip: str,
        visited_vnets: set,
        hop_count: int,
        max_hops: int,
        first_matched_route: str | None = None,
        first_next_hop: str | None = None,
        first_next_hop_type: str | None = None,
    ) -> dict:
        if hop_count >= max_hops:
            return {
                "reachable": False,
                "error": "Max hops exceeded",
                "matchedRoute": first_matched_route, "nextHop": first_next_hop,
                "nextHopType": first_next_hop_type, "path": path,
            }

        if vnet["id"] in visited_vnets:
            return {
                "reachable": False,
                "error": "Routing loop detected",
                "matchedRoute": first_matched_route, "nextHop": first_next_hop,
                "nextHopType": first_next_hop_type, "path": path,
            }
        visited_vnets.add(vnet["id"])

        if subnet and subnet.get("name") and not subnet["name"].startswith("_"):
            rt = self._get_subnet_route_table(subnet)
            if rt:
                path.append(f"rt:{rt.get('name', '?')}")

        matched = self._longest_prefix_match(routes, dest_ip)
        if not matched:
            return {
                "reachable": False,
                "error": "Blackhole — no matching route",
                "matchedRoute": first_matched_route, "nextHop": first_next_hop,
                "nextHopType": first_next_hop_type, "path": path,
            }

        nht = matched.get("nextHopType", "")
        nh_ip = self._resolve_next_hop(matched)
        route_name = matched.get("name", "")

        if first_matched_route is None:
            first_matched_route = route_name
            first_next_hop = nh_ip
            first_next_hop_type = nht

        if nht == "VirtualAppliance":
            next_hop_vnet = None
            next_hop_subnet = None
            fw = self._find_firewall_by_ip(subscription_id, nh_ip) if nh_ip else None
            if fw:
                path.append(f"fw:{fw['name']}")
                fw_subnet_id = self._find_firewall_subnet_id(fw.get("properties", {}))
                next_hop_vnet = self._get_vnet_by_subnet_id(subscription_id, fw_subnet_id) if fw_subnet_id else None
            elif nh_ip:
                fw_subnet, fw_vnet = self._find_subnet_by_ip_any_vnet(subscription_id, nh_ip)
                next_hop_vnet = fw_vnet
                next_hop_subnet = fw_subnet
                if fw_subnet and "AzureFirewall" in fw_subnet.get("name", ""):
                    path.append(f"fw:{nh_ip}")
                else:
                    path.append(f"nva:{nh_ip}")
            if next_hop_vnet:
                fw_routes = self._compute_effective_routes_for_subnet(subscription_id, next_hop_subnet, next_hop_vnet, include_udr=False)
                return self._resolve_route_hop(
                    path, subscription_id, None, next_hop_vnet, fw_routes,
                    dest_ip, visited_vnets, hop_count + 1, max_hops,
                    first_matched_route, first_next_hop, first_next_hop_type,
                )
            return {
                "reachable": True,
                "matchedRoute": first_matched_route,
                "nextHop": first_next_hop,
                "nextHopType": first_next_hop_type,
                "path": path,
            }

        if nht == "VNetPeering":
            peering = self._find_peering_by_name_in_vnet(subscription_id, vnet, route_name)
            if peering:
                remote_id = peering.get("properties", {}).get("remoteVirtualNetwork", {}).get("id", "")
                remote_vnet = self._find_vnet(subscription_id, remote_id)
                if remote_vnet:
                    path.append(f"peering:{peering.get('name', '?')}")
                    remote_routes = self._compute_effective_routes_for_subnet(subscription_id, None, remote_vnet, include_udr=False)
                    return self._resolve_route_hop(
                        path, subscription_id, None, remote_vnet, remote_routes,
                        dest_ip, visited_vnets, hop_count + 1, max_hops,
                        first_matched_route, first_next_hop, first_next_hop_type,
                    )
            return {
                "reachable": False,
                "error": f"Peering '{route_name}' not found or remote VNet missing",
                "matchedRoute": first_matched_route, "nextHop": first_next_hop,
                "nextHopType": first_next_hop_type, "path": path,
            }

        if nht == "VNetLocal":
            dest_subnet = self._find_subnet_by_ip_in_vnet(vnet, dest_ip)
            if dest_subnet:
                subnet_entry = f"subnet:{dest_subnet.get('name', '?')}"
                if subnet_entry not in path:
                    path.append(subnet_entry)
                dest_nic = self._find_nic_by_ip(subscription_id, dest_ip)
                if dest_nic:
                    path.append(f"nic:{dest_nic.get('name', '?')}")
            return {
                "reachable": True,
                "matchedRoute": first_matched_route,
                "nextHop": first_next_hop,
                "nextHopType": first_next_hop_type,
                "path": path,
            }

        if nht == "Internet":
            path.append("Internet")
            return {
                "reachable": True,
                "matchedRoute": first_matched_route,
                "nextHop": first_next_hop,
                "nextHopType": first_next_hop_type,
                "path": path,
            }

        return {
            "reachable": False,
            "error": f"Unknown next hop type: {nht}",
            "matchedRoute": first_matched_route,
            "nextHop": first_next_hop,
            "nextHopType": first_next_hop_type,
            "path": path,
        }

    def network_interfaces__simulate_forwarding(self, parameters: dict, request) -> tuple:
        sub = parameters["subscriptionId"]
        rg = parameters["resourceGroupName"]
        name = parameters["networkInterfaceName"]
        nic_id = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{name}"
        nic = self._find_nic(sub, nic_id)
        if not nic:
            raise ResourceNotFound("Microsoft.Network/networkInterfaces", name, rg)

        body = request.get_json(silent=True) or {}
        dest_ip = body.get("destinationIp", "")

        if not dest_ip:
            return self._ok({"reachable": False, "error": "destinationIp required"})

        result = self._traverse_forwarding_path(
            sub, nic, dest_ip, visited_vnets=set(), hop_count=0, max_hops=10,
        )
        return self._ok(result)
