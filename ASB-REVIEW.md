Yes — here’s the final **offline pre-cutover audit script**. It produces **one JSON audit file containing namespace config, queues, and queue authorization rules** for every Service Bus namespace in the resource group.

 Final Azure Service Bus Pre-Cutover Audit Script

```bash
#!/usr/bin/env bash
# sweep-asb-precutover.sh
#
# Offline/pre-cutover Azure Service Bus configuration audit.
# Dumps one JSON audit file containing:
#   - Namespace-level configuration
#   - All queues and key tunable properties
#   - Queue-level authorization rules
#
# Requirements:
#   - Azure CLI
#   - jq
#   - Logged-in Azure CLI session with permission to read Service Bus resources
#
# Usage:
#   RG="<resource-group>" ./sweep-asb-precutover.sh
#
# Or:
#   export RG="<resource-group>"
#   ./sweep-asb-precutover.sh
#
# Output:
#   ./asb-precutover-audit-<timestamp>/
#     <namespace>.json
#     ...
#     summary.json

set -euo pipefail

: "${RG:?Set RG to the target resource group, e.g. RG=my-servicebus-rg}"

OUT_DIR="./asb-precutover-audit-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"

echo "Starting Azure Service Bus pre-cutover audit"
echo "Resource group: $RG"
echo "Output directory: $OUT_DIR"
echo

# ---------------------------------------------------------------------------
# Discover namespaces.
# Using name + resourceGroup keeps this easy to extend if namespaces span RGs.
# ---------------------------------------------------------------------------

mapfile -t NAMESPACES < <(
  az servicebus namespace list \
    --query "[?resourceGroup=='${RG}'].[name,resourceGroup]" \
    -o tsv
)

if [[ ${#NAMESPACES[@]} -eq 0 ]]; then
  echo "ERROR: No Service Bus namespaces found in resource group '$RG'." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Audit each namespace.
# ---------------------------------------------------------------------------

for NS_ROW in "${NAMESPACES[@]}"; do
  NS="${NS_ROW%%$'\t'*}"
  NS_RG="${NS_ROW#*$'\t'}"

  echo "Auditing namespace: $NS"

  # -------------------------------------------------------------------------
  # Namespace-level configuration
  # -------------------------------------------------------------------------

  NS_JSON="$(
    az servicebus namespace show \
      --resource-group "$NS_RG" \
      --name "$NS" \
      -o json
  )"

  NAMESPACE_CONFIG="$(
    jq '{
      name,
      resourceGroup,
      location,
      sku: (
        if (.sku | type) == "object"
        then {
          name: .sku.name,
          tier: .sku.tier,
          capacity: .sku.capacity
        }
        else .sku
        end
      ),
      zoneRedundant,
      premiumMessagingPartitions,
      minimumTlsVersion,
      publicNetworkAccess,
      disableLocalAuth
    }' <<< "$NS_JSON"
  )"

  # -------------------------------------------------------------------------
  # Queues + queue-level authorization rules
  # -------------------------------------------------------------------------

  QUEUE_AUDIT='[]'

  mapfile -t QUEUES < <(
    az servicebus queue list \
      --resource-group "$NS_RG" \
      --namespace-name "$NS" \
      --query "[].name" \
      -o tsv
  )

  for QUEUE in "${QUEUES[@]}"; do
    [[ -z "$QUEUE" ]] && continue

    echo "  Queue: $QUEUE"

    QUEUE_JSON="$(
      az servicebus queue show \
        --resource-group "$NS_RG" \
        --namespace-name "$NS" \
        --name "$QUEUE" \
        -o json
    )"

    AUTHZ_JSON="$(
      az servicebus queue authorization-rule list \
        --resource-group "$NS_RG" \
        --namespace-name "$NS" \
        --queue-name "$QUEUE" \
        -o json
    )"

    QUEUE_RECORD="$(
      jq \
        --argjson authz "$AUTHZ_JSON" \
        '{
          name,
          lockDuration,
          maxDeliveryCount,
          defaultMessageTimeToLive,
          deadLetteringOnMessageExpiration,
          requiresSession,
          requiresDuplicateDetection,
          duplicateDetectionHistoryTimeWindow,
          enablePartitioning,
          enableBatchedOperations,
          maxSizeInMegabytes,
          status,
          authorizationRules: (
            $authz
            | map({
                name,
                rights
              })
          )
        }' <<< "$QUEUE_JSON"
    )"

    QUEUE_AUDIT="$(
      jq \
        --argjson queue "$QUEUE_RECORD" \
        '. + [$queue]' <<< "$QUEUE_AUDIT"
    )"
  done

  # -------------------------------------------------------------------------
  # Final namespace audit document.
  # -------------------------------------------------------------------------

  jq -n \
    --arg auditType "azure-servicebus-precutover" \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg namespace "$NS" \
    --arg resourceGroup "$NS_RG" \
    --argjson namespaceConfig "$NAMESPACE_CONFIG" \
    --argjson queues "$QUEUE_AUDIT" \
    '{
      auditType: $auditType,
      generatedAt: $generatedAt,
      namespace: $namespace,
      resourceGroup: $resourceGroup,
      namespaceConfig: $namespaceConfig,
      queues: $queues
    }' \
    > "$OUT_DIR/${NS}.json"

done

# ---------------------------------------------------------------------------
# Generate a compact summary for review.
# ---------------------------------------------------------------------------

jq -s '
  {
    auditType: "azure-servicebus-precutover-summary",
    generatedAt: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
    namespaces: [
      .[] | {
        namespace,
        resourceGroup,
        sku: .namespaceConfig.sku,
        zoneRedundant: .namespaceConfig.zoneRedundant,
        premiumMessagingPartitions: .namespaceConfig.premiumMessagingPartitions,
        minimumTlsVersion: .namespaceConfig.minimumTlsVersion,
        publicNetworkAccess: .namespaceConfig.publicNetworkAccess,
        disableLocalAuth: .namespaceConfig.disableLocalAuth,
        queueCount: (.queues | length),
        queuesWithInfiniteTtl: (
          [.queues[] | select(
            .defaultMessageTimeToLive == "P10675199DT2H48M5.4775807S"
            or .defaultMessageTimeToLive == "10675199.02:48:05.4775807"
          )] | length
        ),
        queuesRequiringSessions: (
          [.queues[] | select(.requiresSession == true)] | length
        ),
        partitionedQueues: (
          [.queues[] | select(.enablePartitioning == true)] | length
        )
      }
    ]
  }
' "$OUT_DIR"/*.json > "$OUT_DIR/summary.json"

echo
echo "Audit complete."
echo "Results:"
echo "  $OUT_DIR/"
echo
echo "Review namespace JSON files plus:"
echo "  $OUT_DIR/summary.json"
```

 ### What this gives you

 Each namespace gets a self-contained audit document:

