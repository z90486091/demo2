from localstack.pro.azure.services.store import AccountRegionBundle, BaseStore, LocalAttribute


class NetworkStore(BaseStore):
    virtual_networks: dict[str, dict] = LocalAttribute(default=dict)
    peerings: dict[str, dict] = LocalAttribute(default=dict)
    firewalls: dict[str, dict] = LocalAttribute(default=dict)
    route_tables: dict[str, dict] = LocalAttribute(default=dict)
    public_ip_addresses: dict[str, dict] = LocalAttribute(default=dict)
    subnets: dict[str, dict] = LocalAttribute(default=dict)
    network_interfaces: dict[str, dict] = LocalAttribute(default=dict)
    # Track allocated private IPs per subnet ID
    private_ip_allocations: dict[str, list[str]] = LocalAttribute(default=dict)


network_stores = AccountRegionBundle[NetworkStore]("network", NetworkStore)
