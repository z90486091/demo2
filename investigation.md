# WSOD Investigation — Code + KQL, Tied Together

Each phase: run the grep/git check first, then the matching KQL query to test that finding against real outage data.

---

## Phase 1 — SW Registration Strategy

```bash
grep -rn "registerWhenStable\|ServiceWorkerModule\|provideServiceWorker\|registrationStrategy" src/ apps/
```
**Look for:** `registerWhenStable:30000` (safe default) vs `registerImmediately` (races with bootstrap) vs nothing found (defaults apply).

**Tie-in KQL — does registration timing show up as request bursts right after page load?**
```kql
AzureDiagnostics
| where Category == "FrontDoorAccessLog"
| where requestUri_s has "ngsw.json"
| where TimeGenerated between (datetime(2026-08-XXT00:00:00Z) .. datetime(2026-08-XXT01:00:00Z))
| project TimeGenerated, requestUri_s, cacheStatus_s, httpStatusCode_s, clientIP_s
| order by TimeGenerated asc
```
If `ngsw.json` requests cluster in tight bursts, matches immediate/eager registration; spread out over time matches `registerWhenStable`.

---

## Phase 2 — `ngsw-config.json` Asset Groups

```bash
find . -name "ngsw-config.json" -exec cat {} \;
```
**Look for:** `installMode`/`updateMode` per asset group (`prefetch` = fails whole group if 1 file 404s; `lazy` = fetched on demand). Note whether `error.html`/`index.html` fall under a wildcard glob.

**Tie-in KQL — root cache status, settles whether AFD even caches this route at all:**
```kql
AzureDiagnostics
| where Category == "FrontDoorAccessLog"
| where requestUri_s endswith "/" or requestUri_s has_any ("index.html", "error.html")
| summarize count() by cacheStatus_s, requestUri_s
| order by count_ desc
```
**Critical:** if this returns `CONFIG_NOCACHE`, AFD isn't caching this route **at all**, regardless of `staticwebapp.config.json`'s `max-age` setting — the whole stale-cache theory would need to be dropped for this specific route.

---

## Phase 3 — `error.html` Wildcard Match

```bash
grep -rn "error.html\|\*\.html\|/\*\*" ngsw-config.json 2>/dev/null
```
**Look for:** does `error.html` match a glob pattern unintentionally, making SW treat it as a cacheable app asset?

**Tie-in KQL — correlate `ngsw-cache-bust` param specifically on `error.html`:**
```kql
AzureDiagnostics
| where Category == "FrontDoorAccessLog"
| where requestUri_s has "error.html" and requestUri_s has "ngsw-cache-bust"
| project TimeGenerated, requestUri_s, cacheStatus_s, httpStatusCode_s, responseBytes_s
| order by TimeGenerated desc
```
Confirms frequency/pattern of SW hitting its own error fallback — a proxy signal for how often the SW itself detects failure, independent of any user-visible report.

---

## Phase 4 — Custom Worker Files Exist?

```bash
find . -iname "*worker.min*" -o -iname "ng-worker*" -o -iname "ng-safetyworker*" -o -iname "ng-serviceworker*"
```
**Look for:** any of these = NOT stock `@angular/service-worker` — custom/forked code, doesn't get Angular's own fixes.

**Tie-in KQL — none directly; proceed to Phase 6 for the deploy-date correlation this finding needs.**

---

## Phase 5 — `init()` Diff Against Stock Angular SW

```bash
diff $(find . -iname "*worker.min*" -not -path "*/node_modules/*" | head -1) \
     node_modules/@angular/service-worker/ngsw-worker.js 2>/dev/null
```
**Look for:** exact lines changed from stock. This is the AI-agent-suggested "strip-replace" — read every changed line yourself before trusting any dev explanation of it.

**No KQL for this phase** — pure code review. Note down the commit hash touching this file for Phase 6.

---

## Phase 6 — Git History on Worker File Changes (THE KEY CORRELATION STEP)

```bash
git log --oneline --all -- '**/*worker*'
git show <suspicious-commit-hash>
```
**Look for:** commit date, author, whether it's on the branch/tag currently deployed to prod (cross-check against your CD tag).

**Tie-in KQL — the single most valuable query: does the commit date/deploy date align with when WSOD incidents started or changed pattern?**
```kql
AzureDiagnostics
| where Category == "FrontDoorAccessLog"
| where requestUri_s has_any ("ngsw", "error.html", "index.html")
| where TimeGenerated > ago(90d)
| summarize IncidentSignals = count() by bin(TimeGenerated, 1d), cacheStatus_s
| order by TimeGenerated asc
```
Plot/scan this against the worker.min commit date. A visible shift in pattern starting near that commit date is strong circumstantial evidence tying the code change to the WSOD onset/frequency.

---

## Phase 7 — SW Update Lifecycle Listeners (Instrumentation Gap Check)

```bash
grep -rn "SwUpdate\|checkForUpdate\|activateUpdate\|unrecoverable\|versionUpdates\|versionReady" src/
```
**Look for:** nothing found = SW update failures are completely silent by design — this is likely why no console errors have ever been captured for any incident.

