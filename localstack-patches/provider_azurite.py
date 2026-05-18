import logging
import re
from collections.abc import Callable
from datetime import datetime
from threading import RLock
from time import mktime
from wsgiref.handlers import format_date_time

import requests
from rolo.request import Request
from rolo.response import Response

from localstack.config import is_in_docker, is_in_wsl
from localstack.pro.azure.services.storage.storage.constants import AZURE_MANAGED_STORAGE_ACCOUNT_NAME
from localstack.pro.azure.utilities.http.utilities import log_request, log_response
from localstack.pro.azure.utilities.msf.azure_responses_parser import convert_to_response
from localstack.pro.core.utils.container.container import (
    container_class,
)
from localstack.services.edge import ROUTER
from localstack.utils.container_utils.container_client import PortMappings
from localstack.utils.net import dynamic_port_range
from localstack.utils.sync import retry

from ..storage.models import storage_stores
from ..storage_utils import HostnamePrefix, get_blob_host, get_queue_host, get_table_host
from .auth_utils import compute_hmac_sha256, string_to_sign_blob_storage, string_to_sign_table_storage

# Azurite has a default StorageAccount that one can connect to
# This is the default key that comes with it, and that always must be used to connect to this default account
#
# Because we create custom accounts, we can decide what key should be used to authenticate those accounts
# So theoretically we could use the randomized key assigned to this account
# (i.e. the one that we currently hardcode in storage_accounts__list_keys)
#
# But we already control access to Azurite completely, so having custom keys doesn't add anything (except for complexity)
# That's why we use the same key to authenticate every StorageAccount
account_key = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="

LOG = logging.getLogger(__name__)
AZURITE_DOCKER_IMAGE = "mcr.microsoft.com/azure-storage/azurite"

_AZURITE_CONTAINER_NAME = "azurite"
_azurite_accounts: dict[str, str] = {
    "devstoreaccount1": "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==",
}


def _restart_azurite_with_accounts() -> None:
    try:
        import docker
        client = docker.from_env()
        old = client.containers.get(_AZURITE_CONTAINER_NAME)
        env = [e for e in old.attrs['Config'].get('Env', []) if not e.startswith("AZURITE_ACCOUNTS=")]
        accounts_str = ";".join(f"{n}:{k}" for n, k in _azurite_accounts.items())
        env.append(f"AZURITE_ACCOUNTS={accounts_str}")
        image = old.image.tags[0] if old.image.tags else AZURITE_DOCKER_IMAGE
        ports = {'10000/tcp': 10000, '10001/tcp': 10001, '10002/tcp': 10002}
        old.stop()
        old.remove()
        client.containers.run(
            image,
            name=_AZURITE_CONTAINER_NAME,
            environment=env,
            detach=True,
            ports=ports,
            entrypoint=["docker-entrypoint.sh"],
            command=["azurite", "-l", "/data", "--blobHost", "0.0.0.0", "--queueHost", "0.0.0.0", "--tableHost", "0.0.0.0"],
        )
    except Exception as e:
        LOG.warning("Failed to restart Azurite with accounts %s: %s", list(_azurite_accounts.keys()), e)


def _register_azurite_account(account_name: str, account_key_value: str) -> None:
    _azurite_accounts[account_name] = account_key_value
    _restart_azurite_with_accounts()


