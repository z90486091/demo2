#!/usr/bin/env python3
import re
import sys

# Test the regex pattern from models.py against the actual ARM parameter value
test_val = "[reference(resourceId('Microsoft.Resources/deployments', 'deploy-hub'), '2025-04-01').outputs.hubVnetName.value]"

# Pattern from our models.py fix
pattern = re.compile(
    r"\[reference\(resourceId\('([^']+)',\s*'([^']+)'\),\s*'([^']+)'\)\.(.+)\]"
)

match = pattern.match(test_val)
if match:
    print("MATCHED!")
    print(f"  resource_type: {match.group(1)}")
    print(f"  resource_name: {match.group(2)}")
    print(f"  api_version: {match.group(3)}")
    print(f"  path: {match.group(4)}")
else:
    print("NO MATCH - regex issue")

# Check what's in models.py
with open("/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/deployments/models.py") as f:
    content = f.read()

# Find the pattern string in the code
idx = content.find("pattern = _re.compile")
if idx >= 0:
    # Print 200 chars around it
    print("\n--- Actual code ---")
    print(content[idx:idx+300])
