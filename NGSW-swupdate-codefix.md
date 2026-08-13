# WSOD Root Cause & Fix — SW Version Staleness (1.1.1 → 1.2.3)

## Root Cause Summary

- Aug 5/Aug 6, 2026 incidents: ~1000 distinct users hit `error.html`, only 3 clean `index.html` requests, during a single prod deploy cycle (last deploy Aug 3)
- AFD logs showed locale JSON requests carrying an old app version fragment (`1.1.1`) alongside the current version (`1.2.3`) — confirmed the build cannot generate two versions from one CI/CD run, so this is stale client-side (Service Worker) state, not a build issue
- Mechanism: browsers with a Service Worker still on `1.1.1` request locale JSON at the old version's path → 404s at origin (old version's assets no longer served post-deploy) → app fails to render required resource → falls back to `error.html`
- No AFD/WAF/APIM-side corruption found in this specific chain — this is a client-side SW update-timing gap, not an infra caching bug
- Not reproducible on demand; investigation is post-mortem only, US-only user base, no live repro available

---

## Step 1 — Code Investigation (run on office PC, read-only)

```bash
# 1. Find the versionUpdates subscription itself
rg -n "versionUpdates" src/ apps/

# 2. See what happens inside that subscription (context around it)
rg -n -A 15 "versionUpdates" src/ apps/

# 3. Check if activateUpdate is called anywhere
rg -n "activateUpdate" src/ apps/

# 4. Check if a reload/location.reload happens anywhere near SW logic
rg -n "location.reload" src/ apps/

# 5. Check if it's just a console.log/notification (no action)
rg -n -B 2 -A 10 "VersionReadyEvent" src/ apps/

# 6. Check SW registration timing/strategy (affects how often it even checks)
rg -n "registerWhenStable|registrationStrategy" src/ apps/

# 7. Confirm unrecoverable is truly absent
rg -n "unrecoverable" src/ apps/

# 8. Confirm no existing checkForUpdate polling
rg -n "checkForUpdate" src/ apps/
```

**Expected finding (per prior discussion, unconfirmed until checked):** `versionUpdates` already filters for `VERSION_READY` and calls `activateUpdate()` + `window.location.reload()`. If confirmed, Step 2 below only needs the *additions*, not a rewrite of existing logic.

---

## Step 2 — Fix: What "Good" Looks Like

### 2a. Explicit update polling (closes most of the staleness window)
```typescript
import { Component, OnInit } from '@angular/core';
import { SwUpdate, VersionReadyEvent } from '@angular/service-worker';
import { filter } from 'rxjs/operators';

@Component({ /* ... */ })
export class AppComponent implements OnInit {
  constructor(private swUpdate: SwUpdate) {}

  ngOnInit(): void {
    if (!this.swUpdate.isEnabled) {
      return;
    }

    // Explicit polling — don't rely solely on default lazy check timing
    setInterval(() => {
      this.swUpdate.checkForUpdate().catch(err => {
        console.error('SW update check failed', err);
      });
    }, 6 * 60 * 60 * 1000); // every 6 hours — tune to actual deploy cadence

    // Primary: reload on ready (confirm this already exists per Step 1)
    this.swUpdate.versionUpdates
      .pipe(filter((evt): evt is VersionReadyEvent => evt.type === 'VERSION_READY'))
      .subscribe(() => {
        this.swUpdate.activateUpdate().then(() => {
          window.location.reload();
        });
      });
  }
}
```

### 2b. `unrecoverable` handler (catches the residual gap — request fired before update-check completes)
```typescript
this.swUpdate.unrecoverable.subscribe(event => {
  console.error('SW unrecoverable state:', event.reason);
  window.location.reload();
});
```

### 2c. Skipped — do not implement
`updateViaCache: 'none'` via manual `navigator.serviceWorker.register()` — requires bypassing Angular's built-in `provideServiceWorker`/`ServiceWorkerModule.register()`, risks double-registration/lifecycle conflicts. Marginal benefit not worth the risk given the "don't touch Angular's SW lifecycle" constraint.

Nuclear-option manual `unregister()` + reload (fallback #3 from earlier discussion) also skipped — `unrecoverable` (2b) already covers this case natively, no need for a hand-rolled equivalent.

---

## Why This Fixes It (not just papers over it)

- **2a** shrinks the time window during which any client can still be on `1.1.1` — closes the vast majority of cases
- **2b** catches the residual few who fire a stale-version request in the brief gap before their update-check completes — converts a failed request into a single self-healing reload instead of a stuck blank page
- Net effect: turns a ~1000-request retry storm into, at most, isolated single-reload blips per affected user — directly addresses the confirmed mechanism, not a AFD-side symptom

---

## Open Item

Confirm via Step 1 grep results whether `versionUpdates` reload logic already exists as expected. If it does, only **2a's polling addition** and **2b (`unrecoverable`)** are net-new code — a small, additive, low-risk change, not a rewrite of existing SW logic.


🧨 DO THIS ONLY IF ALL/ANY OF THE ABOVE FAIL

```typescript
// --- #2: Service worker registration, in main.ts or app config ---
// (Angular's provideServiceWorker doesn't expose updateViaCache directly —
//  this requires manual registration if you need it)
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/ngsw-worker.js', {
    updateViaCache: 'none' // browser must always re-fetch ngsw-worker.js itself, never from HTTP cache
  });
}
```

#2 conflicts with Angular's standard provideServiceWorker/ServiceWorkerModule.register() setup — if using Angular's built-in registration, you'd need to bypass it or check if a newer Angular version exposes this option before hand-rolling navigator.serviceWorker.register() directly.
