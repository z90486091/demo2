import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from threading import Thread
from time import sleep
from typing import Any
from uuid import uuid4

import requests

from localstack import config
from localstack.pro.azure.api.Microsoft_Resources.Resources_ResourceManager_Objects_Latest import (
    BasicDependency_Latest,
    Dependency_Latest,
    DeploymentExtended_Latest,
    DeploymentProperties_Latest,
    DeploymentPropertiesExtended_Latest,
    Provider_Latest,
    ProviderResourceType_Latest,
    ResourceReference_Latest,
)
from localstack.pro.azure.server.proxy.server import start_proxy
from localstack.pro.azure.services.utilities.models import ResourceModel
from localstack.pro.azure.utilities.randomizer import get_random_hex
from localstack.pro.core.certificates.plugins import default_cert_store

from .exceptions import DeploymentException
from .parser import ARMTemplateParser

LOG = logging.getLogger(__name__)

CANONICAL_DEPLOYMENT_TYPES = {"string": "String", "object": "Object"}

MAX_CONCURRENT_RESOURCE_DEPLOYMENTS = 2

# Creating all resources usually takes awhile because of dependencies between resources
# Indicate how long we should wait until we retry the creation of resources that couldn't be created previously
WAIT_BETWEEN_RESOURCE_CREATION_ATTEMPTS = 2

# We may not be able to create a Resource because of a deadlock, where creation depends on the existence of another resource
# We want to retry this a few times, in case the other resource is still being created
# If we encounter this scenario too often, i.e. the resource does not exist at all or is never created successfully, we give up
MAX_DEADLOCK_ENCOUNTERS = 5

# How often we should GET a resource to see if creation was successful
NR_OF_RESOURCE_CREATION_SUCCESS_CHECKS = 10


