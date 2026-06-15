#!/usr/bin/env python3
path = '/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/deployments/models.py'
with open(path, 'r') as f:
    content = f.read()

# The bug: regex has \)\) (two escaped close-parens) after the name capture group
# Old: '([^']+)'\)), ,\s*'([^']+)'\)    <- this matches "NAME')), 'API')"
# Need: '([^']+)'\),\s*'([^']+)'\)        <- this matches "NAME'), 'API')"

# In the file the raw string contains: '([^']+)'\)\),
# We need to change it to: '([^']+)'\),

# The exact text in the file after the resource name capture group is:
# '([^']+)'\)\),\s*'([^']+)'\)\.(.+)\]
# We need to remove one \):
# '([^']+)'\),\s*'([^']+)'\)\.(.+)\]

old = "'([^']+)'\\)\\),"  # catches 'name')),
new = "'([^']+)'\\),"     # changes to 'name'),
# BUT WAIT: 'name'\)), contains: apostrophe, name, apostrophe, ), ), comma
# We want:  'name'),           contains: apostrophe, name, apostrophe, ), comma

# Let me find it differently. The file has: '([^']+)'\)\),
# We need to replace: \)\), with \),
# In file text: \)\), is the literal characters: backslash, paren, backslash, paren, comma
# We want: \), is the literal characters: backslash, paren, comma

# So replace the literal string: \)\), with \),
content = content.replace("\\)\\),", "\\),", 1)

with open(path, 'w') as f:
    f.write(content)

# Verify
with open(path, 'r') as f:
    for i, line in enumerate(f, 1):
        if 'resourceId' in line:
            print(f"Line {i}: {line.rstrip()}")

print('Done')