**No KQL possible for this phase** — this is exactly the gap Log Analytics/AFD can't fill, since it's client-side JS execution, not an HTTP transaction. This finding is itself the argument for adding client-side telemetry, independent of anything else in this investigation.

---

## Phase 8 — Confirm SW Wired Into This App's Build

```bash
grep -rn "swRegistrationOptions\|ngsw-worker" angular.json project.json apps/*/project.json 2>/dev/null
```
Confirms SW is actually active in the deployed build, not just an unused dependency.

---

## Phase 9 — APIM Cross-Check (separate mechanism, run regardless of SW findings)

```kql
ApiManagementGatewayLogs
| where TimeGenerated between (datetime(2026-08-XXT00:00:00Z) .. datetime(2026-08-XXT01:00:00Z))
| where Reason == "ClientConnectionFailure" or ResponseCode == 504
| project TimeGenerated, CorrelationId, Reason, ResponseCode, BackendResponseCode, TotalTime
```

---

## Decision Table

| Finding | Means | Next |
|---|---|---|
| Phase 2 shows `CONFIG_NOCACHE` on `/` | AFD never caches this route | Drop the stale-`index.html`-cache theory entirely |
| Phase 4 finds custom worker files | Non-stock SW, higher risk surface | Phase 6 is now mandatory |
| Phase 5 diff shows real divergence | AI-suggested change is live in code | Read line-by-line before any dev conversation |
| Phase 3 confirms `error.html` in a glob | Explains the `ngsw-cache-bust` on error.html finding | Not a bug by itself, but confirms SW treats it as an asset |
| Phase 6 commit date lines up with Phase 6 KQL pattern shift | Circumstantial but real evidence | Strongest single artifact for the dev conversation |
| Phase 6 commit not on prod-deployed tag | The "fix" was never deployed | SW-code theory is moot — redirect investigation |
| Phase 7 finds nothing | Zero visibility into SW failures | Primary ask for dev: add `SwUpdate` logging |

---

## Dev Conversation — Questions (ask after running all phases above)

1. What `registrationStrategy` is set for the SW, and why that choice?
2. What bug did the `worker.min` `init()` change fix — was it tested against a forced SW-update scenario before merge?
3. Is `error.html` intentionally in the SW's asset manifest, or picked up unintentionally via a wildcard?
4. AFD cache purge "fixes" WSOD — if SW has its own separate browser-side cache, what's the actual causal link? Has anyone traced this?
5. Has the SW install→waiting→activate lifecycle been tested under a slow/flaky network?
6. Open to instrumenting `SwUpdate.unrecoverable`/`versionUpdates` with logging, so the next incident produces evidence instead of a guess?

**Opening frame:** *"Purge is masking something in the SW lifecycle we don't understand yet — if we don't find it, it'll eventually happen somewhere purge can't reach."*


## Addendum
### RCA.PRD

# PRD: WSOD Root Cause Investigation (Codebase Analysis)

## Objective
Investigate the codebase for `webapp1` (Angular 19, Nx monorepo) to identify the root cause of an intermittent, unreproducible "White Screen of Death" (WSOD) — a blank page rendered from an HTTP 200 response with non-zero byte content. This is a **read-only investigation task**. No code, config, or deployment changes are to be made under any circumstances.

## Background

**Symptom:** Users occasionally hit a completely blank page. Confirmed:
- HTTP status is 200, response body is non-zero bytes (not a network/transport failure)
- Not reproducible on demand — only observed in production, post-incident
- When it occurs, it's sustained for 30–60 minutes if untouched; an SRE runbook purges Azure Front Door's edge cache immediately, which resolves it within minutes
- No browser console error captures exist from any past incident

**Architecture (context, not in scope to modify):**
```
Hub: AFD (Premium) -> WAF -> Firewall -> App Gateway -> APIM
Spoke: -> Azure Static Web App (SWA)
```
Build: Nx monorepo, custom `./scripts/build.sh` wrapping `nx build webapp1`, Angular 19, Webpack (not esbuild — reverted, suspected due to Nx Module Federation dependency). Deploy: GH Actions CI packages a zip; deploy mechanism to SWA's storage layer not yet fully traced.

**Already ruled out (do not re-investigate these):**
- Build/deploy pipeline correctness — `staticwebapp.config.json` confirmed present in the release artifact; build output is not missing files
- AFD compression — confirmed disabled, not a factor
- Zero-byte JS chunk responses — confirmed present in production currently *without* any WSOD correlation; not the cause
- WAF as a direct cause of the *sustained* WSOD pattern — logically eliminated: WAF evaluates per-request before cache lookup and is unaffected by cache purges, but purging cache is what resolves every incident. This is inconsistent with WAF being the cause of the sustained/purge-fixable behavior. (WAF blocking a sub-resource as an isolated, non-sustained event is not fully ruled out, but is low priority.)
- `immutable` Cache-Control directive — was present at one point, caused a separate catastrophic incident, has since been fully removed from `staticwebapp.config.json`

