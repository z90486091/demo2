# k6 Same-User Audit Row Contention Test: Summary

## Goal
- Load test webapp -> DB using ONE login (one user, one row).
- Check whether row contention occurs on the audit UPDATE after SFUSL (SELECT FOR UPDATE SKIP LOCKED), with the 2-min debounce left on.

## Environment (as stated)
- Dev: Azure App Service -> PG Flexible Server. No Pumba.
- AppDynamics is prod-only. Dev has only App Insights and Azure metrics.
- No read access to the dev PG DB currently.
- k6 runs on the office PC. The k6 login was failing with correct credentials.
- Audit UPDATE matches on userId + SSO token (from earlier context).

## Can multiple VUs share one login?
- Yes. Each VU has its own cookie jar; k6 adds no race conditions itself.
- Any breakage comes from the app: single-session enforcement, lockouts, shared-row conflicts, CSRF/rotating tokens, MFA/captcha.
- Unconfirmed: whether a second login invalidates the first session.

## k6 tool choice
- k6 HTTP (protocol level): replays the requests behind clicks; scales to many VUs. Use this for load.
- k6 browser module: real clicks, one Chromium per VU; only practical for a few VUs.

## Why same-login VUs fit this test
- All VUs hit the same userId + SSO token row.
- A per-VU login may rewrite the token and invalidate other VUs' sessions. Prefer login once in `setup()` and share the session.

## Things that can hide the lock
- 2-min debounce: location unconfirmed (client JS, server memory, or SQL). If server-side or SQL, only ~1 UPDATE per 2 min reaches the row.
- SKIP LOCKED: concurrent callers skip instead of waiting. Compare request count vs UPDATE count.
- Short lock hold time: a fast commit may not overlap.
- Per-instance debounce: prod has 3 instances; scale dev to 3. `ARRAffinity` pins a session to one instance; strip it or disable it in dev.
- Same transaction vs split transactions for SFUSL and UPDATE: unconfirmed. Same tx -> skips; split tx or other writers -> lock waits.

## Test shape
- 5-20 VUs, one shared session, at least 10 min (several debounce windows).
- Run from inside Azure (VM or Azure Load Testing) if possible, to avoid Zscaler and latency noise.
- Compare baseline (plain UPDATE) vs sfusl variants.

## Evidence without DB read access
- App Insights JDBC dependency telemetry: UPDATE duration spikes vs a 1-VU baseline, same `operation_id`.
- Custom logging (if missing): SFUSL row returned vs none, debounce proceed/suppress, gap between SFUSL end and UPDATE start.
- Azure metrics: coarse only (connections, IOPS, CPU); row locks won't show.
- Only if server parameters can be changed: `log_lock_waits=on`, `deadlock_timeout=200ms`, diagnostic settings to Log Analytics, Query Store + wait sampling.

KQL:
```
dependencies | where data has "UPDATE" | summarize percentiles(duration, 50, 95, 99) by bin(timestamp, 10s)
```

## Login failure: diagnosis
- 1 VU / 1 min is not concurrency, but the default function loops and re-logs in each iteration.
- Likelier causes: CSRF/hidden field, SSO redirect flow, wrong URL or body encoding (form vs JSON), missing headers (`Origin`, `Referer`, `User-Agent`), account locked from earlier failures, Zscaler TLS (`x509` error).
- A wrong password may return 200 with the login page, so use a `check()` on a post-login marker.
- Capture: status, `Location` header, first ~300 chars of body, and the real login request from browser DevTools (Network, Preserve log).

## CLI vs script options
- Precedence (low -> high): defaults, script `options`, env vars (`K6_VUS` etc.), CLI flags.
- With `scenarios` in the script, CLI `--vus/--iterations/--duration` replace them with one default scenario.
- `iterations` can't be combined with `stages`.
- Confirm startup output says `1 iterations shared among 1 VUs`.
- Simple option: edit the script to `vus: 1, iterations: 1` and remove `duration`/`stages`/`scenarios`.

## Options block: login debug (1 VU, 1 iteration)
```javascript
export const options = {
  vus: 1,
  iterations: 1,
  noCookiesReset: true,
  throw: true,
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36',
  thresholds: {
    checks: [{ threshold: 'rate==1', abortOnFail: true }],
  },
  // insecureSkipTLSVerify: true, // last resort, dev only
};

// on the login request:
// http.post(url, body, { redirects: 0, tags: { name: 'login' } });
```

