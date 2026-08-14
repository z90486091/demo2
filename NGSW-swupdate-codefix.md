# WSOD Root Cause & Fix — SW Version Staleness (4.0.0 → 5.4.174)

## Root Cause Chain (confirmed via log + code investigation)

1. Aug 5/Aug 6, 2026 incidents: ~1000 distinct US client IPs hit `error.html`, only 3 clean `index.html` requests, in a ~19-min window. Single prod deploy occurred once, Aug 3, 2026. No incidents since Aug 6.
2. `index.html` byte sizes: identical across all 3 requests (clean). `error.html` byte sizes: wildly variable (10–10,000 bytes) across the ~1000 requests — same transfer-corruption signature seen on zero-byte chunk.js files elsewhere in AFD logs.
3. AFD logs show locale JSON requests carrying **two different app version fragments**: current `5.4.174` and an older `4.0.0`. Build tooling (Nx/Webpack) cannot produce two versions from a single CI/CD run — confirmed this is stale **client-side** state (Service Worker), not a build/deploy issue.
4. Mechanism: PWA/browser clients whose Service Worker is still on `4.0.0` request locale JSON at the old version's path. Origin only serves `5.4.174` assets post-deploy → old-version requests fail (404/5xx-class failure).
5. `staticwebapp.config.json` has **no `responseOverrides`** — ruled out a server-side redirect-to-error.html mechanism.
6. Confirmed: a custom file, **`ng-safetyworker.js`**, exists in the prod codebase. This is the most likely site of the actual `error.html` redirect logic — a pre-bootstrap safety-net script (separate from Angular Router / `SwUpdate`) that detects failed critical-resource fetches (404/502/504-class failures) and navigates to `error.html` directly. This explains why `error.html` requests never appeared in Angular Router (`NavigationError`) logs, `SwUpdate` events, or App Insights — it's outside all of those systems.
7. Distinct client IPs, few with more than 1-2 requests each → rules out a single-client retry-storm; confirms broad, simultaneous, independent-session impact (~1000 real users affected).
8. Geo: US-only impact — inconclusive on AFD POP-scope, since the app's user base is US-only entirely (no comparison traffic from other geos at any time). Not meaningful evidence either way — dropped as a lead.
9. WAF, AFD compression, `immutable` cache directive, build/deploy pipeline correctness, and MS Support escalation are all ruled out / deprioritized (see "Ruled Out" section below).

---

## Corrected Understanding of `SwUpdate` (Angular's Own Docs)

**Important correction made mid-investigation:** earlier assumption that `window.location.reload()` without a preceding `activateUpdate()` call is a bug was **wrong**.

Per Angular's official docs (`SwUpdate.activateUpdate()`):
> "In most cases, you should not use this method and instead should update a client by reloading the page. Updating a client without reloading can easily result in a broken application due to a version mismatch between the application shell and other page resources, such as lazy-loaded chunks, whose filenames may change between versions."

**Confirmed:** prod code's `versionUpdates` handler doing a plain `reload()` (no `activateUpdate()`) is the **Angular-recommended pattern**, not a defect. This was retracted as a fix candidate.

**The real gap:** `reload()` only serves whichever version the SW has **already detected and downloaded**. It does not itself trigger a new check. If the SW's update-check never runs for a given session (e.g., a PWA-installed app resuming from background rather than doing a fresh navigation/stabilize cycle), `VersionReadyEvent` never fires, nothing new is ever downloaded, and reload just re-serves the same stale version indefinitely — consistent with users still being on `4.0.0` two days after the Aug 3 deploy.

**Confirmed:** prod code does already call `checkForUpdate()` in `ngOnInit()` — but the exact trigger mechanism (one-time on init vs. polling vs. tied to visibility/focus) was not fully confirmed verbatim (user was off office PC). Working assumption: existing implementation may not reliably fire for backgrounded/resumed PWA sessions, since `setInterval`-based polling is throttled/suspended by mobile OSes when the app isn't in the foreground.

---

## Ruled Out / Deprioritized