**Active leads (in scope):**
1. **Angular Service Worker (`ngsw`) lifecycle.** Confirmed present in the codebase (`ngsw.json` referenced, `staticwebapp.config.json` has explicit `no-cache` on it). AFD access logs show `ngsw-cache-bust` query parameters appearing not only on `ngsw.json`/asset-check requests but also, unexpectedly, on requests for `error.html`. There are references (unconfirmed, from memory) to three additional files: `ng-serviceworker.ts`, `ng-safetyworker.ts`, `ng-worker.min.ts` — verify these actually exist and what they do.
2. **A prior code change**, reportedly AI-agent-suggested, that "strip-replaced" an `init()` function inside a worker file (likely `ng-worker.min` or similar). This change's current state (deployed or not, correct or not) is unverified and is a priority to establish.
3. **`error.html` inclusion in the SW asset manifest**, possibly via a wildcard glob in `ngsw-config.json`, which may explain why it's being cache-busted like a normal app asset.
4. **Complete absence of SW update lifecycle instrumentation** (`SwUpdate`, `checkForUpdate`, `versionUpdates`, `unrecoverable` events) — if confirmed absent, this is both a plausible contributor to the invisibility of the bug and a concrete recommendation regardless of root cause outcome.

## Constraints

- **READ-ONLY.** Do not modify, refactor, fix, or "improve" any file. Do not run `npm install`, build commands, or anything that mutates the working tree or lockfiles.
- Do not open pull requests or create branches.
- Do not attempt to reproduce the bug by running the app locally and manipulating network conditions — this is a static code/config/history analysis task only.
- Treat any prior "fix" you find in the code with skepticism — verify what it actually does against Angular's own documented `@angular/service-worker` behavior; do not assume a past change was correct just because it was merged.

## Investigation Tasks

1. **Inventory all service-worker-related files.** Confirm existence, purpose, and whether each is stock Angular (`@angular/service-worker`) or custom/modified. Specifically verify or refute the existence of `ng-serviceworker.ts`, `ng-safetyworker.ts`, `ng-worker.min.ts`.
2. **Diff any custom worker file against the stock `ngsw-worker.js`** shipped in `node_modules/@angular/service-worker` (matching installed version). Produce a precise, line-level list of differences.
3. **Locate and analyze the `init()` strip-replace change.** Use `git log`/`git blame` on the relevant file(s) to find the commit(s). Report: commit hash, date, author (human or bot-assisted if determinable from commit message/PR), what the diff actually changes, and whether that commit is present in the branch/tag currently deployed to production (cross-reference against the CI/CD deploy tag — determine this from GH Actions history if possible).
4. **Analyze `ngsw-config.json`** in full: report every asset group, its `installMode`/`updateMode`, and whether `index.html`/`error.html`/any wildcard pattern could unintentionally include `error.html` as a managed SW asset.
5. **Determine SW registration strategy**: find where the service worker is registered (`provideServiceWorker`, `ServiceWorkerModule.register`, etc.), report the exact `registrationStrategy` value used, and explain its timing behavior relative to Angular bootstrap.
6. **Check for SW update lifecycle instrumentation**: search for any usage of `SwUpdate`, `checkForUpdate`, `versionUpdates`, `versionReady`, `unrecoverable`, `activateUpdate`. Report what exists, and if nothing, state that explicitly as a finding.
7. **Trace the `error.html` fallback path**: under what conditions does the SW (or the Angular app itself) navigate to or serve `error.html`? Is this SW-triggered, router-triggered, or something else?
8. **Cross-reference build tooling**: confirm whether the app is built with Webpack (not esbuild) as reported, locate `webpack.config.js` or equivalent, and check for `ModuleFederationPlugin`/`remotes` config — report whether Module Federation is actually in use, and if so, summarize the remote/shell configuration relevant to chunk loading.
9. **Timeline correlation**: produce a chronological list of all commits touching any SW-related file, build config, or `staticwebapp.config.json` cache headers over the last 90 days, to support correlating code changes against known incident dates (incident dates will be supplied separately by the requester).

## Out of Scope
- Azure infrastructure (AFD, APIM, WAF, App Gateway) configuration — this is being investigated separately via Azure diagnostic logs, not code
- Any live/production debugging, log pulling, or KQL query execution
- Suggesting or implementing fixes — this task is diagnostic only

## Deliverable

A single written report covering all 9 investigation tasks above, structured with one section per task, each containing:
- What was found (file paths, commit hashes, exact config values/diffs — quote precisely, don't paraphrase configuration)
- Confidence level in the finding (confirmed from code vs. inferred)
- Explicit callout if a task's premise turned out to be false (e.g., a referenced file doesn't exist) rather than silently omitting it

End the report with a ranked list of the findings most likely relevant to the WSOD symptom, and a separate list of anything found that, while not necessarily the root cause, represents a clear gap or risk (e.g., missing instrumentation, undocumented custom code) worth flagging to the dev team regardless of outcome.
