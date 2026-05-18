# Patch for licensingv2.py
# Replace the following block in LicensedPluginLoaderGuard.on_init_after:

# OLD:
#             return  # raise PluginDisabled(f"Plugin {product_name} is disabled since it is not part of the current license agreement")

# NEW:
#             return  # license check bypassed