class Resource:
    STATUS_WAITING = "WAITING"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETE = "COMPLETE"

    _REFERENCE_PATTERN = re.compile(
        r"\[reference\(resourceId\('([^']+)',\s*'([^']+)'\),\s*'([^']+)'\)\.(.+)\]"
    )

    def __init__(self, resource_group_name: str | None, subscription_id: str, data: dict[str, Any]):
        self.resource_group_name = resource_group_name or data.get("resourceGroup")
        self.subscription_id = subscription_id
        self._resource_data = data
        self.status = Resource.STATUS_WAITING
        self.output_id: str | None = None
        self.json_output: dict[str, Any] | None = None

        # Resource Types can be nested
        # Example of a 'root' type: Microsoft.Storage/storageAccounts
        # Example of a nested type: Microsoft.Storage/storageAccounts/blobServices/containers
        #
        # When the type is nested, the name will also reflect this
        # Example name for a root type: storage_name
        # Example name for a nested type: storage_name/blob_service_name/container_name
        #
        # Actual resource ID's have their types/names intertwined though, so that the end-result becomes:
        # Microsoft.Storage/storageAccounts/storage_name/blobServices/blob_service_name/containers/container_name
        self.namespace, *types = self.get_type().split("/")
        self.types_and_names = "/".join(
            [f"{t}/{n}" for t, n in zip(types, self.get_name().split("/"), strict=False)]
        )

    def get_id(self) -> str:
        return f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/{self.namespace}/{self.types_and_names}"

    def get_type(self) -> str:
        return self._resource_data["type"]

    def get_name(self) -> str:
        return self._resource_data["name"]

    def get_api_version(self) -> str:
        return self._resource_data.get("apiVersion", "")

    def list_dependency_ids(self) -> list[str]:
        return self._resource_data.get("dependsOn", [])

    def _resolve_references(self, data: Any, proxy_port: int, internal_host: str, ca_cert: str) -> Any:
        if isinstance(data, str):
            match = self._REFERENCE_PATTERN.match(data)
            if match:
                resource_type = match.group(1)
                resource_name = match.group(2)
                api_version = match.group(3)
                path = match.group(4)
                url = (
                    f"https://management.azure.com/subscriptions/{self.subscription_id}"
                    f"/resourceGroups/{self.resource_group_name}"
                    f"/providers/{resource_type}/{resource_name}?api-version={api_version}"
                )
                try:
                    resp = requests.get(url=url, verify=ca_cert, proxies={"https": f"{internal_host}:{proxy_port}"})
                    if resp.ok:
                        resolved = GlobalDeployment._navigate_json_path(
                            resp.json().get("properties", resp.json()), path
                        )
                        if resolved is not None:
                            LOG.warning("Resolved reference in resource %s: %s -> %s", self.get_name(), data[:60], str(resolved)[:60])
                            return resolved
                except Exception as e:
                    LOG.warning("Failed to resolve reference in resource %s: %s", self.get_name(), e)
            return data
        if isinstance(data, dict):
            return {k: self._resolve_references(v, proxy_port, internal_host, ca_cert) for k, v in data.items()}
        if isinstance(data, list):
            return [self._resolve_references(item, proxy_port, internal_host, ca_cert) for item in data]
        return data

    def deploy(self) -> None:
        LOG.info(
            "Deploying %s=%s in ResourceGroup %s", self.get_type(), self.get_name(), self.resource_group_name
        )
        self.status = Resource.STATUS_IN_PROGRESS

        # This currently assumes success - a second pass should add some basic validation
        proxy_port = start_proxy()
        internal_host = config.GATEWAY_LISTEN[0].host
        ca_cert = default_cert_store().root_ca_cert_path

        # Resolve [reference(...)] expressions in resource properties before sending
        resolved_data = self._resolve_references(self._resource_data, proxy_port, internal_host, ca_cert)

        resp = requests.put(
            url=self.get_resource_url(),
            json=resolved_data,
            verify=ca_cert,
            proxies={"https": f"{internal_host}:{proxy_port}"},
        )
        LOG.info(
            "Deployment for %s=%s in ResourceGroup %s finished with status: %s",
            self.get_type(),
            self.get_name(),
            self.resource_group_name,
            resp.status_code,
        )
        # Throws an exception in case the resource deployment failed
        if not resp.ok:
            raise DeploymentException(
                f"Deployment failed for {self.get_type()}={self.get_name()} in ResourceGroup {self.resource_group_name}: HTTP {resp.status_code} - {resp.text}"
            )
        try:
            # Try to get the status from the CREATE-request
            # This may fail if it is an async request
            try:
                json_output = resp.json()
                status = json_output.get("properties", {}).get("provisioningState")
            except requests.exceptions.JSONDecodeError:
                json_output = {}
                status = None

            # If the resource has not been created successfully, hit the GET endpoint until it has finished
            # Three exit points:
            # Success: Status == Succeeded
            # Timeout: After >= x attempts
            # Unknown: StatusCode == 200, but we do not have a status
            attempt = 0
            while status != "Succeeded":
                if attempt >= NR_OF_RESOURCE_CREATION_SUCCESS_CHECKS:
                    raise DeploymentException(
                        f"Unable to determine deployment status after {NR_OF_RESOURCE_CREATION_SUCCESS_CHECKS} attempts"
                    )
                LOG.warning(
                    "Resource %s=%s is not deployed yet (status=%s), wait a little longer...",
                    self.get_type(),
                    self.get_name(),
                    status,
                )

                sleep(attempt)
                resp = requests.get(
                    url=self.get_resource_url(),
                    verify=ca_cert,
                    proxies={"https": f"{internal_host}:{proxy_port}"},
                )
                json_output = resp.json()
                status = json_output.get("properties", {}).get("provisioningState")

                if resp.status_code == 200 and status is None:
                    # 200 indicates success - if we can't find the status, it probably isn't returned correctly
                    # Let's assume success
                    status = "Succeeded"
                    LOG.warning(
                        "Unable to find status for %s=%s, assuming success", self.get_type(), self.get_name()
                    )

                attempt += 1

            self.output_id = json_output["id"]
            self.json_output = json_output
            LOG.info(json.dumps(json_output))

        except (requests.exceptions.JSONDecodeError, KeyError, DeploymentException) as e:
            LOG.warning(
                "Deployment for %s=%s in ResourceGroup %s - Unable to find output ID: %s",
                self.get_type(),
                self.get_name(),
                self.resource_group_name,
                e,
            )

        self.status = Resource.STATUS_COMPLETE

    def get_resource_url(self) -> str:
        if not self.resource_group_name:
            # Usually the case when creating ResourceGroups - URL is slightly different for those
            return f"https://management.azure.com/subscriptions/{self.subscription_id}/resourcegroups/{self.get_name()}?api-version={self.get_api_version()}"
        else:
            # Default case - Resource in a ResourceGroup
            return f"https://management.azure.com/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/{self.namespace}/{self.types_and_names}?api-version={self.get_api_version()}"


