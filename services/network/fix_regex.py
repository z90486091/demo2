#!/usr/bin/env python3
path = '/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/deployments/models.py'
with open(path, 'r') as f:
    content = f.read()

# The regex: after capturing the resource name, it has \)\) (two close parens).
# The actual ARM expression only has one ) before the comma, then 'API-VERSION')
# Fix: change \)\) to \) so regex expects: resourceId('TYPE', 'NAME'), 'API')
old_str = r"'([^']+)'\),\s*'([^']+)'\)"
new_str = r"'([^']+)',\s*'([^']+)'\)"

content = content.replace(old_str, new_str, 1)

with open(path, 'w') as f:
    f.write(content)
print('Fixed regex in models.py')
