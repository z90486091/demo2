import functools
import logging
from collections.abc import Callable

import requests
from plux import PluginManager, PluginSpec

from localstack.pro.azure.constants import INTERNAL_REQUEST_HEADER
from localstack.pro.azure.services.plugin import AzureService
from localstack.runtime import get_current_runtime, hooks
from localstack.services.plugins import (
    ServicePluginAdapter,
    ServicePluginErrorCollector,
    ServicePluginManager,
)

LOG = logging.getLogger(__name__)

PLUGIN_NAMESPACE = "localstack.azure.provider"


def azure_provider(
    api: str | None = None, name: str = "default", should_load: Callable[[], bool] | None = None
) -> Callable[[Callable[[], AzureService]], Callable[[], AzureService]]:
    """
    Decorator for marking methods that create a Service instance as a ServicePlugin. Methods marked with this
    decorator are discoverable as a PluginSpec within the namespace "localstack.azure.provider", with the name
    "<api>:<name>". If api is not explicitly specified, then the method name is used as api name.
    """

    def wrapper(fn: Callable[[], AzureService]) -> Callable[[], AzureService]:
        # sugar for being able to name the function like the api
        _api = api or fn.__name__

        # this causes the plugin framework into pointing the entrypoint to the original function rather than the
        # nested factory function
        @functools.wraps(fn)
        def factory() -> ServicePluginAdapter:
            return ServicePluginAdapter(api=_api, should_load=should_load, create_service=fn)  # type: ignore[arg-type]

        return PluginSpec(PLUGIN_NAMESPACE, f"{_api}:{name}", factory=factory)

    return wrapper


@azure_provider(api="Microsoft.Resources")
def resources_resources() -> AzureService:
    from localstack.pro.azure.services.resources.provider import ResourcesImpl

    return AzureService.for_provider(ResourcesImpl())


@azure_provider(api="Microsoft.ResourceGraph")
def resourcegraph() -> AzureService:
    from localstack.pro.azure.services.resourcegraph.provider import ResourceGraphProvider

    return AzureService.for_provider(ResourceGraphProvider())


@azure_provider(api="Microsoft.Authorization")
def authorization_resources() -> AzureService:
    from localstack.pro.azure.services.authorization.authorization_service import AuthorizationImplementation

    return AzureService.for_provider(AuthorizationImplementation())


@azure_provider(api="Microsoft.ApiManagement")
def api_management() -> AzureService:
    from localstack.pro.azure.services.apimanagement.provider import ApiManagementImpl

    return AzureService.for_provider(ApiManagementImpl())


@azure_provider(api="Microsoft.App")
def app_environments() -> AzureService:
    from localstack.pro.azure.services.apps.provider import AppsImpl

    return AzureService.for_provider(AppsImpl())


@azure_provider(api="Microsoft.Cdn")
def cdn() -> AzureService:
    from localstack.pro.azure.services.cdn.provider import CdnImp

    return AzureService.for_provider(CdnImp())


@azure_provider(api="Microsoft.ContainerRegistry")
def container_registry() -> AzureService:
    from localstack.pro.azure.services.containerregistry.provider import ContainerRegistryImpl

    return AzureService.for_provider(ContainerRegistryImpl())


@azure_provider(api="Microsoft.ContainerService")
def container_service() -> AzureService:
    from localstack.pro.azure.services.containerservice.provider import ContainerServiceImpl

    return AzureService.for_provider(ContainerServiceImpl())


@azure_provider(api="Microsoft.DBforPostgreSQL")
def cosmos_postgres() -> AzureService:
    from localstack.pro.azure.services.cosmos.postgres.provider import CosmosDBPostgresImpl

    return AzureService.for_provider(CosmosDBPostgresImpl())


@azure_provider(api="Microsoft.DocumentDB")
def cosmos_mongo() -> AzureService:
    from localstack.pro.azure.services.cosmos.mongo.provider import CosmosDBMongoImpl

    return AzureService.for_provider(CosmosDBMongoImpl())


@azure_provider(api="Microsoft.EventGrid")
def eventgrid() -> AzureService:
    from localstack.pro.azure.services.eventgrid.provider import EventGridImpl

    return AzureService.for_provider(EventGridImpl())


@azure_provider(api="Microsoft.EventGrid.DataPlane")
def eventgrid_dataplane() -> AzureService:
    from localstack.pro.azure.services.eventgrid.dataplane.provider import EventGridDataPlane

    return AzureService.for_provider(EventGridDataPlane())


