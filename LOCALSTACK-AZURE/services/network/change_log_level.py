#!/usr/bin/env python3
path = "/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/deployments/models.py"
with open(path, "r") as f:
    content = f.read()

content = content.replace('LOG.debug("Resolving references for', 'LOG.warning("Resolving references for')
content = content.replace('LOG.debug("Param %s not a reference', 'LOG.warning("Param %s not a reference')
content = content.replace('LOG.debug("RESOLVED %s=%s"', 'LOG.warning("RESOLVED %s=%s"')
content = content.replace('LOG.debug("Failed to resolve reference', 'LOG.warning("Failed to resolve reference')
content = content.replace('LOG.debug(\n                            "Resolved reference', 'LOG.warning(\n                            "Resolved reference')

with open(path, "w") as f:
    f.write(content)
print("done")
