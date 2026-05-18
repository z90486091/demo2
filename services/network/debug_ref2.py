#!/usr/bin/env python3
import sys
sys.path = [
    "/opt/code/localstack/localstack-pro-azure/.venv/lib/python3.11/site-packages",
    "/opt/code/localstack/localstack-pro-azure",
    "/opt/code/localstack/localstack-pro-core/.venv/lib/python3.11/site-packages",
] + sys.path

import re

# Copy the regex from models.py
pattern = re.compile(
    r"\[reference\(resourceId\('([^']+)',\s*'([^']+)'\),\s*'([^']+)'\)\.(.+)\]"
)

test_val = "[reference(resourceId('Microsoft.Resources/deployments', 'deploy-hub'), '2025-04-01').outputs.hubVnetName.value]"
match = pattern.match(test_val)
if match:
    print("MATCHED!")
    print(f"  type: {match.group(1)}")
    print(f"  name: {match.group(2)}")
    print(f"  api: {match.group(3)}")
    print(f"  path: {match.group(4)}")
else:
    print("NO MATCH")

# Check patterns
test_val2 = "[reference(resourceId('Microsoft.Network/virtualNetworks', 'vnet-hub'), '2023-04-01').subnets[1].id]"
match2 = pattern.match(test_val2)
if match2:
    print("MATCHED pattern2!")
    print(f"  type: {match2.group(1)}")
    print(f"  name: {match2.group(2)}")
    print(f"  api: {match2.group(3)}")
    print(f"  path: {match2.group(4)}")
else:
    print("NO MATCH pattern2")

# Check if the method call is in __init__
with open("/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/deployments/models.py") as f:
    content = f.read()

idx = content.find("_resolve_reference_expressions")
if idx >= 0:
    start = max(0, idx - 100)
    end = min(len(content), idx + 100)
    print(f"\nFound at position {idx}")
    print(repr(content[start:end]))
else:
    print("\n_resolve_reference_expressions NOT FOUND in models.py!")