class DeploymentManager(Thread):
    STATUS_RUNNING = "Running"
    STATUS_SUCCEEDED = "Succeeded"
    STATUS_FAILED = "Failed"

    def __init__(
        self,
        parameters: dict[str, dict[str, str]],
        template: dict[str, Any],
        deployment: "GlobalDeployment",
    ):
        super().__init__()
        self.resource_group_name = deployment.resource_group_name
        self.subscription_id = deployment.subscription_id
        self.parameters = parameters
        self.template = template
        self.location = deployment.location
        self.resources: dict[str, Resource] = {}
        self.deployment = deployment
        self.deployment_failed = False

    def has_resources(self) -> bool:
        return len(self.resources) > 0

    def run(self) -> None:
        try:
            # Process Resources
            # This involves downloading the ArmTemplateParser.Cli, which is why it's done in the background
            processed_variables = ARMTemplateParser.parse_variables(
                parameters=self.parameters,
                template=self.template,
                location=self.location,
                resource_group_name=self.resource_group_name,
            )

            for var in processed_variables:
                self.parameters[var] = processed_variables[var]

            parsed_resources = ARMTemplateParser.parse_resources(
                parameters=self.parameters,
                template=self.template,
                location=self.location,
                resource_group_name=self.resource_group_name,
            )

            ARMTemplateParser.parse_dependencies(
                parsed_resources,
                subscription_id=self.subscription_id,
                resource_group_name=self.resource_group_name,
            )

            # Add support for the ARM template copy element used inside loops
            # In Bicep, this mechanism is used by for loops.
            copies: dict[str, list[str]] = {}

            for resource_data in parsed_resources:
                # If the condition element exists in the resource definition and
                # its value is false, it means that the ARM template the conditional
                # provisioning expression for this resource evaluated to false.
                # Hence, the resource should be deployed.
                if "condition" not in resource_data or resource_data["condition"]:
                    resource = Resource(
                        resource_group_name=self.resource_group_name,
                        subscription_id=self.subscription_id,
                        data=resource_data,
                    )
                    self.resources[resource.get_id()] = resource
                    if (
                        "copy" in resource_data
                        and isinstance(resource_data["copy"], dict)
                        and "name" in resource_data["copy"]
                        and "count" in resource_data["copy"]
                        and resource_data["copy"]["count"] > 1
                    ):
                        if resource_data["copy"]["name"] in copies:
                            copies[resource_data["copy"]["name"]].append(resource.get_id())
                        else:
                            copies[resource_data["copy"]["name"]] = [resource.get_id()]

            self.add_operation("EvaluateDeploymentOutput")

            nr_of_unprocessed_resources_previously = 0
            deadlock_encounters = 0
            while True:
                unprocessed_resources = self.get_resources_waiting()
                nr_of_unprocessed_resources = len(unprocessed_resources)
                if nr_of_unprocessed_resources == 0:
                    break
                if nr_of_unprocessed_resources == nr_of_unprocessed_resources_previously:
                    # We've tried to process all the resources,
                    # but the number of unprocessed resources hasn't changed.
                    # This typically happens if two resources depend on each other and there is a deadlock
                    if deadlock_encounters >= MAX_DEADLOCK_ENCOUNTERS:
                        LOG.warning(
                            "Unable to complete deployment, resources %s haven't completed yet!",
                            [f"{r.get_type()}::{r.get_name()}" for r in unprocessed_resources],
                        )
                        break
                    deadlock_encounters += 1
                LOG.info("DeploymentManager: Creating resources, %s outstanding", nr_of_unprocessed_resources)
                for resource in unprocessed_resources:
                    # Check dependencies
                    # If this resource has dependencies on resources that haven't finished yet,
                    # continue on to the next resource
                    if dependency_ids := resource.list_dependency_ids():
                        for dependency_id in dependency_ids:
                            # If the dependency is non a copy element, the copy name
                            # is replaced by the id of the resources deployed in the copy loop
                            if not dependency_id.startswith("/"):
                                dependency_ids.remove(dependency_id)
                                if dependency_id in copies:
                                    dependency_ids.extend(copies[dependency_id])

                        finished_resource_ids = [
                            r.output_id for r in self.get_resources_finished() if r.output_id
                        ]
                        if not all(_id in finished_resource_ids for _id in dependency_ids):
                            continue

                    try:
                        resource.deploy()  # Wrap this in try-catch
                        self.add_operation("Create", target=resource)
                    except Exception as e:
                        LOG.error(
                            "Deployment failed for resource %s=%s: %s",
                            resource.get_type(),
                            resource.get_name(),
                            str(e),
                        )
                        self.deployment_failed = True  # Set failure flag
                        resource.status = Resource.STATUS_COMPLETE  # Mark as complete to avoid infinite loop
                        self.add_operation("Create", target=resource)
                        return  # Exit the run method immediately on failure

                nr_of_unprocessed_resources_previously = nr_of_unprocessed_resources
                sleep(WAIT_BETWEEN_RESOURCE_CREATION_ATTEMPTS)

            self.add_operation("DeploymentCleanup")
        except Exception as e:
            LOG.error("Deployment failed with unexpected error: %s", str(e))
            self.deployment_failed = True

    def add_operation(self, name: str, target: Resource | None = None) -> None:
        self.deployment.operations.append(
            DeploymentOperation(
                resource_group=self.resource_group_name,
                subscription_id=self.subscription_id,
                deployment_name=self.deployment.name,
                operation=name,
                target=target,
            )
        )

    def get_resources_waiting(self) -> list[Resource]:
        # ident is None -> Thread hasn't started yet
        return [res for res in self.resources.values() if res.status == Resource.STATUS_WAITING]

    def get_resources_in_progress(self) -> list[Resource]:
        return [res for res in self.resources.values() if res.status == Resource.STATUS_IN_PROGRESS]

    def get_resources_finished(self) -> list[Resource]:
        return [res for res in self.resources.values() if res.status == Resource.STATUS_COMPLETE]

    def get_status(self) -> str:
        # Check if deployment failed
        if self.deployment_failed:
            return DeploymentManager.STATUS_FAILED

        # If the deployment is still being executed, we haven't finished yet
        if self.ident is None or self.is_alive():
            return DeploymentManager.STATUS_RUNNING

        # If any resources are still being created, we haven't finished yet
        for res in self.resources.values():
            if res.status == Resource.STATUS_WAITING:
                return DeploymentManager.STATUS_RUNNING
            if res.status == Resource.STATUS_IN_PROGRESS:
                return DeploymentManager.STATUS_RUNNING

        # Only when all resources are ready, the deployment can be considered complete
        return DeploymentManager.STATUS_SUCCEEDED


