import logging

from rolo.gateway import Handler, HandlerChain, RequestContext
from rolo.request import Request
from rolo.resource import Resource
from rolo.response import Response
from rolo.routing import Router, handler_dispatcher
from werkzeug.exceptions import NotFound

from localstack.utils.analytics.metadata import (
    get_localstack_edition,
    is_license_activated,
)
from localstack.utils.objects import singleton_factory

LOG = logging.getLogger(__name__)


class LocalstackResourceHandler(Handler):
    """
    Adapter to serve LocalstackResources as a Handler.
    """

    def __call__(self, chain: HandlerChain, context: RequestContext, response: Response):
        try:
            response.update_from(get_internal_apis().dispatch(context.request))
            chain.stop()
        except NotFound:
            path = context.request.path
            if path.startswith("/_localstack/"):
                # only return 404 if we're accessing an internal resource, otherwise fall back to the other handlers
                LOG.warning("Unable to find resource handler for path: %s", path)
                chain.respond(404)


class HealthResource:
    def on_post(self, request: Request):
        return Response("ok", 200)

    def on_get(self, request: Request):
        result = {
            "edition": get_localstack_edition(),
            "license": is_license_activated(),
        }
        return result

    def on_head(self, request: Request):
        return Response("ok", 200)

    def on_put(self, request: Request):
        return {"status": "OK"}


class ProxyResource:
    """
    Endpoint that returns the port that the proxy runs on.

    If downstream clients (SDK's, CLI's) want to use the proxy to use to our emulator, they should call this endpoint to determine which port to connect to.
    """

    def on_get(self, request: Request):
        """
        Returns a JSON object with the port that the proxy runs on
        """
        # Start the proxy (if it hasn't been started yet), and get the port it's listening on
        from localstack.pro.azure.server.proxy.server import start_proxy

        proxy_port = start_proxy()

        return {"proxy_port": proxy_port}


class MetadataEndpointsResource:
    def on_get(self, request: Request):
        return {
            "name": "AzureCloud",
            "galleryEndpoint": "http://localhost:4510/",
            "graphEndpoint": "http://localhost:4510/",
            "portalEndpoint": "http://localhost:4510/",
            "authentication": {
                "loginEndpoint": "http://localhost:4510/",
                "audiences": ["http://localhost:4510/"],
            },
            "resourceManager": "http://localhost:4510/",
            "suffixes": {
                "storageEndpoint": "localhost",
                "keyVaultDns": ".localhost",
                "sqlServerHostname": ".localhost",
            },
        }


class LocalstackResources(Router):
    """
    Router for localstack-internal HTTP resources.
    """

    def __init__(self):
        super().__init__(dispatcher=handler_dispatcher())
        self.add_default_routes()

    def add_default_routes(self):
        self.add(Resource("/_localstack/health", HealthResource()))
        self.add(Resource("/_localstack/proxy", ProxyResource()))
        self.add(Resource("/metadata/endpoints", MetadataEndpointsResource()))


@singleton_factory
def get_internal_apis() -> LocalstackResources:
    """
    Get the LocalstackResources singleton.
    """
    return LocalstackResources()
