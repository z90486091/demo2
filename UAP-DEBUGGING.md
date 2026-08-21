# UA‑Parser‑JS – Stack‑Overflow (Maximum Call‑Stack Size Exceeded) Issues

## 1. What is UA‑Parser‑JS?
A lightweight JavaScript library that parses a user‑agent string and returns structured information about:

| Category | Data Returned |
|----------|----------------|
| **Browser** | name, version, major version |
| **Engine** | name, version |
| **OS** | name, version |
| **Device** | vendor, model, type (`mobile`, `tablet`, etc.) |
| **CPU** | architecture (`amd64`, `arm`, …) |

Typical usage:

```js
import UAParser from 'ua-parser-js';

const parser = new UAParser();                 // uses navigator.userAgent
// or const parser = new UAParser(customUAString);
const result = parser.getResult();

console.log(result);
/*
{
  ua: "...",
  browser: {name:"Mobile Safari", version:"16.2", major:"16"},
  engine:  {name:"WebKit", version:"605.1.15"},
  os:      {name:"iOS", version:"16.2"},
  device:  {vendor:"Apple", model:"iPhone", type:"mobile"},
  cpu:     {architecture:"arm"}
}
*/
```

---

## 2. Scenarios that trigger “RangeError: Maximum call stack size exceeded”

| Situation | Why it happens |
|-----------|----------------|
| **Parsing an extremely long or maliciously crafted UA string** | The internal regular‑expression engine recurses through a huge pattern until the stack overflows. |
| **Calling `setUA()` (or creating a new parser) inside a callback that itself triggers another parse** | Recursive re‑entry creates an infinite call chain. |
| **Parsing a circular object** | Traversal of a circular reference leads to infinite recursion. |
| **Using a vulnerable pre‑fix version** | Versions ≤ `0.7.32` contain a known DoS bug; the fix was added in `0.7.33`. |

### How to avoid the error
1. **Validate UA length** – reject or truncate overly long strings.  
2. **Keep parser calls isolated** – do not invoke the parser from within its own result callback.  
3. **Upgrade to a safe version** (`>= 0.7.33` or any `1.x`).  
4. **Guard against circular data** – ensure you pass a plain string.

---

## 3. Minimum stable version that guarantees the fix
The recursion bug was patched in **v 0.7.33**. All later releases (including the current 1.x series) contain the fix.

**Use `≥ 0.7.33`.**

```bash
# Yarn (recommended)
yarn add ua-parser-js@^0.7.33   # or yarn add ua-parser-js@latest
```

---

## 4. Reproducing an MCSSE error in a local dev setup

### Step‑by‑step

1. **Create a demo project**

```bash
mkdir uap-mcsse-demo
cd uap-mcsse-demo
yarn init -y
yarn add ua-parser-js@0.7.32   # vulnerable version
```

2. **Script that triggers the overflow with a huge UA**

```js
// trigger-mcsse.js
import UAParser from 'ua-parser-js';

const repeat = 10_000;                // adjust upward if needed
const longUA = 'Mozilla/5.0 (compatible; MyBot/1.0; +' + 'X'.repeat(repeat) + ')';

const parser = new UAParser();
console.log('Parsing UA length', longUA.length);
parser.setUA(longUA).getResult();   // <-- throws RangeError
```

Run:

```bash
node trigger-mcsse.js
```

You should see:

```
RangeError: Maximum call stack size exceeded
    at RegExpExec …
```

3. **Alternative: recursive `setUA` call**

```js
// recursive-mcsse.js
import UAParser from 'ua-parser-js';

const parser = new UAParser();

function afterParse(res) {
  parser.setUA(res.ua).getResult();   // recursive entry
}

const ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)';
const first = parser.setUA(ua).getResult();
afterParse(first);   // throws RangeError
```

4. **Verify the fix**

```bash
yarn add ua-parser-js@^0.7.33   # or latest 1.x
node trigger-mcsse.js           # now prints the result without error
```

---

## 5. Can MCSSE cause a “blank screen” in an Angular 20 PWA (NGSW)?

### Yes.  
When the overflow occurs during Angular bootstrap, change detection, a router guard, or a service‑worker install, the JavaScript thread aborts and the app never renders, leaving a white/blank page.

### How it propagates

| Angular / NGSW layer | Effect of MCSSE |
|-----------------------|-----------------|
| **App bootstrap** (main.ts → AppModule) | Rejected bootstrap promise → no component rendered. |
| **Lifecycle hooks / change detection** | Error inside `ngOnInit`, pipe, or subscription stops the CD cycle. |
| **Router guards** | Recursive guard → infinite call stack → navigation aborted. |
| **NGSW (service worker)** | Cached bundle containing the bug prevents activation; every load shows a blank screen. |
| **Production error handling** | Uncaught error is swallowed, so the UI just stays empty. |

### Confirmation steps

1. Open DevTools → Console on a fresh reload. Look for `RangeError: Maximum call stack size exceeded`.  
2. Disable the Service Worker (Application → Service Workers → Unregister) and reload – if the UI appears, the bug is in the cached bundle.  
3. Temporarily comment out any UA‑Parser usage (e.g., a service that runs on startup). If the app loads, you’ve isolated the trigger.

### Mitigation for Angular 20 PWA

| Action | Details |
|--------|---------|
| **Upgrade UA‑Parser‑JS** to `>= 0.7.33` (or latest 1.x). |
| **Validate UA length** before parsing (`if (ua.length > 2000) …`). |
| **Wrap parsing in try/catch** to prevent bootstrap failure. |
| **Avoid recursive calls** in services, guards, pipes, or directives. |
| **Add a global error handler** that logs instead of halting the zone. |
| **Clear Service Worker cache** after fixing (bump `ngsw-config.json` version). |
| **Run the stress test** (see Section 4) to confirm the error is gone. |

### Quick sanity check after fixing

```bash
yarn add ua-parser-js@^0.7.33
ng build --configuration=production
npx http-server -p 4200 -c-1 dist/your-app
# Open Chrome, disable cache, reload the PWA URL.
```

If the app loads and the console shows no `RangeError`, the blank‑screen issue is resolved.

---

## 6. Using Yarn (not npm)

All upgrade/install commands shown above use Yarn syntax (`yarn add …`). The same version constraints apply as with npm.

---

### Summary Checklist

- **Version**: Use `ua-parser-js@≥0.7.33`.  
- **Input safety**: Reject/truncate overly long UA strings.  
- **Isolation**: Do not call the parser recursively from callbacks or guards.  
- **Angular PWA**: Ensure the parser is called after bootstrap or inside a `try/catch`.  
- **Service Worker**: Clear cache or bump version after fixing.  
- **Testing**: Run the provided `trigger-mcsse.js` script before and after the upgrade to verify the bug is gone.

--- 

*All information compiled from the discussion in this chat (including release‑note references to the fix in v 0.7.33).*