class DeploymentOperation:
    def __init__(
        self,
        subscription_id: str,
        resource_group: str | None,
        deployment_name: str,
        operation: str,
        target: Resource | None,
    ):
        self.operation_id = get_random_hex(length=16).upper()
        if resource_group:
            self.id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Resources/deployments/{deployment_name}/operations/{self.operation_id}"
        else:
            self.id = f"/subscriptions/{subscription_id}/providers/Microsoft.Resources/deployments/{deployment_name}/operations/{self.operation_id}"
        self.operation = operation
        self.timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%sZ")
        self.duration = "PT1S"  # Not tracked yet

        self.target = target


class GlobalDeployment:
    TYPE = "Microsoft.Resources/deployments"

    def __init__(
        self,
        name: str,
        resource_group_name: str | None,
        resource_group_location: str | None,
        subscription_id: str,
        location: str,
        properties: DeploymentProperties_Latest,
    ):
        self.id = f"/subscriptions/{subscription_id}/providers/Microsoft.Resources/deployments/{name}"
        self.name = name
        self.location = location
        self.subscription_id = subscription_id
        self.resource_group_name = resource_group_name
        self.resource_group_location = resource_group_location

        self.properties = properties
        assert self.properties.template
        ARMTemplateParser.validate_template_fields(self.properties.template)

        self.operations: list[DeploymentOperation] = []

        self.correlation_id = str(uuid4())
        self.created = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%s+00:00")

        # Replaces references to our resource group
        # The Parser doesn't know anything about that, so we have to do it manually
        if resource_group_name and resource_group_location:
            ARMTemplateParser.replace_resource_group_info(
                template=self.properties.template,
                resource_group_name=resource_group_name,
                resource_group_location=resource_group_location,
            )
        if not self.properties.parameters:
            self.properties.parameters = {}

        self._resolve_reference_expressions()

        # Resolve Parameters
        # They are either provided by the user or can be calculated
        self.resolved_parameters: dict[str, Any] = {}
        for param_name, param_details in self.properties.template.get("parameters", {}).items():
            resolved = {"type": CANONICAL_DEPLOYMENT_TYPES.get(param_details["type"], param_details["type"])}
            if param_name in self.properties.parameters:
                resolved["value"] = self.properties.parameters[param_name]["value"]
            else:
                # TODO: Can we use the defaultValue as specified in the template?
                # We may have to process it first, as a defaultValue can be made up of functions
                # - "[resourceGroup().location]"
                # - "[concat('storage', uniqueString(resourceGroup().id))]"
                pass
            self.resolved_parameters[param_name] = resolved

        self.deployment_manager = DeploymentManager(
            parameters=self.properties.parameters,
            template=self.properties.template,
            deployment=self,
        )
        self.deployment_manager.start()

        # Determine Outputs
        self.resolved_outputs: dict[str, Any] = {}
        parsed_outputs = ARMTemplateParser.parse_outputs(
            parameters=self.properties.parameters,
            template=self.properties.template,
            location=self.location,
            resource_group_name=self.resource_group_name,
        )
        self.has_outputs = "outputs" in self.properties.template
        for name, details in self.properties.template.get("outputs", {}).items():
            resolved = {
                "type": CANONICAL_DEPLOYMENT_TYPES.get(details["type"], details["type"]),
                "value": parsed_outputs.get(name),
            }
            self.resolved_outputs[name] = resolved

    def fill(self, obj: DeploymentExtended_Latest) -> None:
        obj.id = self.id
        obj.name = self.name
        obj.type = GlobalDeployment.TYPE
        if not self.resource_group_name:
            obj.location = self.location

        obj.properties = DeploymentPropertiesExtended_Latest()
        obj.properties.correlation_id = self.correlation_id
        obj.properties.diagnostics = None  # type: ignore
        obj.properties.extensions = None  # type: ignore[assignment]
        obj.properties.timestamp = self.created
        obj.properties.duration = "PT1S"
        obj.properties.provisioning_state = self.deployment_manager.get_status()
        obj.properties.mode = self.properties.mode
        # TODO: Determine how to compute hash if it's not provided
        obj.properties.template_hash = (
            self.properties.template.get("metadata", {}).get("_generator", {}).get("templateHash")  # type: ignore
        )

        if self.deployment_manager.has_resources():
            obj.properties.parameters = self.resolved_parameters
        else:
            obj.properties.parameters = None

        obj.properties.validated_resources = None  # type: ignore

        serialized_resources: dict[str, list[ProviderResourceType_Latest]] = defaultdict(list)
        for resource in self.deployment_manager.resources.values():
            split_type = resource.get_type().split("/", 1)
            if len(split_type) == 2:
                namespace, resource_type = split_type
            else:
                # Skip this resource if the type is not in the expected format
                continue

            type_resp = ProviderResourceType_Latest()
            type_resp.resource_type = resource_type
            type_resp.aliases = None  # type: ignore
            type_resp.api_profiles = None  # type: ignore
            type_resp.api_versions = None  # type: ignore
            if serialized_resources[namespace]:
                # Only the first resource for each namespace returns a location
                # subsequent resources return [None]
                type_resp.locations.append(None)  # type: ignore
            else:
                type_resp.locations.append(self.resource_group_location)  # type: ignore
            type_resp.location_mappings = None  # type: ignore
            type_resp.zone_mappings = None  # type: ignore

            serialized_resources[namespace].append(type_resp)

        for namespace in serialized_resources:
            provider = Provider_Latest()
            provider.namespace = namespace
            provider.resource_types.extend(serialized_resources[namespace])
            obj.properties.providers.append(provider)

        # Dependencies
        for resource in self.deployment_manager.resources.values():
            resp = Dependency_Latest()
            resp.id = resource.get_id()
            resp.resource_type = resource.get_type()
            resp.resource_name = resource.get_name()
            if dependency_ids := resource.list_dependency_ids():
                for dep_id in dependency_ids:
                    # Azure returns dependencies for every request to GetDeployment
                    #
                    # We do not have this information immediately available, though,
                    # as we may still be busy downloading/running the TemplateParser
                    #
                    # So there is a parity issue the first few times GetDeployment is called
                    # That should not be a big problem though:
                    # By the time we finish parsing the template, all Dependency information will be available/returned
                    if resource_dependency := self.deployment_manager.resources.get(dep_id):
                        basic_resp = BasicDependency_Latest()
                        basic_resp.id = dep_id
                        basic_resp.resource_name = resource_dependency.get_name()
                        basic_resp.resource_type = resource_dependency.get_type()
                        resp.depends_on.append(basic_resp)
                obj.properties.dependencies.append(resp)

        obj.properties.dependencies = sorted(obj.properties.dependencies, key=lambda x: x.resource_type)  # type: ignore

        if obj.properties.provisioning_state == DeploymentManager.STATUS_RUNNING:
            obj.properties.output_resources = None  # type: ignore

        if (
            obj.properties.provisioning_state == DeploymentManager.STATUS_SUCCEEDED
            and self.deployment_manager.has_resources()
        ):
            if self.has_outputs:
                obj.properties.outputs = self.resolved_outputs

            resource_ids = [
                r.output_id for r in self.deployment_manager.get_resources_finished() if r.output_id
            ]
            for resource_id in sorted(resource_ids):
                output_resource = ResourceReference_Latest()
                output_resource.id = resource_id
                obj.properties.output_resources.append(output_resource)


    def _resolve_reference_expressions(self) -> None:
        if not self.properties.parameters:
            return
        LOG.warning("Resolving references for %s params=%s", self.name, list(self.properties.parameters.keys()))
        proxy_port = start_proxy()
        internal_host = config.GATEWAY_LISTEN[0].host
        ca_cert = default_cert_store().root_ca_cert_path

        pattern_deployment = re.compile(
            r"\[reference\(resourceId\('Microsoft\.Resources/deployments',\s*'([^']+)'\),\s*'([^']+)'\)\.outputs\.([^.]+)\.value\]"
        )
        pattern_resource = re.compile(
            r"\[reference\(resourceId\('([^']+)',\s*'([^']+)'\),\s*'([^']+)'\)\.(.+)\]"
        )

        for param_name, param_info in list(self.properties.parameters.items()):
            if not isinstance(param_info, dict) or "value" not in param_info:
                continue
            value = param_info["value"]
            if not isinstance(value, str):
                continue

            resolved = value
            for iteration in range(5):
                if not isinstance(resolved, str) or not resolved.startswith("["):
                    break
                match = pattern_deployment.match(resolved)
                if match:
                    deployment_name = match.group(1)
                    api_version = match.group(2)
                    output_key = match.group(3)
                    url = (
                        f"https://management.azure.com/subscriptions/{self.subscription_id}"
                        f"/resourceGroups/{self.resource_group_name}"
                        f"/providers/Microsoft.Resources/deployments/{deployment_name}?api-version={api_version}"
                    )
                    try:
                        resp = requests.get(
                            url=url,
                            verify=ca_cert,
                            proxies={"https": f"{internal_host}:{proxy_port}"},
                        )
                        if resp.ok:
                            data = resp.json()
                            output_value = data.get("properties", {}).get("outputs", {}).get(output_key, {}).get("value")
                            if output_value is not None:
                                resolved = output_value
                                LOG.warning("Resolved deployment output %s.%s -> %s", deployment_name, output_key, str(resolved)[:80])
                                continue
                    except Exception as e:
                        LOG.warning("Failed to resolve deployment output %s: %s", resolved, e)
                    break

                match = pattern_resource.match(resolved)
                if match:
                    resource_type = match.group(1)
                    resource_name = match.group(2)
                    api_version = match.group(3)
                    path = match.group(4)
                    url = (
                        f"https://management.azure.com/subscriptions/{self.subscription_id}"
                        f"/resourceGroups/{self.resource_group_name}"
                        f"/providers/{resource_type}/{resource_name}?api-version={api_version}"
                    )
                    try:
                        resp = requests.get(
                            url=url,
                            verify=ca_cert,
                            proxies={"https": f"{internal_host}:{proxy_port}"},
                        )
                        if resp.ok:
                            data = resp.json()
                            prop_value = self._navigate_json_path(data.get("properties", data), path)
                            if prop_value is not None:
                                resolved = prop_value
                                LOG.warning("Resolved resource ref %s -> %s", str(value)[:60], str(resolved)[:60])
                                continue
                    except Exception as e:
                        LOG.warning("Failed to resolve resource ref %s: %s", str(value)[:60], e)
                    break
                break

            if resolved != value:
                if isinstance(resolved, (dict, list, int, float, bool)):
                    resolved = str(resolved)
                param_info["value"] = resolved
                LOG.warning("Final resolved %s = %s", param_name, str(resolved)[:120])

    @staticmethod
    def _navigate_json_path(data: dict, path: str) -> Any:
        parts = path.split(".")
        current = data
        for part in parts:
            array_match = re.match(r"^([^\[]+)\[(\d+)\]$", part)
            if array_match:
                key = array_match.group(1)
                index = int(array_match.group(2))
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return None
                if isinstance(current, list) and index < len(current):
                    current = current[index]
                else:
                    return None
            else:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
        # Convert to JSON-serializable type if needed
        if isinstance(current, (dict, list, str, int, float, bool)) or current is None:
            return current
        return str(current)

class ResourceGroupDeployment(ResourceModel, GlobalDeployment):  # type: ignore
    def __init__(
        self,
        name: str,
        subscription_id: str,
        resource_group_name: str,
        resource_group_location: str,
        location: str,
        properties: DeploymentProperties_Latest,
        tags: dict[str, str] | None,
    ):
        GlobalDeployment.__init__(
            self,
            name=name,
            resource_group_name=resource_group_name,
            resource_group_location=resource_group_location,
            subscription_id=subscription_id,
            location=location,
            properties=properties,
        )
        ResourceModel.__init__(
            self,
            subscription_id=subscription_id,
            resource_group_name=resource_group_name,
            resource_type=GlobalDeployment.TYPE,
            resource_name=name,
            location=location,
            tags=tags,
        )
