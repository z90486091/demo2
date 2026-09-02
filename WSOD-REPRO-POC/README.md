# WSOD Triage MVP

Net-new hub/spoke sandbox mirroring your prod chain (AFD -> WAF -> Firewall -> App Gateway -> APIM -> SWA), for reproducing/instrumenting the zero-byte-200 WSOD behavior in isolation.

## Deploy infra

```bash
az login
az account set --subscription <sub-id>
az deployment sub create \
  --location eastus2 \
  --template-file infra/main.bicep \
  --parameters prefix=wsod location=eastus2
```

Grab outputs: `afdEndpointHostname`, `swaName` (resource group is `<prefix>-rg`).

## Deploy the PWA to SWA

```bash
cd swa-app
pnpm install
pnpm run build
swa deploy ./dist/wsod-triage-pwa/browser \
  --deployment-token <token-from-portal-or-azd> \
  --env production
```

Open the SWA URL, paste the `afdEndpointHostname` output into the "AFD endpoint base URL" field, and use the two buttons to probe `/good` and `/zero` through the full hub chain. `/zero` returning empty is expected (control case); `/good` returning `200` with `0` actual body bytes is the signature you're hunting.

## Key assumptions (flag any that don't hold)

- APIM Consumption tier -> no VNet injection; Firewall/AppGW sit only in front of AppGW, not APIM itself. Egress to `*.azure-api.net` is allowlisted on the firewall app-rule.
- TLS terminates at AFD; everything AFD-to-APIM runs HTTP/plain internally for MVP simplicity (no cert/Key Vault wiring). Swap to end-to-end TLS before treating results as fully prod-representative.
- No APIM auth (open), per your answer — add subscription-key validation later if you want auth-layer effects in scope.
- AFD caching is OFF by default on the route (no `cacheConfiguration` block) so cache behavior is opt-in during repro, not implicit.
- `swa deploy` deployment token / `azd` wiring is left to you — module has `skipGithubActionWorkflowGeneration: true` so no GH Action gets auto-created.
