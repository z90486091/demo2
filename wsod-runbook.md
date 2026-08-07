# AFD + SWA White Screen of Death (WSOD) — Troubleshooting Runbook

**Stack:** Azure Front Door (caching enabled, custom domain) → Azure Static Web App (Angular + Yarn build)

---

## 1. Symptom Summary

- Intermittent blank/white screen on home page, only through AFD custom domain
- Confirmed causes found so far, in order of investigation:
  1. `staticwebapp.config.json` bundling into build output — **unconfirmed, assume NOT bundled**
  2. AFD serving stale `index.html` referencing old hashed JS/CSS chunks
  3. **Confirmed:** `TCP_HIT` + `200` + `Content-Length: 0` on JS chunk files (cached empty/broken response)
  4. **Confirmed:** Cache purge resolves it immediately, but is not a permanent fix
  5. **Unresolved:** Intermittent `504` with an errorInfo value team couldn't recall exactly — most likely `OriginTimeout` based on documented Microsoft `errorInfo` enum (not `UnexpectedClientResponse`, which does not exist in official docs)

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

**What we know:**
- Team recalls an `errorInfo` value alongside `504` but couldn't confirm exact text
- `"UnexpectedClientResponse"` was searched and **does not exist** in Microsoft's documented `errorInfo` enum

**Official documented `errorInfo` values relevant to 504/5xx:**
`OriginTimeout`, `OriginConnectionAborted`, `OriginConnectionError`, `OriginConnectionRefused`, `OriginError`, `OriginInvalidResponse`, `ClientDisconnected`, `UnspecifiedClientError`, `ResponseHeaderTooBig`

**When back in the portal, run this first:**
```kusto
AzureDiagnostics
| where httpStatusCode_s == "504"
| summarize count() by errorInfo_s
| order by count_ desc
```

**If it comes back `OriginTimeout` (most likely candidate):**
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

**If the errorInfo value is genuinely unrecognized:**
- [ ] Pull `trackingReference_s` for affected requests and open a Microsoft support case — support has access to internal errorInfo definitions not published in docs

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

## 9. Open Items / Next Session

- [ ] Confirm `staticwebapp.config.json` bundling status once portal access is back
- [ ] Run the `errorInfo` breakdown KQL query to confirm actual 504 cause
- [ ] Confirm whether disabling AFD compression alone resolves zero-byte chunks (24–48h observation window)
- [ ] Check origin forward protocol (HTTP vs HTTPS) if `OriginTimeout` confirmed
- [ ] If errorInfo value remains unidentified after log check, escalate to Microsoft support with `trackingReference_s`