```json
{
  "namespaceConfig": { ... },
  "queues": [
    {
      "name": "...",
      "lockDuration": "...",
      "maxDeliveryCount": 10,
      "defaultMessageTimeToLive": "...",
      "requiresSession": true,
      "enablePartitioning": false,
      "authorizationRules": [
        {
          "name": "...",
          "rights": ["Listen"]
        }
      ]
    }
  ]
}
```

 For your **15 Premium queues**, I would specifically review these before approving cutover:

 - **TTL:** verify infinity is deliberate. If it is, document the operational mechanism for detecting unbounded queue growth.
- **`maxDeliveryCount`:** confirm the value is intentional because expiration won't provide a DLQ path when TTL is effectively infinite.
- **`requiresSession`:** validate against the actual ordering/FIFO requirement for each queue.
- **`enablePartitioning`:** flag any unexpected `true` values, particularly on Premium.
- **Authorization rules:** verify each queue exposes only the rights its publisher/consumer actually needs.
- **`publicNetworkAccess`:** confirm the intended private/public network architecture is already enforced.
- **`minimumTlsVersion`:** verify the value is compatible with the JBoss/JMS client while meeting the security requirement.
- **Premium capacity:** confirm messaging-unit capacity and, where applicable, Premium partition configuration are sized for production.
- **Geo-DR:** verify the pairing separately if it is part of the production resilience requirement.
- **Diagnostic settings:** verify Log Analytics/Azure Monitor wiring separately; diagnostic settings aren't represented by the queue/namespace properties above.

 One important distinction: this script is deliberately **configuration/readiness-only**. It does **not** collect runtime message counts, latency, throughput, or other metrics, which is appropriate for an offline pre-cutover review.
