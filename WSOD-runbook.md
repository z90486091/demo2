## SWA diagnostic categories:

- **`StaticSiteDiagnosticLogs`** — platform-level events (deployments, auth, function assignment), includes a `correlationId` field per request.
- **`StaticSiteHttpLogs`** — actual HTTP request logs (this is the one you want for header/timestamp correlation).
- Neither supports Basic Logs plan or ingestion-time transforms; both only export via Diagnostic Settings (Log Analytics, Storage, or Event Hub) — **must be enabled ahead of time**, they don't backfill.
- If no Diagnostic Setting was configured on the SWA resource before your incident window, these logs simply don't exist for that period — check `Microsoft.Insights/diagnosticSettings` on the resource now, and enable both categories going forward.
- 
## Trace AGW -> APIM
  
1. Open the App GatewayPortal search bar -> your AGW name -> left menu -> "Backend pools". Note the FQDN/IP listed there (this should point at one specific APIM).
2. Cross-check via Backend settingsLeft menu -> "Backend settings" -> open each setting -> check "Override with new hostname" / hostname field, since the pool target and the Host header sent can differ.
3. Confirm via RulesLeft menu -> "Rules" (Request routing rules) -> click each rule -> shows which Listener maps to which Backend pool + Backend setting pair, in one screen.
4. Match against APIM Custom domainsGo to each candidate APIM instance -> left menu -> "Custom domains" -> compare the Gateway hostname/custom domain listed there against the FQDN found in step 1/2.
5. Use APIM's own diagnostic tool if still ambiguousOn the APIM instance -> left menu -> "Network" or "Custom domains" won't show inbound callers directly, so if multiple AGWs could match the same hostname pattern, fall back to checking each AGW's Backend pool IP against each APIM's "Overview" blade Gateway IP addresses (public/private VIP) for an exact match.

With multiple AGW/APIM pairs, the exact IP match in step 5 is the reliable tiebreaker — hostnames can look similar across environments.

```bash
# Run in Azure Cloud Shell (bash)

# 1) List all AGWs with their backend pool targets (FQDN/IP)
az network application-gateway list -o table
for AGW in $(az network application-gateway list --query "[].id" -o tsv); do
  echo "=== $AGW ==="
  az network application-gateway show --ids "$AGW" \
    --query "{name:name, backendPools:backendAddressPools[].{name:name, fqdns:backendAddresses[].fqdn, ips:backendAddresses[].ipAddress}}" -o json
done

# 2) Backend settings — hostname overrides per AGW
for AGW in $(az network application-gateway list --query "[].id" -o tsv); do
  az network application-gateway show --ids "$AGW" \
    --query "{name:name, httpSettings:backendHttpSettingsCollection[].{name:name, host:hostName, overrideHost:pickHostNameFromBackendAddress}}" -o json
done

# 3) Routing rules — listener -> pool -> setting mapping
for AGW in $(az network application-gateway list --query "[].id" -o tsv); do
  az network application-gateway show --ids "$AGW" \
    --query "{name:name, rules:requestRoutingRules[].{rule:name, listener:httpListener, pool:backendAddressPool, settings:backendHttpSettings}}" -o json
done

# 4) All APIM custom domains, for hostname matching against step 1/2 output
az apim list --query "[].{name:name, gatewayUrl:gatewayUrl}" -o table
for APIM in $(az apim list --query "[].name" -o tsv); do
  RG=$(az apim list --query "[?name=='$APIM'].resourceGroup" -o tsv)
  az apim show -n "$APIM" -g "$RG" --query "{name:name, hostnames:hostnameConfigurations[].hostName, ips:publicIpAddresses}" -o json
done

# 5) One-shot IP cross-match: pulls every AGW backend IP/FQDN and every APIM IP into two lists you can diff
az network application-gateway list --query "[].backendAddressPools[].backendAddresses[].{ip:ipAddress, fqdn:fqdn}" -o tsv > agw_targets.txt
az apim list --query "[].publicIpAddresses[]" -o tsv > apim_ips.txt
grep -Ff apim_ips.txt agw_targets.txt   # matching lines = confirmed wiring
```

Step 5's `grep` is the actual pinpoint — everything above it is just building the two lists to diff.

```bash
# Get AGW's backend target (FQDN/IP)
az network application-gateway address-pool list \
  --gateway-name <AGW_NAME> -g <AGW_RG> \
  --query "[].backendAddresses" -o table

# Get APIM's gateway hostname + IP
az apim show -n <APIM_NAME> -g <APIM_RG> \
  --query "{gatewayUrl:gatewayUrl, publicIp:publicIpAddresses, customDomains:hostnameConfigurations[].hostName}" -o json
```

Match confirmed if the AGW backend FQDN/IP equals the APIM `gatewayUrl` host, any `customDomains` entry, or `publicIp`.

That confirms APIM is internal-mode (VNet-injected) — no public IP to match against.

```bash
# APIM private IP + internal gateway hostname instead
az apim show -n <APIM_NAME> -g <APIM_RG> \
  --query "{privateIps:privateIpAddresses, gatewayUrl:gatewayUrl, vnetType:virtualNetworkType}" -o json

# AGW backend pool target (should be private IP or internal FQDN, not public)
az network application-gateway address-pool list \
  --gateway-name <AGW_NAME> -g <AGW_RG> \
  --query "[].backendAddresses" -o table
```

Match confirmed if AGW's backend `ipAddress`/`fqdn` equals APIM's `privateIps` entry (or resolves to it, if backend uses the internal `gatewayUrl` hostname via private DNS).


- You have a **genuine, unexplained anomaly**: AFD logs `200` + `0 bytes` + `ClientDisconnected`, while AGW (the hop right before AFD in the response path) shows full bytes sent/received for the same request.
- Nothing in public Microsoft docs explains why those three fields would combine this way on AFD Premium. I don't have a real answer for it.
- This is a **Microsoft support case**, not something diagnosable from your side or from public documentation — you need someone with backend AFD telemetry access, not more log correlation from your end.
- If you want, I can help draft that support ticket now with the exact fields to include (trackingReference, timestamp, POP, the AGW byte comparison) so it doesn't get bounced back for missing info.


Two sources:

- **Documented field behavior** (the "499 if client closed" rule): [Monitor Azure Front Door – Microsoft Learn](https://learn.microsoft.com/en-us/azure/frontdoor/monitor-front-door) — under the access log schema, `httpStatusCode` field description.
- **The informal "old vs new POP software" explanation** (not official documentation, a support engineer's anecdotal reply): [Azure Front Door 499 responses from pop_s EWR – Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/1350738/azure-front-door-499-responses-from-pop-s-ewr)

Worth being precise: the first link is authoritative documentation. The second is a 2023 forum answer, not something Microsoft stands behind as current or official — that's the one I shouldn't have leaned on as if it explained your Aug 2026 case.
