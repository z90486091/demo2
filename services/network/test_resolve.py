#!/usr/bin/env python3
"""Test the reference resolution in isolation."""
import sys
sys.path = [
    "/opt/code/localstack/localstack-pro-azure/.venv/lib/python3.11/site-packages",
    "/opt/code/localstack/localstack-pro-azure",
    "/opt/code/localstack/localstack-pro-core/.venv/lib/python3.11/site-packages",
] + sys.path

import logging
logging.basicConfig(level=logging.DEBUG)

# Directly test the regex and HTTP resolution
import re
import requests

from localstack.pro.azure.server.proxy.server import start_proxy
from localstack import config
from localstack.pro.core.certificates.plugins import default_cert_store

pattern = re.compile(
    r"\[reference\(resourceId\('([^']+)',\s*'([^']+)'\),\s*'([^']+)'\)\.(.+)\]"
)

test_val = "[reference(resourceId('Microsoft.Resources/deployments', 'deploy-hub'), '2025-04-01').outputs.hubVnetName.value]"
match = pattern.match(test_val)
if match:
    print(f"Matched: type={match.group(1)} name={match.group(2)} api={match.group(3)} path={match.group(4)}")
    
    proxy_port = start_proxy()
    internal_host = config.GATEWAY_LISTEN[0].host
    ca_cert = default_cert_store().root_ca_cert_path
    
    sub = "00000000-0000-0000-0000-000000000000"
    rg = "rg-hub-spoke"
    resource_type = match.group(1)
    resource_name = match.group(2)
    api_version = match.group(3)
    path = match.group(4)
    
    url = f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/{resource_type}/{resource_name}?api-version={api_version}"
    print(f"\nGET URL: {url}")
    
    try:
        resp = requests.get(
            url=url,
            verify=ca_cert,
            proxies={"https": f"{internal_host}:{proxy_port}"},
        )
        print(f"Response status: {resp.status_code}")
        print(f"Response body: {resp.text[:500]}")
        if resp.ok:
            data = resp.json()
            print(f"\nParsed JSON keys: {list(data.keys())}")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("No match!")
