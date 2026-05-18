import logging
from collections.abc import Iterator
from datetime import datetime
from time import mktime
from typing import Any
from wsgiref.handlers import format_date_time

LOG = logging.getLogger(__name__)

from localstack.pro.azure.api.Microsoft_Storage.Storage_ResourceManager_Objects_Latest import (
    BlobContainer_Latest,
    ContainerProperties_Latest,
    Endpoints_Latest,
    ImmutableStorageWithVersioning_Latest,
    LegalHoldProperties_Latest,
    ListContainerItem_Latest,
    Sku_Latest,
    SkuName_Latest,
    StorageAccount_Latest,
    StorageAccountProperties_Latest,
    StorageAccountsCreateRequest,
    StorageAccountUpdateParameters_Latest,
    Tier_Latest,
)
from localstack.pro.azure.services.store import AccountRegionBundle, BaseStore, LocalAttribute
from localstack.pro.azure.services.utilities.models import ResourceModel


class Container:
    def __init__(self, name: str, subscription_id: str, account_name: str, resource_group_name: str):
        self.name = name
        self.blobs: list[tuple[str, str, bytes]] = []
        self.last_modified = datetime.now()

        self.subscription_id = subscription_id
        self.account_name = account_name
        self.resource_group_name = resource_group_name

    @property
    def last_modified_rfc1123(self) -> str:
        stamp = mktime(self.last_modified.timetuple())
        return format_date_time(stamp)

    def fill(self, obj: BlobContainer_Latest | ListContainerItem_Latest) -> None:
        obj.name = self.name
        obj.id = f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/Microsoft.Storage/storageAccounts/{self.account_name}/blobServices/default/containers/{self.name}"
        obj.type = "Microsoft.Storage/storageAccounts/blobServices/containers"

        obj.properties = ContainerProperties_Latest()
        obj.properties.deleted = False
        obj.properties.default_encryption_scope = "$account-encryption-key"
        obj.properties.deny_encryption_scope_override = False
        obj.properties.has_immutability_policy = False
        obj.properties.has_legal_hold = False
        obj.properties.lease_state = "Available"
        obj.properties.lease_status = "Unlocked"
        obj.properties.public_access = "None"
        obj.properties.remaining_retention_days = 0
        obj.properties.last_modified_time = self.last_modified.strftime("%Y-%m-%dT%H:%M:%S.%s+00:00")

        if isinstance(obj, BlobContainer_Latest):
            obj.properties.legal_hold = LegalHoldProperties_Latest()
            obj.properties.legal_hold.has_legal_hold = False

        if isinstance(obj, ListContainerItem_Latest):
            obj.properties.immutable_storage_with_versioning = ImmutableStorageWithVersioning_Latest()
            obj.properties.immutable_storage_with_versioning.enabled = False