@azure_provider(api="Microsoft.KeyVault")
def keyvault_secrets() -> AzureService:
    from localstack.pro.azure.services.keyvault.provider import KeyVaultImpl

    return AzureService.for_provider(KeyVaultImpl())


@azure_provider(api="Microsoft.Subscription")
def subscription_subscriptions() -> AzureService:
    from localstack.pro.azure.services.resources.provider import ResourcesImpl

    return AzureService.for_provider(ResourcesImpl())


@azure_provider(api="Microsoft.ServiceBus")
def servicebus() -> AzureService:
    from localstack.pro.azure.services.servicebus.provider import ServiceBusProvider

    return AzureService.for_provider(ServiceBusProvider())


@azure_provider("Microsoft.Storage")
def storage_storage() -> AzureService:
    from localstack.pro.azure.services.storage.storage.provider import StorageImpl

    return AzureService.for_provider(StorageImpl())


@azure_provider(api="Microsoft.Sql")
def sql() -> AzureService:
    from localstack.pro.azure.services.sql.provider import SqlImpl

    return AzureService.for_provider(SqlImpl())


@azure_provider(api="Localstack.OperationResults")
def operation_results() -> AzureService:
    from localstack.pro.azure.services.operationresults.provider import OperationResults

    return AzureService.for_provider(OperationResults())


@azure_provider(api="Microsoft.OperationalInsights")
def operational_insights() -> AzureService:
    from localstack.pro.azure.services.operational_insights.provider import OperationalInsightsImpl

    return AzureService.for_provider(OperationalInsightsImpl())


@azure_provider(api="Microsoft.Web")
def web() -> AzureService:
    from localstack.pro.azure.services.web.provider import WebImpl

    return AzureService.for_provider(WebImpl())


@azure_provider(api="Microsoft.Network")
def network() -> AzureService:
    from localstack.pro.azure.services.network.provider import NetworkImpl

    return AzureService.for_provider(NetworkImpl())


@hooks.on_runtime_ready()  # type: ignore
def create_managed_storage_containers() -> None:  # type: ignore
    if get_current_runtime().components.name != "azure":
        # only run this hook if the current runtime is azure
        # this is a workaround to avoid trying to create managed storage containers in the localstack aws runtime
        return
    LOG.info("Creating Managed StorageContainers")
    from localstack import config
    from localstack.pro.azure.constants import AZURE_MANAGED_SUBSCRIPTION_ID
    from localstack.pro.azure.server.proxy.server import start_proxy
    from localstack.pro.azure.services.storage.storage.constants import (
        AZURE_MANAGED_STORAGE_ACCOUNT_NAME,
        AZURE_MANAGED_STORAGE_ACCOUNT_RESOURCE_GROUP,
    )
    from localstack.pro.core.certificates.plugins import default_cert_store

    proxy_port = start_proxy()

    internal_host = config.GATEWAY_LISTEN[0].host
    ca_cert = default_cert_store().root_ca_cert_path

    create_resource_group_url = f"https://management.azure.com/subscriptions/{AZURE_MANAGED_SUBSCRIPTION_ID}/resourcegroups/{AZURE_MANAGED_STORAGE_ACCOUNT_RESOURCE_GROUP}?api-version=2022-09-01"
    requests.put(
        url=create_resource_group_url,
        headers={INTERNAL_REQUEST_HEADER: "yes"},
        json={"location": "global"},
        proxies={"https": f"{internal_host}:{proxy_port}"},
        verify=ca_cert,
    )

    create_storage_account_url = f"https://management.azure.com/subscriptions/{AZURE_MANAGED_SUBSCRIPTION_ID}/resourceGroups/{AZURE_MANAGED_STORAGE_ACCOUNT_RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/{AZURE_MANAGED_STORAGE_ACCOUNT_NAME}?api-version=2023-05-01"
    requests.put(
        url=create_storage_account_url,
        headers={INTERNAL_REQUEST_HEADER: "yes"},
        json={"sku": {"name": "Standard"}, "kind": "StorageV2", "location": "global"},
        proxies={"https": f"{internal_host}:{proxy_port}"},
        verify=ca_cert,
    )


plugin_errors = ServicePluginErrorCollector()
plugin_manager = PluginManager(PLUGIN_NAMESPACE, listener=plugin_errors)
SERVICE_PLUGINS: ServicePluginManager = ServicePluginManager(plugin_manager)