class AzuriteWrapper:
    """
    Wrapper around the Azurite container.
    Ideally we just start the Azurite container and tell the user to connect to the Docker IP, but there are some problems with that:

     - Hardcoded endpoints
         Users may have a hardcoded URL to {storage_account}.blob.core.microsoft.net
         If that's the case, we would need to intercept URL's to that address and redirect them regardless
     - Authorization
         Azurite is very strict about the Authorization-header - it needs to contain a predefined value
         But we don't know what Authorization the user will provide
     - Consistency
         Azurite needs to know in advance which storage accounts it can serve.
         We create a separate Azurite container for every storage account, which means that the docker IP is different for every storage account.

    Solution: A Wrapper that manages a Azurite container and handles communication to it.

    Users can talk to {accountName}.blob.core.windows.net like normal.
    The AzuriteWrapper then relays that request to the relevant Azurite container.
    Because we are in complete control of the communication with Azurite itself, we ensure that
     - we always only have a single Docker container running,
     - and the Authorization-header is correct.
    """

    def __init__(self, account_name: str) -> None:
        self.account_name = account_name
        self.docker_container_name = f"ls-storage-{self.account_name.lower()}"
        self.docker_host = "127.0.0.1"
        self.blob_port = 10000
        self.queue_port = 10001
        self.table_port = 10002

        # External Azurite running on host — no container to manage
        self.docker_host = "host.docker.internal"

        LOG.debug(f"External Azurite at host.docker.internal for {self.account_name}")
        _register_azurite_account(self.account_name, account_key)

        blob_host = get_blob_host(account_name)
        table_host = get_table_host(account_name)
        queue_host = get_queue_host(account_name)
        self.external_blob_endpoint = f"https://{blob_host}"
        self.external_table_endpoint = f"https://{table_host}"
        self.external_queue_endpoint = f"https://{queue_host}"

        self._routes = []
        # Configure the edge router to intercept all calls to BlobStorage
        for host in [blob_host, f"{account_name}.blob.core.windows.net"]:
            # Container Creation/Deletion should be handled separately, as we keep a local cache of the containers that are created in Azurite
            self._routes.append(
                ROUTER.add(  # type: ignore[call-overload]
                    path="/<container_name>",
                    host=blob_host,
                    endpoint=AzuriteWrapper.container_create,
                    methods=["PUT"],
                )
            )
            self._routes.append(
                ROUTER.add(  # type: ignore[call-overload]
                    path="/<container_name>",
                    host=blob_host,
                    endpoint=AzuriteWrapper.container_delete,
                    methods=["DELETE"],
                )
            )
            for path in ["/", "/<path:path>"]:
                self._routes.append(
                    ROUTER.add(path=path, host=host, endpoint=AzuriteWrapper.proxy_blob_request)  # type: ignore[call-overload]
                )
        # Configure the edge router to intercept all calls to TableStorage
        for host in [table_host, f"{account_name}.table.core.windows.net"]:
            for path in ["/", "/<path:path>"]:
                self._routes.append(
                    ROUTER.add(path=path, host=host, endpoint=AzuriteWrapper.proxy_table_request)  # type: ignore[call-overload]
                )
        # Configure the edge router to intercept all calls to QueueStorage
        for host in [queue_host, f"{account_name}.queue.core.windows.net"]:
            for path in ["/", "/<path:path>"]:
                self._routes.append(
                    ROUTER.add(path=path, host=host, endpoint=AzuriteWrapper.proxy_queue_request)  # type: ignore[call-overload]
                )

        self._route_lock = RLock()

    def stop_container(self) -> None:
        with self._route_lock:
            # The 'ROUTER.remove' method is not idempotent, so we have to manually ensure that we never remove the same route twice
            ROUTER.remove(self._routes)
            self._routes.clear()
        if hasattr(self, "container"):
            try:
                self.container.destroy()
                LOG.debug("Stopped container %s", self.container.id)
            except Exception as e:
                LOG.warning("Unable to remove container: %s", e)

    @staticmethod
    def proxy_blob_request(request: Request, path: str | None = None) -> Response:
        """
        Proxies a blob storage request to the appropriate Azure storage account if it exists.

        This method determines the target storage account based on the request's host. It
        iterates through the available storage stores to find a matching storage account. If
        found, it delegates the processing of the request to the azurite wrapper associated
        with the storage account, which proxies the request to the corresponding port. If no
        matching storage account is found, the method returns a "Storage Account Not Found"
        response.

        :param request: Request object containing information about the blob request to be proxied.
        :type request: Request
        :return: A tuple containing the HTTP status code, headers, and response body. If the
            storage account does not exist, it returns 404, an empty dictionary for headers, and
            a byte string stating "Storage Account Not Found".
        :rtype: tuple[int, dict[str, str], bytes]
        """
        # URL currently looks like this:
        #     {account_name}blob.localhost.localstack.cloud
        # The 'blob' suffix is there to differentiate from other storage types (table, queues)
        # Ideally we use different subdomains, like so:
        #     {account_name}.blobstorage.localhost.localstack.cloud
        # but we don't have a valid SSL certificate for subdomains yet.
        account = re.sub(rf"{HostnamePrefix.BLOB}$", "", request.host.split(".")[0])
        for subscription_id in storage_stores:
            for region in storage_stores[subscription_id]:
                if storage_account := storage_stores[subscription_id][region].storage_accounts.get(account):
                    return storage_account.azurite_wrapper.proxy_request(
                        request,
                        account=account,
                        port=storage_account.azurite_wrapper.blob_port,
                        compute_string_to_sign=string_to_sign_blob_storage,
                    )
        return Response(status=404, response=b"Storage Account Not Found")

    @staticmethod
    def proxy_table_request(request: Request, path: str | None = None) -> Response:
        """
        Handles a proxy request to the Azure Table Storage emulator for a given storage
        account. This method identifies the target storage account from the incoming
        request hostname and routes the request to the appropriate Azurite instance.
        If the storage account does not exist, it returns a 404 response.

        :param request:
            The HTTP request object to be proxied, containing all necessary information
            such as headers, body, and host.

        :return:
            A tuple containing:
            - The HTTP status code as an integer.
            - A dictionary of response headers.
            - A bytes object containing the response body data.
        """
        account = re.sub(rf"{HostnamePrefix.TABLE}$", "", request.host.split(".")[0])
        for subscription_id in storage_stores:
            for region in storage_stores[subscription_id]:
                if storage_account := storage_stores[subscription_id][region].storage_accounts.get(account):
                    return storage_account.azurite_wrapper.proxy_request(
                        request,
                        account=account,
                        port=storage_account.azurite_wrapper.table_port,
                        compute_string_to_sign=string_to_sign_table_storage,
                    )
        return Response(status=404, response=b"Storage Account Not Found")

    @staticmethod
    def proxy_queue_request(request: Request, path: str | None = None) -> Response:
        """
        Proxies a queue storage request to the appropriate Azure storage account if it exists.

        This method determines the target storage account based on the request's host. It
        iterates through the available storage stores to find a matching storage account. If
        found, it delegates the processing of the request to the azurite wrapper associated
        with the storage account, which proxies the request to the corresponding port. If no
        matching storage account is found, the method returns a "Storage Account Not Found"
        response.

        :param request: Request object containing information about the queue request to be proxied.
        :type request: Request
        :return: A tuple containing the HTTP status code, headers, and response body. If the
            storage account does not exist, it returns 404, an empty dictionary for headers, and
            a byte string stating "Storage Account Not Found".
        :rtype: tuple[int, dict[str, str], bytes]
        """
        account = re.sub(rf"{HostnamePrefix.QUEUE}$", "", request.host.split(".")[0])
        for subscription_id in storage_stores:
            for region in storage_stores[subscription_id]:
                if storage_account := storage_stores[subscription_id][region].storage_accounts.get(account):
                    # Assuming string_to_sign_queue_storage is available from .auth_utils
                    from .auth_utils import string_to_sign_queue_storage

                    return storage_account.azurite_wrapper.proxy_request(
                        request,
                        account=account,
                        port=storage_account.azurite_wrapper.queue_port,
                        compute_string_to_sign=string_to_sign_queue_storage,
                    )
        return Response(status=404, response=b"Storage Account Not Found")

    def proxy_request(
        self, request: Request, account: str, port: int, compute_string_to_sign: Callable[[Request, str], str]
    ) -> Response:
        """
        Proxy an HTTP request to a specified server port, modifying headers and generating the appropriate
        authorization string. This function communicates with an internal service or endpoint, transforming
        the incoming request to utilize specific host and account configurations. The function also logs
        request and response details for debugging, and handles different errors that might occur during
        the request process.

        :param request: The incoming HTTP request represented as a `Request` object. This contains the HTTP
            method, headers, data, path, and query string to be proxied.
        :type request: Request
        :param account: Which StorageAccount this request should go to
        :type account: str
        :param port: The port number to use for sending the proxied request.
        :type port: int
        :param compute_string_to_sign: A callable function that calculates the necessary string to sign
            for authorization based on the request and account name.
        :type compute_string_to_sign: Callable[[Request, str], str]
        :rtype: rolo.response.Response
        """
        # If localstack runs on the host on WSL, the host address is the 127.0.0.1, otherwise is the IP address of the container
        host = "127.0.0.1" if is_in_wsl and not is_in_docker else self.docker_host
        url = f"http://{host}:{port}/{account}{request.path}?{request.query_string.decode('utf-8')}"

        # Set the Host header
        request.headers["Host"] = f"{host}:{port}"

        # Set the Date header
        if "x-ms-date" in request.headers:
            request.headers["Date"] = request.headers["x-ms-date"]
        else:
            stamp = mktime(datetime.now().timetuple())
            request.headers["Date"] = format_date_time(stamp)

        # Compute the value for the Authorization header
        string_to_sign = compute_string_to_sign(request, account)
        signature1 = compute_hmac_sha256(data=string_to_sign, key=account_key)
        authValue1 = f"SharedKey {account}:{signature1}"
        request.headers["Authorization"] = authValue1

        # Remove Transfer-Encoding header before sending the request to Azurite
        if "Transfer-Encoding" in request.headers:
            del request.headers["Transfer-Encoding"]

        # Log the request
        log_request(url, request.method, None, dict(request.headers))

        try:
            resp = requests.request(
                method=request.method,
                url=url,
                headers=dict(request.headers),
                data=request.data,
                proxies={"http": "", "https": ""},
                allow_redirects=True,
                verify=False,
                timeout=30,
            )

            # Get the dictionary of response headers
            headers_dict = dict(resp.headers)

            # Log the response
            log_response(url, resp.status_code, resp.content, headers_dict)

            # Remove Transfer-Encoding header before sending the response back
            if "Transfer-Encoding" in headers_dict:
                del headers_dict["Transfer-Encoding"]

            rolo_response = Response()
            convert_to_response(
                service_response=(resp.status_code, headers_dict, resp.content), response=rolo_response
            )
            return rolo_response

        except requests.exceptions.Timeout:
            LOG.error(f"Request timed out while connecting to {url}")
            return Response(status=504, response=b"Gateway Timeout")
        except requests.exceptions.ConnectionError as e:
            LOG.error(f"Connection error while connecting to {url}: {str(e)}")
            return Response(status=503, response=b"Service Unavailable")
        except Exception as e:
            LOG.error(f"Unexpected error while making request to {url}: {str(e)}")
            return Response(status=500, response=str(e).encode())

    @staticmethod
    def container_create(request: Request, container_name: str) -> Response:
        # Azurite should be the source of truth for all our Storage data
        # When using the BlobStorage service, this is not a problem
        #
        # The (regular) Storage service also has CRUDL methods for containers though
        # Keeping track of containers ourselves is the easiest way to ensure the regular Storage service can Read/List containers

        account_name = request.host.split(".")[0].rstrip(HostnamePrefix.BLOB)
        resp = AzuriteWrapper.proxy_blob_request(request)

        # This method is invoked for every call to /{container_name}
        # Routing is different for different querystrings though, so we can only assume this is a `CreateContainer` call if the 'restype' is set
        if b"restype=container" in request.query_string:
            for subscription_id in storage_stores:
                for location in storage_stores[subscription_id]:
                    store = storage_stores[subscription_id][location]
                    if storage_account := store.storage_accounts.get(account_name):
                        storage_account.create_container(container_name)
        return resp

    @staticmethod
    def container_delete(request: Request, container_name: str) -> Response:
        account_name = request.host.split(".")[0].rstrip(HostnamePrefix.BLOB)

        response = AzuriteWrapper.proxy_blob_request(request)
        if response.status_code == 404:
            return response

        if b"restype=container" in request.query_string:
            for subscription_id in storage_stores:
                for location in storage_stores[subscription_id]:
                    store = storage_stores[subscription_id][location]
                    if storage_account := store.storage_accounts.get(account_name):
                        storage_account.delete_container(container_name)
        return response

    def _create_port_mappings(self) -> PortMappings:
        """
        Creates and configures port mappings based on the provided account name. For specific account
        names, fixed ports are added. For other accounts, free TCP ports are dynamically selected
        and added to the mappings.

        :param account_name: The name of the storage account for which port mappings are to be created.
        :type account_name: str
        :return: A configured `PortMappings` instance containing the mapped ports.
        :rtype: PortMappings
        """
        port_mappings = PortMappings()
        if self.account_name == AZURE_MANAGED_STORAGE_ACCOUNT_NAME:
            self.blob_port = 10000
            self.queue_port = 10001
            self.table_port = 10002
        else:
            self.blob_port = dynamic_port_range.reserve_port()
            self.queue_port = dynamic_port_range.reserve_port()
            self.table_port = dynamic_port_range.reserve_port()

        port_mappings.add(self.blob_port, 10000)
        port_mappings.add(self.queue_port, 10001)
        port_mappings.add(self.table_port, 10002)

        LOG.debug(
            f"AzuriteWrapper: Using {self.blob_port}:10000, {self.queue_port}:10001, {self.table_port}:10002 port mappings for storage account {self.account_name}",
        )
        return port_mappings
