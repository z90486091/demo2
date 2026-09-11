# WSOD Local Repro PoC — Fully Automated

One command, no manual DevTools steps. Builds prod bundle, serves it, auto-detects
the chunk(s) containing the auth-redirect logic, forces them to 200/zero-byte,
and captures console/network/HAR/screenshot of `ngOnInit`'s reaction.

Goal: observe actual `ngOnInit` behavior for the auth-redirect flow under a
forced zero-byte-chunk failure — NOT a root-cause finding for why the real
chunk goes zero-byte in prod (still unconfirmed).

---

## Prereqs (one-time)

```bash
npm install -D playwright http-server
npx playwright install chromium
```

---

## `run-repro.sh` — the one command you actually run

```bash
#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR="dist/webapp1/browser"
PORT=4200
BASE_URL="http://localhost:${PORT}"

echo "[1/5] Building prod bundle..."
./scripts/build.sh

echo "[2/5] Auto-detecting auth-redirect chunk(s)..."
CHUNKS=$(grep -rl "AUTHY_ERROR" "${BUILD_DIR}"/*.js | xargs -n1 basename | tr '\n' ' ')
if [ -z "$CHUNKS" ]; then
  echo "No chunk matched 'AUTHY_ERROR' — falling back to 'isPathRedirecting'..."
  CHUNKS=$(grep -rl "isPathRedirecting" "${BUILD_DIR}"/*.js | xargs -n1 basename | tr '\n' ' ')
fi
if [ -z "$CHUNKS" ]; then
  echo "ERROR: no matching chunk found. Check BUILD_DIR path and search strings."
  exit 1
fi
echo "Targeting chunk(s): ${CHUNKS}"

echo "[3/5] Serving build on ${BASE_URL}..."
npx http-server "${BUILD_DIR}" -p "${PORT}" -s &
SERVER_PID=$!
sleep 2

echo "[4/5] Running automated repro..."
node automate-repro.js "${BASE_URL}" ${CHUNKS}

echo "[5/5] Cleaning up..."
kill "${SERVER_PID}" 2>/dev/null || true

echo "Done. See repro-output/<timestamp>/ for results."
```

```bash
chmod +x run-repro.sh
./run-repro.sh
```

That's the entire manual involvement: one command, one terminal.

---

## `automate-repro.js` — called automatically by the script above

```javascript
/**
 * Intercepts and forces the auto-detected chunk(s) to 200 + zero-byte,
 * navigates, captures console/pageerror output, network log, HAR, screenshot.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function main() {
  const [, , baseUrl, ...chunkPatterns] = process.argv;

  if (!baseUrl || chunkPatterns.length === 0) {
    console.error('Usage: node automate-repro.js <baseUrl> <chunkPattern1> [chunkPattern2 ...]');
    process.exit(1);
  }

  const outDir = path.join(__dirname, 'repro-output', String(Date.now()));
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    recordHar: { path: path.join(outDir, 'repro.har') },
  });
  const page = await context.newPage();

  const consoleLog = [];
  const networkLog = [];

  page.on('console', (msg) => {
    const entry = `[${msg.type()}] ${msg.text()}`;
    consoleLog.push(entry);
    console.log(entry);
  });

  page.on('pageerror', (err) => {
    const entry = `[pageerror] ${err.message}\n${err.stack ?? ''}`;
    consoleLog.push(entry);
    console.log(entry);
  });

  await page.route('**/*', async (route) => {
    const url = route.request().url();
    const isTarget = chunkPatterns.some((pattern) => url.includes(pattern));
    if (isTarget) {
      console.log(`[override] forcing 200/0B for: ${url}`);
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/javascript' },
        body: '',
      });
    } else {
      await route.continue();
    }
  });

  page.on('response', async (res) => {
    try {
      const body = await res.body().catch(() => null);
      networkLog.push({
        url: res.url(),
        status: res.status(),
        bytes: body ? body.length : null,
      });
    } catch {
      // ignore bodies that can't be read (e.g. redirects)
    }
  });

  console.log(`Navigating to ${baseUrl} with override on: ${chunkPatterns.join(', ')}`);
  await page.goto(baseUrl, { waitUntil: 'networkidle' });

  // Give any async auth-check / redirect logic time to run and (hopefully) fail.
  await page.waitForTimeout(8000);

  await page.screenshot({ path: path.join(outDir, 'screenshot.png'), fullPage: true });

  fs.writeFileSync(path.join(outDir, 'console.log'), consoleLog.join('\n'));
  fs.writeFileSync(path.join(outDir, 'network.json'), JSON.stringify(networkLog, null, 2));

  const zeroByteHits = networkLog.filter((n) => n.status === 200 && n.bytes === 0);
  console.log(`\nZero-byte 200 responses observed: ${zeroByteHits.length}`);
  zeroByteHits.forEach((n) => console.log(`  - ${n.url}`));

  await context.close();
  await browser.close();

  console.log(`\nOutput saved to: ${outDir}`);
  console.log('  - repro.har       (compare against real incident HARs)');
  console.log('  - console.log     (all console + pageerror output)');
  console.log('  - network.json    (full response status/byte-size log)');
  console.log('  - screenshot.png  (final page state — check for stuck spinner)');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

---

## Output (per run, in `repro-output/<timestamp>/`)

- `repro.har` — compare directly against your real BOS/SJC/Aug-5/6 HAR captures
- `console.log` — all console output + thrown errors (surfaces `AUTHY_ERROR` if it fires visibly)
- `network.json` — every response's status + byte size, flags zero-byte 200s automatically
- `screenshot.png` — final rendered state; stuck spinner is visible here

## What this does NOT tell you (still unresolved)

- Why the real chunk returns zero-byte in prod — root cause remains client-side/network-path, unconfirmed
- Whether `isRedirecting` itself gets stuck — headless Chromium has no Redux DevTools extension, so the flag's actual value isn't captured, only its visible side effects (console errors, final screenshot state). To see the flag directly, add a temporary `console.log` inside the reducer's `isRedirecting` case(s) and rebuild — `automate-repro.js`'s console capture will then pick it up automatically, no other change needed.
- Whether this mechanism matches what's actually happening in prod — this reproduces the *confirmed symptom pattern* (zero-byte chunk → observe reaction), not a proven root cause
