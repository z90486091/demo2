**Confirmed — private repo, so:**

**Fine-grained PAT:** Repository access → this repo only → Permissions → `Actions: Read and write` + `Contents: Read-only` (unchanged, fine-grained scoping already handles private repos correctly).

**Classic PAT:** must use full `repo` scope (not `public_repo`) + `workflow` scope — `public_repo` alone won't work on a private repo regardless of `workflow` being set.

**TL;DR:** Private repo → Classic PAT needs `repo` + `workflow` (not `public_repo`); fine-grained stays `Actions: Read+write` + `Contents: Read-only`.

```diff
  const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
      viewport: { width: 1920, height: 1080 },
      deviceScaleFactor: 1,
      locale: 'en-US',
      timezoneId: 'America/New_York',
+     geolocation: { latitude: 40.7128, longitude: -74.0060 },
+     permissions: ['geolocation'],
      recordHar: {
          path: harPath,
          content: 'embed' 
      }
  });
```

Notes:
- `permissions: ['geolocation']` is required — without it, the page's `navigator.geolocation` calls will be denied even though coordinates are set.
- Coordinates above are New York; swap to whatever region you want the check to appear to originate from (matches your existing `timezoneId: 'America/New_York'`, so keep them consistent — a geolocation/timezone mismatch is itself a bot-detection signal, which matters given you're already using the stealth plugin).
- If your PWA doesn't use `navigator.geolocation` at all, this has no effect on the WSOD check — only relevant if the app's rendering/routing depends on detected location.

**Use KQL's built-in `geo_info_from_ip_address()` plugin in Log Analytics — it converts logged client IPs directly into lat/long, no external geo-IP service needed.**

```kql
AzureDiagnostics
| where Category == "FrontDoorAccessLog"
| where TimeGenerated > ago(7d)
| extend GeoInfo = geo_info_from_ip_address(clientIp_s)
| extend Country = tostring(GeoInfo.country), Lat = todouble(GeoInfo.latitude), Long = todouble(GeoInfo.longitude)
| summarize RequestCount = count() by clientIp_s, Country, Lat, Long
| order by RequestCount desc
```

**To get a clean distinct list for feeding into your Playwright script:**

```kql
AzureDiagnostics
| where Category == "FrontDoorAccessLog"
| where TimeGenerated > ago(7d)
| extend GeoInfo = geo_info_from_ip_address(clientIp_s)
| extend Country = tostring(GeoInfo.country), Lat = todouble(GeoInfo.latitude), Long = todouble(GeoInfo.longitude)
| where isnotempty(Country)
| summarize RequestCount = count() by Country, Lat, Long
| order by RequestCount desc
```

Export as CSV (Log Analytics query results → **Export** → CSV) and map `Lat`/`Long` into your `geolocation: { latitude, longitude }` array in the Playwright script.

**Given your Reader-only access constraint:** running Log Analytics queries needs `Log Analytics Reader` (or `Reader` at the workspace scope, which typically includes query access) — this is a narrower, read-only permission distinct from Key Vault write access, so it's worth checking if you already have it before assuming you need to ask anyone. If the AFD diagnostic logs route to a Log Analytics workspace you can already query (Portal → Log Analytics workspace → **Logs**), this needs zero additional grants.

**TL;DR:**
- `geo_info_from_ip_address(clientIp_s)` in KQL against `AzureDiagnostics` (`Category == "FrontDoorAccessLog"`) gives country + lat/long directly
- Group/dedupe by country, export CSV, feed lat/long into Playwright's `geolocation` option
- Reader role often includes Log Analytics query access already — check before assuming you need another permission grant
