# AFD + SWA White Screen of Death (WSOD) — Troubleshooting Runbook

**Stack:** Azure Front Door (caching enabled, custom domain) → APIM → Azure Static Web App (Angular + Yarn build, hash-based routing) → Storage Account

**Auth flow:** End user clicks emailed link (`https://FQDN/#/A/?B=C`) → default browser opens → 302 redirect to self-hosted Authy (Azure Function App) for auth check → on success, 302 redirect back to original page/landing. WSOD has been observed both before and after the Authy redirect.

---

## 1. Symptom Summary

- Intermittent blank/white screen on home page, only through AFD custom domain
- Confirmed causes found so far, in order of investigation:
  1. `staticwebapp.config.json` bundling into build output — **unconfirmed, assume NOT bundled**
  2. AFD serving stale `index.html` referencing old hashed JS/CSS chunks
  3. **Confirmed:** `TCP_HIT` + `200` + `Content-Length: 0` on JS chunk files (cached empty/broken response)
  4. **Confirmed:** Cache purge resolves it immediately, but is not a permanent fix
  5. **Unresolved:** Intermittent `504` with an errorInfo value team couldn't recall exactly — most likely `OriginTimeout` based on documented Microsoft `errorInfo` enum (not `UnexpectedClientResponse`, which does not exist in official docs)
  6. **New topology detail:** Actual path is AFD → APIM → SWA → Storage Account — APIM was not previously accounted for as a possible independent caching/failure layer
  7. **New flow detail:** Entry point is a hash-routed deep link (`#/A/?B=C`) that passes through a 302 auth-check redirect (self-hosted Authy Function App) before landing — WSOD occurs both before and after this redirect, suggesting two possible distinct mechanisms

**Known evidence gap:** AFD access logs cannot prove that a zero-byte chunk *caused* a given WSOD occurrence — they only show what happened at the edge, not what the browser did with it. The correlation is circumstantial (timestamp proximity to purges) until client-side error telemetry is added. See §11.

---

## 2. Step 0 — Confirm `staticwebapp.config.json` Is Actually Bundled

Before anything else, verify the config file made it into the deployed output.

- [ ] Check GH Action logs for the **Oryx build** step — look for the line `Found staticwebapp.config.json`
- [ ] If using Angular 17+, confirm `output_location` matches the real build path — new application builder outputs to `dist/<app>/browser/`, not `dist/<app>/`
- [ ] If Oryx auto-copy isn't firing (custom/skip-build workflow), force it via `angular.json`:
  ```json
  "assets": [
    "src/favicon.ico",
    "src/assets",
    { "glob": "staticwebapp.config.json", "input": ".", "output": "." }
  ]
  ```
- [ ] Confirm presence directly in the storage account blob container after a fresh deploy

---

## 3. Step 1 — Isolate AFD vs. Origin (SWA)

```bash
# Bypass AFD entirely
curl -I https://<your-app>.azurestaticapps.net/
curl -I https://<your-app>.azurestaticapps.net/main.<hash>.js
```

- If WSOD **never** happens hitting SWA directly but **does** happen via AFD → confirms AFD/caching layer, not build/config.

---

## 4. Step 2 — Browser-Side Repro

When WSOD is caught live:

- [ ] DevTools → Network tab → hard refresh (Cmd/Ctrl+Shift+R)
- [ ] Look for `404` on `.js`/`.css` chunks → stale `index.html` referencing old hashed filenames
- [ ] Look for `200` on `index.html` with empty/wrong body → stale cached HTML
- [ ] Check response headers on `index.html`: `X-Cache: TCP_HIT`, nonzero `Age` header → confirms edge cache serve, not origin
- [ ] Check Console tab:
  - `Uncaught SyntaxError` / `Unexpected token '<'` → JS file 404'd, server returned HTML error page parsed as JS
  - `NG0908` / zone.js errors → Angular bootstrap failure (different root cause, not caching)

---

## 5. Step 3 — Zero-Byte Chunk Bug (CONFIRMED ISSUE)

**Symptom:** `TCP_HIT`, `200` status, but `Content-Length: 0` on JS chunk files.

**Root cause candidates (ranked):**
1. Compression race condition — AFD compresses on the fly, origin response slow/interrupted, partial/empty compressed result gets cached
2. Cache stampede — concurrent requests hit a cache entry still mid-write
3. Origin timeout cached as a `200` instead of an error

**Verification loop:**
```bash
for i in {1..20}; do
  curl -s -o /dev/null -w "%{http_code} %{size_download}\n" https://<domain>/main.<hash>.js
done
```
All 20 should return identical non-zero `size_download`.

**Fixes, in order of leverage:**
- [ ] **Disable AFD compression** (Portal → Endpoint → Route → Compression) — let SWA serve pre-negotiated `Content-Encoding`; primary suspected fix
- [ ] Increase origin response timeout (Portal → Origin group → Health probes / Load balancing) if compression fix alone doesn't resolve it
- [ ] Add a Rules Engine rule to bypass cache on `Content-Length: 0` responses so broken responses never get written to cache:
  ```
  Condition: Response header "Content-Length" Equals "0"
  Action: Cache expiration → Bypass cache
  ```
