import sys
sys.path.insert(0, '/opt/code/localstack/localstack-pro-azure/.venv/lib/python3.11/site-packages')

# Import the plugins module to register all providers
import localstack.pro.azure.services.plugins as plugins_mod

pm = plugins_mod.plugin_manager

# Check internal source
src = pm._source
print(f"Source: {type(src).__name__}")

if hasattr(src, '_namespace'):
    print(f"Namespace: {src._namespace}")

# List all specs
specs = src.list_specs() if hasattr(src, 'list_specs') else []
for s in specs:
    print(f"  Spec: {s}")

print(f"Total specs: {len(specs)}")

# Check if the PluginSpec for Microsoft.Network exists in the module
for attr_name in dir(plugins_mod):
    attr = getattr(plugins_mod, attr_name)
    from plux import PluginSpec
    if isinstance(attr, PluginSpec):
        print(f"  PluginSpec in module: {attr_name} -> {attr}")
