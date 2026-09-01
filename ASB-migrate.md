# Azure Service Bus (ASB) Summary

## Reverse Engineering to Bicep
- **Cloud Shell:** 
  `az group export --name <rg-name> --resource-ids <service-bus-id> | az bicep decompile --file /dev/stdin`
- **Portal:** Export template -> `az bicep decompile --file template.json`

## SKU Options
- **Basic:** Queues only, 256 KB max, pay-per-operation.
- **Standard:** Queues, topics, transactions, 256 KB max.
- **Premium:** Dedicated, up to 100 MB max, VNet, Geo-DR.

## Migration (Without Data Loss)
- **Standard to Premium:** Built-in tool.
- **Basic to Premium:** Upgrade to Standard first.
- **CLI (Std to Prem):**
  `az servicebus namespace migration start -g <rg> -n <std-name> --target-namespace-id <prem-id> --post-migration-name <alias>`
