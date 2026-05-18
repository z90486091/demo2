#!/usr/bin/env python3
path = '/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/deployments/models.py'
with open(path, 'r') as f:
    content = f.read()

# Add debug log in _resolve_reference_expressions after the early return check
old1 = '        if not self.properties.parameters:\n            return\n        proxy_port'
new1 = '        if not self.properties.parameters:\n            return\n        LOG.debug("Resolving references for %s params=%s", self.name, list(self.properties.parameters.keys()))\n        proxy_port'
content = content.replace(old1, new1, 1)

# Log when no match
old2 = '            if not match:\n                continue'
new2 = '            if not match:\n                LOG.debug("Param %s not a reference: %s", param_name, str(value)[:80])\n                continue'
content = content.replace(old2, new2, 1)

# Log successful resolution
old3 = '                    if resolved is not None:\n                        param_info["value"] = resolved\n                        LOG.debug('
new3 = '                    if resolved is not None:\n                        param_info["value"] = resolved\n                        LOG.debug("RESOLVED %s=%s", param_name, str(resolved)[:60])\n                        LOG.debug('
content = content.replace(old3, new3, 1)

with open(path, 'w') as f:
    f.write(content)
print('Added debug logging')