- [ ] Add a scheduled health-check workflow (safety net, not a fix) that curls known chunk URLs and auto-purges on zero-byte detection

**Important:** cache purge resolves symptoms immediately but is **not** a permanent fix — treat repeated reliance on purge as a signal the above root causes haven't been addressed yet.

---

## 6. Step 4 — Intermittent 504s

**UPDATED FINDING — likely source identified: APIM, not AFD.**

The recalled error text ("UnexpectedClientResponse"/"ClientUnexpected") does not match any AFD `errorInfo` value, but closely matches a **documented APIM error**:

> `"reason": "ClientConnectionFailure"` — message: *"Client connection was unexpectedly closed."*

Given the confirmed topology is **AFD → APIM → SWA → Storage Account**, this is now the leading candidate over `OriginTimeout`.

**What it means in this topology:**
- In APIM's log, "client" = whoever called APIM — i.e. **AFD**, not the end user's browser
- APIM reads response status/headers from the backend first, then streams the body; if that stream gets interrupted or times out, APIM logs `ClientConnectionFailure`
- Root pattern: AFD gives up waiting on APIM's response (because APIM itself is still waiting on SWA, or on Authy further down the chain) and closes the connection before APIM can respond — APIM then logs the abandonment
- Known real-world cause: short-lived/cold-starting backends (e.g. Azure Functions) causing the upstream caller to time out first — directly relevant if Authy is anywhere in the affected call chain (see §10b)

**When back in the portal, check APIM first (not AFD):**
```kusto
// APIM diagnostic logs — requires Diagnostic Settings sending to Log Analytics
ApiManagementGatewayLogs
| where ResponseCode == 504 or Reason == "ClientConnectionFailure"
| project TimeGenerated, CorrelationId, ApiId, OperationId, Reason, ErrorSource, BackendResponseCode, TotalTime
| order by TimeGenerated desc
```
- [ ] Check the `ErrorSource`/`section` fields — identifies which policy or which leg (`inbound`/`outbound`) the failure occurred in
- [ ] Cross-reference `CorrelationId` against AFD access logs and Authy Function App logs for the same request

**Still run the AFD-side query too, to see if AFD independently logged anything:**
```kusto
AzureDiagnostics
| where httpStatusCode_s == "504"
| summarize count() by errorInfo_s
| order by count_ desc
```

**Official documented AFD `errorInfo` values relevant to 504/5xx** (kept for reference, now considered less likely given the topology):
`OriginTimeout`, `OriginConnectionAborted`, `OriginConnectionError`, `OriginConnectionRefused`, `OriginError`, `OriginInvalidResponse`, `ClientDisconnected`, `UnspecifiedClientError`, `ResponseHeaderTooBig`

**If AFD-side query does come back `OriginTimeout`:**
- [ ] Check origin forward protocol — HTTPS vs HTTP. One documented case resolved persistent `OriginTimeout` 504s by switching AFD-to-origin forwarding from HTTPS to HTTP, since SSL handshake time isn't counted within AFD's configurable origin timeout
- [ ] Check backend KeepAlive timeout — AFD holds connections open up to 90s; if origin's idle/KeepAlive timeout is shorter, AFD can attempt to reuse a closed connection → random, low-volume 504s
- [ ] Note `timeTaken_s` on the failing rows: a fast fail (~6–10s) suggests health-probe-driven unhealthy-marking rather than a genuine slow origin; ~30s suggests a real timeout

**Correlation query** (check if 504s and zero-byte chunk events are the same underlying incidents):
```kusto
AzureDiagnostics
| where errorInfo_s == "OriginTimeout" or responseBytes_s == "0"
| project TimeGenerated, requestUri_s, errorInfo_s, responseBytes_s, cacheStatus_s
| order by TimeGenerated desc
```

**If neither APIM's `ClientConnectionFailure` nor AFD's `errorInfo` explains it:**
- [ ] Pull `trackingReference_s` (AFD) / `CorrelationId` (APIM) for affected requests and open a Microsoft support case

---

## 7. Config Reference — `staticwebapp.config.json` cache headers

```json
{
  "routes": [
    { "route": "/index.html", "headers": { "cache-control": "no-cache, no-store, must-revalidate" } },
    { "route": "/assets/*", "headers": { "cache-control": "public, max-age=31536000, immutable" } }
  ],
  "navigationFallback": { "rewrite": "/index.html" },
  "globalHeaders": { "cache-control": "no-cache" }
}
```

## 8. CI/CD — Purge on Deploy

```yaml
- name: Purge Front Door cache
  uses: azure/CLI@v1
  with:
    inlineScript: |
      az afd endpoint purge --resource-group <rg> \
        --profile-name <afd-profile> --endpoint-name <endpoint> \
        --content-paths "/*"
```