class StorageAccount(ResourceModel):
    def __init__(self, parameters: StorageAccountsCreateRequest):
        super().__init__(
            subscription_id=parameters.subscription_id,
            resource_group_name=parameters.resource_group_name,
            resource_name=parameters.account_name,
            resource_type="Microsoft.Storage/storageAccounts",
            location=parameters.parameters.location,
            tags=parameters.parameters.tags,
        )
        self.kind = parameters.parameters.kind

        self.sku_name = parameters.parameters.sku.name
        self.sku_tier = parameters.parameters.sku.tier or Tier_Latest.STANDARD

        self.created_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%s+00:00")
        self.changed_time = self.created_time

        self.containers: dict[str, Container] = {}

        self.tags = parameters.parameters.tags or {}
        self.identity = parameters.parameters.identity

        # For the Storage kind access_tier is always None
        if parameters.parameters.kind == "Storage":
            self.access_tier = None
        else:
            self.access_tier = (
                parameters.parameters.properties.access_tier
                if parameters.parameters.properties
                and parameters.parameters.properties.access_tier is not None
                else "Hot"
            )

        self.allowed_copy_scope = (
            parameters.parameters.properties.allowed_copy_scope if parameters.parameters.properties else None
        )
        self.allow_blob_public_access = (
            parameters.parameters.properties.allow_blob_public_access
            if parameters.parameters.properties
            and parameters.parameters.properties.allow_blob_public_access is not None
            else False
        )
        self.is_local_user_enabled = (
            parameters.parameters.properties.is_local_user_enabled
            if parameters.parameters.properties
            else None
        )
        self.allow_cross_tenant_replication = (
            parameters.parameters.properties.allow_cross_tenant_replication
            if parameters.parameters.properties
            and parameters.parameters.properties.allow_cross_tenant_replication is not None
            else False
        )
        self.default_to_o_auth_authentication = (
            parameters.parameters.properties.default_to_o_auth_authentication
            if parameters.parameters.properties
            else None
        )
        self.minimum_tls_version = (
            parameters.parameters.properties.minimum_tls_version
            if parameters.parameters.properties
            and parameters.parameters.properties.minimum_tls_version is not None
            else "TLS1_0"
        )

        # These properties have the following fixed values because they cannot be created or updated
        self.provisioning_state = "Succeeded"
        self.status_of_primary = "available"
        self.supports_https_traffic_only = True

        self.location = parameters.parameters.location
        self.extended_location = parameters.parameters.extended_location

        from ..dataplane.provider_azurite import AzuriteWrapper

        try:
            self.azurite_wrapper = AzuriteWrapper(self.name)
        except Exception as e:
            LOG.warning("Failed to initialize AzuriteWrapper for %s: %s", self.name, e)
            self.azurite_wrapper = None

    def update(self, parameters: StorageAccountUpdateParameters_Latest) -> None:
        if parameters.kind:
            self.kind = parameters.kind

        if parameters.sku:
            self.sku_name = parameters.sku.name
            self.sku_tier = parameters.sku.tier or Tier_Latest.STANDARD

        if parameters.tags:
            self.tags = parameters.tags

        if parameters.identity:
            self.identity = parameters.identity

        if not parameters.properties:
            return

        if parameters.properties.access_tier is not None:
            self.access_tier = parameters.properties.access_tier

        if parameters.properties.allow_blob_public_access is not None:
            self.allow_blob_public_access = parameters.properties.allow_blob_public_access

        if parameters.properties.allow_cross_tenant_replication is not None:
            self.allow_cross_tenant_replication = parameters.properties.allow_cross_tenant_replication

        if parameters.properties.minimum_tls_version is not None:
            self.minimum_tls_version = parameters.properties.minimum_tls_version

        self.allowed_copy_scope = parameters.properties.allowed_copy_scope
        self.is_local_user_enabled = parameters.properties.is_local_user_enabled
        self.default_to_o_auth_authentication = parameters.properties.default_to_o_auth_authentication

    def create_container(self, container_name: str) -> Container:
        container = Container(
            name=container_name,
            account_name=self.name,
            resource_group_name=self.resource_group_name,
            subscription_id=self.subscription_id,
        )
        self.containers[container_name] = container
        return container

    def delete_container(self, container_name: str) -> Container:
        return self.containers.pop(container_name)

    def response(self) -> StorageAccount_Latest:
        response = StorageAccount_Latest()
        response.kind = self.kind
        response.name = self.name
        response.location = self.location
        response.id = self.id
        response.type = self.type
        response.tags = self.tags

        response.sku = Sku_Latest()
        response.sku.name = self.sku_name
        response.sku.tier = self.sku_tier

        response.properties = StorageAccountProperties_Latest()
        response.properties.access_tier = self.access_tier
        response.properties.allowed_copy_scope = self.allowed_copy_scope
        response.properties.allow_blob_public_access = self.allow_blob_public_access
        response.properties.is_local_user_enabled = self.is_local_user_enabled
        response.properties.allow_cross_tenant_replication = self.allow_cross_tenant_replication
        response.properties.default_to_o_auth_authentication = self.default_to_o_auth_authentication

        response.properties.supports_https_traffic_only = self.supports_https_traffic_only
        response.properties.minimum_tls_version = self.minimum_tls_version
        response.properties.primary_location = self.location
        response.properties.provisioning_state = self.provisioning_state
        response.properties.status_of_primary = self.status_of_primary

        response.properties.primary_endpoints = Endpoints_Latest()
        if self.azurite_wrapper:
            response.properties.primary_endpoints.blob = self.azurite_wrapper.external_blob_endpoint
            response.properties.primary_endpoints.queue = self.azurite_wrapper.external_queue_endpoint
            response.properties.primary_endpoints.table = self.azurite_wrapper.external_table_endpoint
        # Based on very highlevel testing
        # The exact logic (when/which endpoints are exposed) is probably more involved
        if self.kind != "Storage":
            response.properties.primary_endpoints.dfs = f"https://{self.name}.dfs.core.windows.net/"
            response.properties.primary_endpoints.web = f"https://{self.name}.z28.web.core.windows.net/"
        if self.kind != "Storage" or self.sku_name == SkuName_Latest.STANDARD_LRS.value:  # type: ignore
            response.properties.primary_endpoints.file = f"https://{self.name}.file.core.windows.net/"

        return response

    def get_resource_properties(self) -> Iterator[tuple[str, Any]]:
        yield "location", self.location
        yield "kind", self.kind
        sku = Sku_Latest()
        sku.name = self.sku_name
        sku.tier = self.sku_tier
        yield "sku", sku

    def delete_resource(self) -> None:
        # It may have been deleted manually
        store = storage_stores[self.subscription_id][self.location]
        if self.name in store.storage_accounts:
            del store.storage_accounts[self.name]

            if self.azurite_wrapper:
                self.azurite_wrapper.stop_container()


class StorageStore(BaseStore):
    storage_accounts: dict[str, StorageAccount] = LocalAttribute(default=dict)  # type: ignore


storage_stores = AccountRegionBundle[StorageStore]("storage", StorageStore)