| Hypothesis | Status | Why |
|---|---|---|
| AFD compression | Ruled out | Confirmed disabled in AFD, not a factor |
| Zero-byte JS chunk caching (general) | Not the sole cause | Zero-byte chunks confirmed present in prod *without* WSOD on other occasions; only correlates with WSOD in the specific windows tied to the version-staleness mechanism |
| `immutable` Cache-Control | Ruled out | Was live once, caused a separate catastrophic incident, fully removed since |
| WAF (AFD) as cause of *sustained* WSOD | Logically eliminated | WAF evaluates per-request before cache lookup, unaffected by cache purge; purge is what resolves every incident — inconsistent with WAF as the driver of the sustained pattern. Not fully ruled out as an isolated non-sustained event, but low priority. |
| Build/deploy pipeline (`staticwebapp.config.json` bundling, Nx build output) | Ruled out | Confirmed present correctly in release artifact; not the source of this issue |
| `staticwebapp.config.json` `responseOverrides` (404→error.html) | Ruled out | Confirmed no such block exists in config |
| AFD-native rule to block caching zero-byte 200 responses | Not possible | Confirmed: AFD Rules Engine has no match condition on response body size/Content-Length — not configurable natively |
| Microsoft Support escalation | Deprioritized indefinitely | Assessed as low value by requester; dropped as an avenue |
| Geo/POP-specific AFD issue | Inconclusive, dropped | US-only impact is fully explained by US-only user base; no comparison data available |

---

## Fix Plan — 2 PRs (PR#3 speculative/parked)

### PR#1 — `staticwebapp.config.json`
Scoped change: `no-cache` → `no-store`, **only** for confirmed ngsw-related routes (`ngsw.json`, `ngsw-worker.js`, and any other confirmed SW control files) — explicitly NOT a blanket find-replace across the whole file; other routes using `no-cache` for unrelated reasons must be left untouched.

```json
{
  "route": "/ngsw.json",
  "headers": { "cache-control": "no-store" }
},
{
  "route": "/ngsw-worker.js",
  "headers": { "cache-control": "no-store" }
}
```

**Why `no-store` and not `no-cache`:** `no-cache` still permits storage, relying on every intermediary (AFD, APIM, App Gateway, browser) to correctly revalidate before use — a chain that's already shown ambiguous/inconsistent cache-status behavior in this investigation. `no-store` removes that reliance entirely: the file can never be stored anywhere, full stop.

**Scope clarification (asset-group files vs control files):** `no-store` on `index.html`/JS chunks would NOT change Angular SW's own internal caching of those files — assets listed in `ngsw-config.json`'s `assetGroups` are cached by ngsw via its own Cache Storage logic, driven by `installMode`/`updateMode` config and content hashing, independent of HTTP `Cache-Control` headers entirely. `no-store` is only meaningful/effective on the two control files (`ngsw.json`, `ngsw-worker.js`) which the SW fetches via normal HTTP semantics.

**Cache-busting note:** Angular's SW independently appends `?ngsw-cache-bust=<random>` to its own control-plane requests regardless of what Cache-Control header the origin sends — this behavior is hardcoded in `ngsw-worker.js` and is unaffected by the `no-cache`→`no-store` change. It already applies to `index.html` requests even under `no-cache` (defensive behavior, not evidence of misconfiguration).