---

## 10. Auth Redirect Flow Hypotheses (AFD → APIM → SWA → SA, hash routing + Authy 302)

Two WSOD occurrence points were reported — **before** the Authy redirect and **after** it. Treat these as potentially separate mechanisms, not one bug.

### 10a. Before the Authy redirect (initial GET to FQDN)
Most likely the **same** zero-byte chunk / stale cache mechanism from §5 — this is just a normal first page load hitting AFD.
- [ ] No new investigation needed here beyond §5/§6 — confirm via timestamp correlation whether "before-redirect" reports line up with known zero-byte chunk events

### 10b. After the Authy redirect (return trip)
New hypotheses specific to the auth round-trip:

- [ ] **Hash fragment loss.** The URL fragment (`#/A/?B=C`) is never sent to any server — browsers do not transmit fragments in HTTP requests. AFD, APIM, SWA, and Authy never see it. If Authy's return redirect constructs a fresh URL rather than relying on browser fragment-preservation behavior (which is inconsistent across cross-origin redirect chains), the original deep link route/params can be silently dropped on return. If the app's default/root route doesn't handle a missing route+params gracefully (e.g. throws on undefined `B`), that's an app-level blank screen with a **different root cause than caching**.
  - Confirm: does Authy encode the original path as a `state`/`returnUrl` query param (survives redirects, safe) or rely on the fragment surviving (fragile, browser-dependent)?
- [ ] **APIM as an additional cache/failure layer.** APIM sits between AFD and SWA and was not previously investigated. If APIM has its own caching policy enabled, it stacks a second independent cache layer on top of AFD's — doubling the surface area for stale/truncated responses, and potentially explaining WSOD occurrences that don't correlate with AFD's own cache/purge timeline.
  - [ ] Check APIM for a `<cache-lookup>` / `<cache-store>` policy on the relevant operation(s)
  - [ ] If present, test disabling it in isolation to see if WSOD frequency changes
- [ ] **Authy cold start.** Self-hosted Authy on Azure Functions — if on a Consumption plan, cold starts can add multi-second latency to the 302 chain. This may be the actual source of the intermittent `504`/`OriginTimeout` from §6, misattributed to the SWA static-content path rather than the auth hop.
  - [ ] Check Authy Function App's hosting plan (Consumption vs Premium/Dedicated)
  - [ ] Check Application Insights (if enabled on the Function App) for cold start duration on affected timestamps
  - [ ] Cross-reference 504 timestamps (§6) against Authy invocation timestamps, not just AFD→SWA timestamps

---

## 11. Closing the Causation Evidence Gap

AFD logs alone cannot confirm a zero-byte chunk caused a specific WSOD report — no visibility into what the browser did with the response.

- [ ] **Chunk-type matters:** if a 0-byte response is confirmed on `main.<hash>.js`, `polyfills.<hash>.js`, `vendor.<hash>.js`, or `runtime.<hash>.js` — these load unconditionally on every page, so 0 bytes there is a near-certain WSOD cause. A 0-byte lazy-loaded route chunk only breaks that route, not necessarily the home page.
- [ ] **Best available passive correlation** (no repro needed):
  ```kusto
  AzureDiagnostics
  | where requestUri_s has_any ("main.", "polyfills.", "vendor.", "runtime.")
  | where responseBytes_s == "0"
  | project TimeGenerated, requestUri_s, clientIp_s, cacheStatus_s, errorInfo_s
  | order by TimeGenerated desc
  ```
  Compare timestamps against known purge times/user reports — clustering is circumstantial but the best available evidence from this data source.
- [ ] **Long-term fix for the visibility gap:** add client-side error telemetry (Application Insights JS SDK, Sentry, or a minimal `window.onerror` beacon) so the next occurrence produces a real browser-side error/timestamp that can be joined against AFD/APIM logs — turning "we think it's related" into a confirmed link.

---

## 12. Open Items / Next Session

- [ ] **Priority:** check APIM diagnostic logs for `reason == "ClientConnectionFailure"` around known 504/WSOD timestamps — likely source of the recalled error, given the AFD → APIM → SWA topology
- [ ] Confirm `staticwebapp.config.json` bundling status once portal access is back
- [ ] Run the AFD `errorInfo` breakdown KQL query as a secondary check
- [ ] Confirm whether disabling AFD compression alone resolves zero-byte chunks (24–48h observation window)
- [ ] Check origin forward protocol (HTTP vs HTTPS) if `OriginTimeout` confirmed
- [ ] If errorInfo value remains unidentified after log check, escalate to Microsoft support with `trackingReference_s`
- [ ] Confirm whether Authy's return redirect preserves the original route via `state`/`returnUrl` param vs. relying on fragment survival
- [ ] Check APIM for an active caching policy on the relevant operations
- [ ] Check Authy Function App hosting plan and cold-start duration around known 504/WSOD timestamps
- [ ] Run the initial-load-chunk zero-byte query (§11) and compare against purge timestamps
