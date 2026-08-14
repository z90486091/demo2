# WSOD Findings — Meeting Narrative (Dev + PM)

## Framing (open with this)
Two incidents, same signature, same deploy cycle (Aug 5 + Aug 6, both after the single Aug 3 prod deploy). No repro possible — this is 100% log/artifact reconstruction. SRE cache-purge "fixes" the symptom every time but doesn't explain or prevent it — we now know why.

---

## Narrative order (slot screenshots 1-6 here)

**1. The imbalance [SS #1]**
`error.html` requests vastly outnumbered `index.html` requests in both incident windows. Something was failing *after* the app started loading, not at initial load — bootstrap wasn't the problem.

**2. The smoking gun [SS #2]**
AFD logs show requests for locale JSON files at **both** `1.1.1` and `1.2.3` paths, in both windows — despite only one prod deploy (Aug 3) ever having happened. The build cannot produce two versions from one CI/CD run. This is stale client-side state: some end-user devices are still running app version 1.1.1.

**3. Corruption pattern, not clean failures [SS #3 + #6]**
Response byte sizes for `index.html` were identical/static across all requests — clean. `error.html` byte sizes varied wildly (10–10,000 bytes) in both windows — inconsistent, not a simple clean error page being served.

**4. Ruling out the app's own error page as the cause [SS #4]**
`error.html` itself doesn't use our Webpack-built app chunks at all — only static, 3rd-party CDN-delivered libraries. So the corruption/variance seen on `error.html` isn't caused by our own JS chunk pipeline — it's happening at the transport/delivery layer, not in application code shipped by us.

**5. Ruling out the build [SS #5]**
`unzip -l` on the exact release zip deployed to prod shows **zero 0-byte chunk files** at build time — every chunk was created correctly. Overlaid against AFD logs from the incident windows, the *same* chunk filenames appear as 0 bytes in what was actually delivered. The corruption happens between deployment and delivery — not in our build.

**6. Conclusion**
- Root cause: end-user devices with a stale Service Worker (still on `1.1.1`) requesting locale JSON paths that no longer exist post-deploy, resulting in failed critical resource fetches
- A custom pre-bootstrap script (`ng-safetyworker.js`) is very likely what redirects to `error.html` on these failures — needs code confirmation, not yet 100% proven
- Byte-size corruption pattern (seen on both chunk.js and error.html) is a second, related transport-layer issue compounding the visible impact — not yet fully explained, separate from the version-staleness root cause

---

## The ask (close with this)
Two small PRs, already drafted:
- **PR#1**: `staticwebapp.config.json` — tighten cache headers on 2 SW control files (`no-cache` → `no-store`)
- **PR#2**: client-side — force reliable update-checks + add a safety-net reload if a client ever gets stuck in a broken state. Fully additive, no existing logic removed, no user-facing popup.

Not asking for a redesign — asking to close a ~19-minute, ~1000-user-impacting gap that's currently only "fixed" by someone manually noticing and purging cache.
