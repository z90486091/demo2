# LocalStack Azure Storage Patch Guide

This repository contains patches to enable `Microsoft.Storage/storageAccounts` creation and usage in the LocalStack Azure alpha image.

## Goal
Enable end-to-end creation of Azure Storage Accounts using Bicep/ARM templates, ensuring that the storage accounts are correctly provisioned in an external Azurite instance and that the LocalStack API returns `provisioningState: Succeeded`.

## Patched Files
The following files are patched and stored in the `localstack-patches/` directory:

1. **`licensingv2.py`**: Bypasses the license check for Azure plugins to allow them to load without a paid subscription.
2. **`provider_azurite.py`**: 
   - Replaces internal Docker container management with a connection to an external Azurite instance at `host.docker.internal`.
   - Implements `_restart_azurite_with_accounts()` to dynamically provision new storage accounts in the external Azurite container by updating the `AZURITE_ACCOUNTS` environment variable.
   - Ensures the default `devstoreaccount1` is always preserved.
   - Guards `stop_container()` to prevent `AttributeError` when no internal container exists.
3. **`models.py`**:
   - Wraps `AzuriteWrapper` initialization in a try/except block to prevent async creation threads from crashing.
   - Adds null guards to `response()` and `delete_resource()` when accessing the `azurite_wrapper`.

## DevGuide: How to Apply Patches

### Prerequisites
- LocalStack Azure container running (e.g., `da4ee600dc46`).
- External Azurite container running as a sibling on `localhost:10000/10001/10002`.
- 

Pre-requisite: Run azurite docker container
`docker run -d --name azurite \
  -p 10000:10000 -p 10001:10001 -p 10002:10002 \
  mcr.microsoft.com/azure-storage/azurite`

### Application Steps
Apply the patches to the `.venv` installed path (which is what runs at runtime) and the source path for consistency.

```bash
# 1. Patch provider_azurite.py
docker cp localstack-patches/provider_azurite.py <container_id>:/opt/code/localstack/localstack-pro-azure/.venv/lib/python3.11/site-packages/localstack/pro/azure/services/storage/dataplane/provider_azurite.py
docker cp localstack-patches/provider_azurite.py <container_id>:/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/storage/dataplane/provider_azurite.py

# 2. Patch models.py
docker cp localstack-patches/models.py <container_id>:/opt/code/localstack/localstack-pro-azure/.venv/lib/python3.11/site-packages/localstack/pro/azure/services/storage/storage/models.py
docker cp localstack-patches/models.py <container_id>:/opt/code/localstack/localstack-pro-azure/localstack/pro/azure/services/storage/storage/models.py

# 3. Patch licensingv2.py (Manual edit or script)
# Replace 'raise PluginDisabled(...)' with 'return' in LicensedPluginLoaderGuard.on_init_after

# 4. Restart container
docker restart <container_id>
sleep 15
```

## Validation Sequence

### 1. Create Resource Group
```bash
curl -s -X PUT "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-storage-test?api-version=2021-04-01" \
  -H "Content-Type: application/json" -H "Authorization: Bearer faketoken" \
  -d '{"location":"eastus"}'
```

### 2. Create Storage Account
```bash
curl -s -X PUT "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-storage-test/providers/Microsoft.Storage/storageAccounts/teststore123?api-version=2022-09-01" \
  -H "Content-Type: application/json" -H "Authorization: Bearer faketoken" \
  -d '{"location":"eastus","sku":{"name":"Standard_LRS"},"kind":"StorageV2"}'
```

### 3. Verify Provisioning State
```bash
curl -s "http://localhost:4510/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/rg-storage-test/providers/Microsoft.Storage/storageAccounts/teststore123?api-version=2022-09-01" \
  -H "Authorization: Bearer faketoken" | jq '.properties.provisioningState'
# Expected: "Succeeded"
```

### 4. Test Blob Operation (Direct Azurite)
```bash
# Note: Requires computed SharedKey auth for the specific account
curl -s -X PUT "http://localhost:10000/teststore123/test-container?restype=container" \
  -H "x-ms-date: $(date -u '+%a, %d %b %Y %H:%M:%S GMT')" \
  -H "x-ms-version: 2020-10-02" \
  -H "Authorization: SharedKey teststore123:<computed_signature>"
# Expected: HTTP 201
```
## Success Criteria
- [x] Storage Account GET returns `"provisioningState": "Succeeded"`
- [x] No `ResourceNotFound` or `ContainerException` in logs after creation
- [x] Azurite connectivity confirmed from inside container (`host.docker.internal:10000`)
- [x] Blob container creation via port 10000 returns 201
