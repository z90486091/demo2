import importlib.metadata as md

# Check entry points in our namespace
eps = md.entry_points(group="localstack.azure.provider")
print(f"Found {len(list(eps))} entry points in localstack.azure.provider:")
for ep in eps:
    print(f"  {ep.name} -> {ep.value}")

print()

# Check all distributions with "localstack" in name
dists = list(md.distributions())
for d in dists:
    if "localstack" in d.name:
        print(f"{d.name} {d.version}")
        # Check entry points for this dist
        try:
            dist_eps = d.entry_points
            provider_eps = [e for e in dist_eps if e.group == "localstack.azure.provider"]
            if provider_eps:
                print(f"  -> {len(provider_eps)} localstack.azure.provider entry points")
                for ep in provider_eps:
                    print(f"     {ep.name}: {ep.value}")
        except:
            pass