## Options block: same-session contention (many VUs)
```javascript
export const options = {
  noCookiesReset: true,
  throw: true,
  setupTimeout: '120s',
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  scenarios: {
    same_user: {
      executor: 'constant-vus',
      vus: 10,
      duration: '10m',
      gracefulStop: '30s',
    },
  },
  thresholds: {
    checks: ['rate>0.99'],
    'http_req_duration{name:audit_call}': ['p(99)<2000'],
  },
};

// on the audit-triggering request:
// http.get(url, { tags: { name: 'audit_call' } });
```

## Reuse login across iterations (no browser)
```javascript
import http from 'k6/http';
import { check } from 'k6';

const BASE = 'https://YOUR-DEV-APP';

export const options = {
  vus: 1,
  iterations: 5,
  noCookiesReset: true,
  setupTimeout: '120s',
};

export function setup() {
  const res = http.post(`${BASE}/login`, { username: __ENV.APP_USER, password: __ENV.APP_PASS }, {
    redirects: 0,
    tags: { name: 'login' },
  });
  check(res, { 'login ok': (r) => r.status === 200 || r.status === 302 });

  // setup() has its own cookie jar, so return the values to pass on
  const cookies = http.cookieJar().cookiesForURL(BASE);
  return { sid: cookies['JSESSIONID'] && cookies['JSESSIONID'][0] };
}

export default function (data) {
  const jar = http.cookieJar();
  jar.set(BASE, 'JSESSIONID', data.sid);

  const res = http.get(`${BASE}/YOUR-AUDIT-TRIGGER-URL`, { tags: { name: 'audit_call' } });
  check(res, { 'still logged in': (r) => r.status === 200 && !r.url.includes('login') });
}
```
- Placeholders to replace from DevTools: `BASE`, `/login` path, form field names, cookie name `JSESSIONID`, audit trigger URL.
- If login is an SSO redirect: script each redirect step, or copy a valid session cookie from the browser into an env var and skip the login call.
- If sessions time out, re-login when `res.url` contains `login`.

Run:
```bash
APP_USER=xxx APP_PASS=yyy k6 run script.js
# debug only; prints credentials, remove afterwards:
k6 run --http-debug=full script.js
```

## Open items (need office PC / answers)
- Login type: form POST or SSO redirect? CSRF token?
- Session type: `JSESSIONID`, bearer token, or both?
- Which request fires the audit UPDATE? Is it called ~1/sec by a browser timer?
- Where does the 2-min debounce live?
- SFUSL and UPDATE: same transaction or separate?
- Dev App Service instance count and `ARRAffinity` setting.
- Failed login response: status, `Location`, body snippet.
- Current `options` block in the existing script.

**TLDR**
- Use `page.waitForTimeout(ms)` between steps. Set `maxDuration` if the run lasts over 10 min.

**Pause helper (add near the top of the script)**
```javascript
// fixed pause
const pause = (page, ms) => page.waitForTimeout(ms);

// random pause between minMs and maxMs (more realistic than a fixed pause)
const think = (page, minMs, maxMs) =>
  page.waitForTimeout(minMs + Math.random() * (maxMs - minMs));
```

**Use between steps**
```javascript
await page.locator('#your-button').click();
await think(page, 2000, 5000);   // 2-5 s

await page.locator('#your-dropdown').selectOption('value');
await think(page, 2000, 5000);

await pause(page, 130000);       // 130 s: outlasts one 2-min debounce window
```

**Notes**
- **`page.waitForTimeout` vs `sleep()`:** the k6 docs recommend `waitForTimeout` in browser scripts, since `sleep()` is synchronous and can block the browser's event handling. Check your k6 version's docs to confirm.
- **`maxDuration`:** with `iterations: 1`, the `shared-iterations` executor's default is 10 min. Longer runs are killed unless you set it.
```javascript
export const options = {
  scenarios: {
    ui: {
      executor: 'shared-iterations',
      vus: 1,
      iterations: 1,
      maxDuration: '30m',
      options: { browser: { type: 'chromium' } },
    },
  },
};
```
- **Timing the windows:** vary pauses (2-5 s short, occasional 130 s) so actions land at different points in each debounce window, including right after expiry.
- **Second tab:** `const page2 = await context.newPage();` shares the session, and needs its own pauses.
- **Close pages:** call `await page.close()` in a `finally` block.

**Question:** do you want me to write the two-tab version (tab 1 running the workflow, tab 2 idle or with its own actions)?
