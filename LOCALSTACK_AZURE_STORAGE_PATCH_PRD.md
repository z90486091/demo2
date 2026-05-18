# PRD: Patch LocalStack Azure Image for Storage Account Support

## Context

- **Image**: `localstack/localstack-azure-alpha:8a3d8a4e462fe9f3b305f4076a3050e8fd1750de`
- **Container**: `da4ee600dc46`
- **Azurite**: Running as sibling container on `localhost:10000/10001/10002`
- **Goal**: Make `Microsoft.Storage/storageAccounts` CREATE work via Bicep deployment

## What Has Already Been Done

1. `licensingv2.py:1294` — `raise PluginDisabled(...)` replaced with `return  # license check bypassed`
2. `provider_azurite.py` — Docker container spinup block commented out, replaced with `self.docker_host = "host.docker.internal"`

## Current Failure

Storage account PUT returns HTTP 202 (accepted) but async creation fails with:

```
ResourceNotFound: ('Resource group', 'rg-test')
```

Traceback:
```
provider.py:260 → _create_account_async
  → StorageAccount(parameters)
  → models.py:69 → super().__init__()
  → utilities/models.py:34 → get_resource_group(subscription_id, name=resource_group_name)
  → resources/models.py:83 → raise ResourceNotFound("Resource group", name)
```

The RG DOES exist (confirmed via GET). The issue is `get_resource_group()` is looking it up with wrong keys (wrong subscription_id or region/location key) in the resource store.

## Task: What the Agent Must Do

### Step 1: Read and understand the bug (no coding yet)

```bash
docker exec da4ee600dc46 cat /opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/resources/models.py | grep -n "get_resource_group" -A 20 | head -40

docker exec da4ee600dc46 cat /opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/utilities/models.py | head -60

docker exec da4ee600dc46 sed -n '250,270p' /opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/storage/storage/provider.py

docker exec da4ee600dc46 sed -n '60,90p' /opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/storage/storage/models.py
```

Understand:
- What keys does `get_resource_group()` use to look up the RG?
- What keys does the storage `_create_account_async` pass as `subscription_id` and `resource_group_name`?
- Are there any region/location mismatches?

### Step 2: Fix `get_resource_group` lookup or the parameters passed to it

The fix is likely one of:
- The subscription_id being passed is wrong (e.g. None or different format)
- The region key used to look up the store doesn't match where the RG was stored
- `get_resource_group` iterates incorrectly over the store

Fix whichever is wrong. Do NOT rewrite the whole storage provider — minimal surgical fix only.

### Step 3: Fix `stop_container` method

`AzuriteWrapper.stop_container()` calls `self.container.destroy()` which will fail since there's no container object. Patch it:

File: `/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/storage/dataplane/provider_azurite.py`

Find `stop_container` method and replace `self.container.destroy()` with `pass  # external Azurite, no container to destroy`

### Step 4: Fix port mapping

The external Azurite is on `localhost:10000/10001/10002` but LocalStack is in a container. `host.docker.internal` resolves correctly on Docker Desktop/OrbStack on Mac — verify this works by running inside the container:

```bash
docker exec da4ee600dc46 curl -s http://host.docker.internal:10000/ 2>&1 | head -5
```

If it fails, find the host IP and use that instead:
```bash
docker exec da4ee600dc46 cat /etc/hosts | grep host
# or
docker inspect da4ee600dc46 | grep Gateway
```

### Step 5: Verify end-to-end

After each fix, apply via `docker cp` + `docker restart da4ee600dc46`, then run:

```bash
# 1. Create RG
curl -s -X PUT \
  "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-storage-test?api-version=2021-04-01" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer faketoken" \
  -d '{"location":"eastus"}'

sleep 2

# 2. Create Storage Account
curl -s -X PUT \
  "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-storage-test/providers/Microsoft.Storage/storageAccounts/teststore123?api-version=2022-09-01" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer faketoken" \
  -d '{"location":"eastus","sku":{"name":"Standard_LRS"},"kind":"StorageV2"}'

sleep 10

# 3. Check logs — must NOT contain ResourceNotFound or ContainerException
docker logs da4ee600dc46 --tail 20 2>&1 | grep -E "ERROR|Exception|Succeeded|Azurite"

# 4. GET the storage account — must return provisioningState: Succeeded
curl -s \
  "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-storage-test/providers/Microsoft.Storage/storageAccounts/teststore123?api-version=2022-09-01" \
  -H "Authorization: Bearer faketoken"

# 5. Test actual blob operation via Azurite
curl -s -X PUT \
  "http://localhost:10000/teststore123/test-container?restype=container" \
  -H "x-ms-date: $(date -u '+%a, %d %b %Y %H:%M:%S GMT')" \
  -H "x-ms-version: 2020-10-02"
```

## Success Criteria

- [ ] Storage Account GET returns `"provisioningState": "Succeeded"`
- [ ] No `ResourceNotFound` or `ContainerException` in logs after creation
- [ ] Azurite connectivity confirmed from inside container (`host.docker.internal:10000`)
- [ ] Blob container creation via port 10000 returns 201

## Files to Touch (and save locally to `localstack-patches/`)

1. `services/storage/storage/models.py` or `services/resources/models.py` — fix RG lookup
2. `services/storage/dataplane/provider_azurite.py` — fix `stop_container`
3. Possibly `services/storage/storage/provider.py` — fix parameters passed to StorageAccount

## DO NOT

- Rewrite the entire storage provider
- Touch `licensingv2.py` again
- Touch `routing.py` or `plugins.py`
- Declare success until the GET curl returns `Succeeded`