**Branching:** branch off the confirmed `v5.4.174` release tag (not `main`'s current HEAD), since `main` has since moved forward with unrelated `1.2.x` in-progress work:
```bash
git checkout -b fix/ngsw-no-store-cache-headers v5.4.174
git push origin fix/ngsw-no-store-cache-headers
```
PR target branch: confirm with team which branch is the actual deploy source of truth before opening.

---

### PR#2 — Client-side recovery logic (additive only, no existing logic removed/changed)

```typescript
import { ErrorHandler, Injectable, Component, OnInit } from '@angular/core';
import { Router, NavigationError } from '@angular/router';
import { SwUpdate, VersionReadyEvent } from '@angular/service-worker';
import { filter } from 'rxjs/operators';

// --- Global handler: catches chunk load errors app-wide ---
@Injectable()
export class ChunkErrorHandler implements ErrorHandler {
  handleError(error: any): void {
    const chunkFailedMessage = /Loading chunk [\d]+ failed|ChunkLoadError/;
    if (chunkFailedMessage.test(error?.message ?? '')) {
      console.error('Chunk load failure detected, reloading:', error);
      window.location.reload();
      return;
    }
    console.error(error);
  }
}
// Register in app.config.ts / app.module.ts providers:
// { provide: ErrorHandler, useClass: ChunkErrorHandler }
```

```typescript
@Component({ /* ... */ })
export class AppComponent implements OnInit {
  constructor(private swUpdate: SwUpdate, private router: Router) {}

  ngOnInit(): void {
    if (!this.swUpdate.isEnabled) {
      return;
    }

    // --- Proactive: force update checks on every plausible "app active" signal ---
    // (confirm existing checkForUpdate() implementation on office PC before assuming
    //  this is net-new — prod code reportedly already has SOME form of this)
    const triggerCheck = () => {
      this.swUpdate.checkForUpdate().catch(err => console.error('SW update check failed', err));
    };
    triggerCheck(); // on init
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') triggerCheck();
    });
    window.addEventListener('focus', triggerCheck);
    setInterval(triggerCheck, 6 * 60 * 60 * 1000); // best-effort while foregrounded; tune to deploy cadence

    // --- Existing prod pattern — confirmed correct per Angular docs, unchanged ---
    this.swUpdate.versionUpdates
      .pipe(filter((evt): evt is VersionReadyEvent => evt.type === 'VERSION_READY'))
      .subscribe(() => window.location.reload());

    // --- Router-level chunk/navigation failure catch ---
    this.router.events
      .pipe(filter((e): e is NavigationError => e instanceof NavigationError))
      .subscribe(e => {
        if (/Loading chunk [\d]+ failed|ChunkLoadError/.test(e.error?.message ?? '')) {
          console.error('Router-level chunk load failure, reloading:', e);
          window.location.reload();
        }
      });

    // --- unrecoverable: the actual guarantee, catches regardless of WHY client was stale ---
    this.swUpdate.unrecoverable.subscribe(event => {
      console.error('SW unrecoverable:', event.reason);
      window.location.reload();
    });
  }
}
```

**Why this combination is the closest to "bullet proof" achievable client-side:**
- Proactive triggers (`visibilitychange`, `focus`, interval) reduce *how often* a client is stale when it makes a request — directly targets the PWA-background-throttling gap
- `versionUpdates`→reload remains as-is (already correct)
- `unrecoverable` is the deterministic floor — fires on the failure itself, regardless of root cause, converting a stuck blank page into a single self-healing reload
- Router + global `ErrorHandler` chunk catches cover both navigation-triggered and non-navigation-triggered lazy-load failures
- No user-facing popup/prompt anywhere in this flow — every path reloads silently

**Honest limitation:** no client-side fix is 100% guaranteed — browser/OS-level timer throttling and scheduling are outside app control. This is proactive-minimization + reactive-guarantee combined, not a mathematical guarantee.

**Not achievable:** an AFD-native rule to block caching of zero-byte 200 responses — confirmed no such match condition exists in AFD's Rules Engine.

---

### PR#3 — `ng-safetyworker.js` (SPECULATIVE / PARKED — not scoped yet)

Flagged as a future investigation target, not a committed PR. Before scoping:
```bash
cat ng-safetyworker.js  # or: find . -iname "ng-safetyworker*"
rg -n "error.html" ng-safetyworker.js
rg -n "404\|502\|504\|status\|catch\|fetch" ng-safetyworker.js
rg -n "1\.1\.1\|locale\|version" ng-safetyworker.js
rg -n "safetyworker" index.html src/index.html
rg -n "retry\|attempt\|maxRetries" ng-safetyworker.js
git log --oneline -- ng-safetyworker.js
git log -p -- ng-safetyworker.js | head -200
```
Goal: confirm exact trigger condition, whether it retries before redirecting (could explain error.html's variable byte sizes — different partial/retry states), whether it has any version-awareness, and whether its creation/last-edit date lines up with when this WSOD behavior started (via git log).

---

## `ngsw-config.json` Investigation (supporting ripgreps, run on office PC)

```bash
find . -name "ngsw-config.json" -exec cat {} \;
rg -n "assetGroups" -A 40 ngsw-config.json
rg -n "installMode\|updateMode" ngsw-config.json
rg -n "index.html" ngsw-config.json
rg -n "error.html" ngsw-config.json
rg -n "locale\|i18n\|\.json" ngsw-config.json
rg -n "dataGroups" -A 30 ngsw-config.json
rg -n "navigationUrls" -A 20 ngsw-config.json
```
**Key distinction to confirm:** whether locale JSON files are under `assetGroups` (app-shell-style caching, hash-driven) or `dataGroups` (Angular's mechanism for runtime data, with its own `freshness`/`performance` mode and `maxAge`/`maxSize` settings) — these behave differently and matter for understanding the exact staleness mechanism.

---

## Confirmed Answers (Q&A log from investigation)

- Locale JSON requests for stale `4.0.0` → **do** cause `error.html` to be needed (Y)
- `error.html` fallback is triggered by 404/502/504-class failures, likely via `ng-safetyworker.js`, not Angular Router/`SwUpdate` (Y)
- `activateUpdate()` is NOT required for `reload()` to pick up a new version — Angular recommends against using it in most cases (confirmed via official docs)
- `checkForUpdate()` firing is a prerequisite for `versionUpdates`'s `VERSION_READY` event to ever emit (Y)
- Combination of `no-store` (control files) + reliable `checkForUpdate` triggering + `unrecoverable` + chunk/router error handling should collectively resolve the stale-4.0.0-client problem (Y, as a combined effect — no single piece alone is sufficient)
- AFD cannot natively block caching zero-byte 200 responses via any rule (N — not supported)
- `no-cache`→`no-store` change does not affect existing ngsw cache-busting behavior, which is independent SW-internal logic (N — no effect)
