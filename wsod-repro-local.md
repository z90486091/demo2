# WSOD Local Repro — Deterministic Steps

Goal: reproduce the confirmed symptom (zero-byte 200 JS chunk -> stuck spinner,
mislabeled by SRE as "blank page") on office PC, without guessing.

Does NOT explain root cause of why the real chunk returns zero-byte in prod
(client-side/network-path, unconfirmed). This reproduces the EFFECT only.

---

## 1. Build matching prod exactly

```bash
git checkout <prod-tag-or-branch>   # must match what's actually deployed
./scripts/build.sh                  # NOT `ng serve` — dev server doesn't
                                     # chunk/hash the same way as prod
```

## 2. Serve as static files (matches how SWA actually serves it)

```bash
npx http-server dist/webapp1/browser -p 4200
```

Open `http://localhost:4200` in Chrome.

## 3. Identify the chunk(s) containing the redirect/auth logic

Do NOT try to match prod HAR filenames — hashes are build-specific and will
differ locally. Instead, grep the built output directly:

```bash
grep -rl "AUTHY_ERROR" dist/webapp1/browser/*.js
grep -rl "isPathRedirecting" dist/webapp1/browser/*.js
```

If multiple files match, rank by occurrence count to find the primary one:

```bash
grep -o "AUTHY_ERROR" dist/webapp1/browser/*.js | sort | uniq -c
```

Note all matching filenames — you may need to test them individually or
together (see step 5).

## 4. Force one (or more) of those chunks to 200 + zero-byte

DevTools → **Sources** tab → **Overrides** sub-tab:
1. "Select folder for overrides" → pick any local folder → allow file access
2. Network tab → reload once to populate the request list
3. Right-click the target chunk (filename from step 3) → **Override content**
4. In the opened editor: Ctrl+A → Delete → Ctrl+S (saves as an empty file)
5. Reload the page (Ctrl+R)
6. Confirm in Network tab: that request now shows **200**, **0 B** — matches
   the confirmed real-incident symptom exactly

(Blocking the request instead — "Block request URL" — does NOT produce this;
it returns `net::ERR_BLOCKED_BY_CLIENT`, a different failure mode. Use
Override content, not Block.)

## 5. If a single chunk doesn't reproduce it

- Override ALL matching chunks from step 3 simultaneously, reload once
- If symptom appears only with all of them empty: restore one at a time,
  re-test, to isolate which specific chunk (or combination) is required
- If it never reproduces even with all matching chunks emptied: the failure
  may depend on load-order/timing (race), not just chunk content — note this
  as a finding, don't force further guessing

## 6. Confirm the actual symptom, not just the network state

- Open DevTools **console** — note any errors thrown
- If Redux/NgRx DevTools extension is installed: open it, watch the
  `isRedirecting` (or actual state key — confirm exact name from your
  reducer) value through page load — confirm whether it gets set `true`
  and is never reset back to `false`
- If NgRx DevTools isn't available: add a temporary `console.log` inside the
  reducer's case(s) for that flag, rebuild (step 1), repeat

---

## What this does NOT tell you

- Why the real chunk returns zero-byte in prod (root cause still unconfirmed)
- Whether AFD cache is actually in the causal chain (contradicted by BOS/SJC
  catches occurring with cache disabled)
- Whether this exact mechanism is what SRE/customers have been reporting —
  it reproduces the confirmed symptom pattern, not a confirmed root cause
