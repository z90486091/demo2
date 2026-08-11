# GH REPO — SOURCE CODE SEARCH (use repo-wide "/" search)

[ ] "@angular/service-worker" or "ngsw-config.json"
[ ] "ChunkLoadError" or "NavigationError"
[ ] "ModuleFederationPlugin" or "remotes:"
[ ] "integrity=" (index.html / build templates)
[ ] "Content-Security-Policy" (app code + staticwebapp.config.json)
[ ] "provideClientHydration" or "@angular/ssr"
[ ] "NG0500" or "hydration mismatch"
[ ] apps/webapp1/project.json → check for "server"/"prerender" build target

# GH ACTIONS — CI WORKFLOW LOGS (latest + last 5 runs)

[ ] Ctrl+F "warning"
[ ] Ctrl+F "chunk"
[ ] Ctrl+F "hydration"

# MS SUPPORT TICKET
Subject: Intermittent blank page (WSOD) - AFD Premium + APIM + SWA - 
         suspected edge caching, need internal error trace

Environment:
- AFD Premium (Microsoft.Cdn/profiles)
- Topology: AFD -> WAF -> Firewall -> App Gateway -> APIM -> SWA
- Custom domain: <domain>
- Front Door profile: <name>
- SWA resource: <name>

Symptom:
- Intermittent blank page (WSOD) on initial load, 30-60 min sustained
  if unaddressed, resolved immediately via manual cache purge
- HTTP 200 status, non-zero Content-Length, but renders blank client-side
- No reproducible trigger; only observed in prod, post-incident

Evidence gathered:
- [attach: AFD access log excerpt for outage window(s)]
- [attach: WAF log excerpt for same window(s), if pulled - ruled out]
- [attach: APIM ApiManagementGatewayLogs excerpt if ClientConnectionFailure found]
- [attach: staticwebapp.config.json cache-control config]
- Confirmed: not a build/deploy issue (ruled out via GH repo/CI review)
- Confirmed: not WAF-caused (purge resolves it; WAF evaluation is
  stateless per-request and unaffected by cache purge)

Ask:
- Internal trace/RCA for [specific trackingReference_s / CorrelationId
  values] during outage window(s)
- Confirm whether AFD Premium has any known caching edge cases
  producing intermittent stale/bad 200 responses independent of
  Cache-Control misconfiguration



# FOOTNOTE
**Big finding wrt presence of `ngsw.json` — reframes everything.** Angular's service worker adds a **third cache layer** (in-browser, per-user), separate from AFD and any server-side cache.

**Most likely tie-in to what you've already confirmed:**
- SW checks for updates by fetching `ngsw.json` on each load and comparing hashes
- If **`ngsw.json` itself** gets cached by AFD (stale), SW clients keep seeing "no update available" → serve old cached app shell/chunks forever, per-browser
- AFD purge → next `ngsw.json` fetch is fresh → SW finally detects the real update → explains why **server-side purge fixes a client-side symptom**

**Next check:** confirm `ngsw.json`'s cache-control in `staticwebapp.config.json` — if it's not explicitly `no-cache`, this is your strongest lead yet, and ties both AFD's role AND the intermittent, purge-fixable pattern together in one coherent mechanism.
  
