# Detecting and Fixing Stack‑Overflow IIFEs in an Angular 20 PWA (NGSW) Built with Yarn + esbuild

---

## 1️⃣ Build an **un‑minified** bundle with source‑maps  

```bash
yarn ng build \
  --configuration production \
  --output-hashing=none \
  --source-map=true \
  --optimization=false \
  --named-chunks=true
```

*Why:*  
- Keeps every IIFE as a separate function.  
- Source‑maps let the stack‑trace point back to the original TS file.

The compiled files appear in `dist/<project‑name>/` (`main.js`, `runtime.js`, …).

---

## 2️⃣ Static scan – locate IIFEs that recurse

### 2.1 Grab all IIFE patterns (classic & arrow)

```bash
grep -RnwE --exclude-dir=node_modules \
  '(\(\s*function[^(]*\([^)]*\)\s*\{|\(\s*\([^)]*\)\s*=>\s*\{' \
  dist/ > /tmp/esbuild-iife-list.txt
```

### 2.2 Keep only those that **self‑call** (typical cause of MCSSE)

```bash
awk -F: '
{
  file=$1; line=$2;
  cmd="sed -n "line",${line}+30p " file
  cmd | getline src; close(cmd);

  if (src ~ /function[[:space:]]+([a-zA-Z0-9_$]+)[[:space:]]*\([^)]*\)[[:space:]]*\{[^}]*\1\s*\(/ ||
      src ~ /([a-zA-Z0-9_$]+)\s*=>\s*\{[^}]*\1\s*\(/) {
    print file ":" line
  }
}
' /tmp/esbuild-iife-list.txt > /tmp/esbuild-iife-recursive.txt
```

Open any line from `/tmp/esbuild-iife-recursive.txt` (e.g. `dist/main.js:10342`) – that file/line is a **candidate** that may be throwing `RangeError: Maximum call stack size exceeded`.

---

## 3️⃣ ESLint lint on the **source TypeScript** (fix before bundling)

### 3.1 Create a custom rule `no-self-iife`

Create `tools/eslint-plugin-no-self-iife/index.js`:

```js
module.exports = {
  rules: {
    "no-self-iife": {
      meta: {
        type: "problem",
        docs: {
          description: "Disallow IIFEs that recursively call themselves (stack‑overflow risk)",
          category: "Possible Errors"
        },
        schema: []
      },
      create(context) {
        return {
          // Classic function IIFE
          "CallExpression[callee.type='FunctionExpression']"(node) {
            const fn = node.callee;
            const name = fn.id && fn.id.name;
            if (!name) return;

            const body = fn.body.body;
            const hasSelfCall = body.some(
              stmt =>
                stmt.type === "ExpressionStatement" &&
                stmt.expression.type === "CallExpression" &&
                stmt.expression.callee.name === name
            );

            if (hasSelfCall) {
              context.report({
                node,
                message: "IIFE '{{name}}' recursively calls itself – may cause a stack overflow",
                data: { name }
              });
            }
          },

          // Arrow‑function IIFE (usually assigned to a const)
          "CallExpression[callee.type='ArrowFunctionExpression']"(node) {
            const parent = node.parent;
            const name = parent && parent.type === "VariableDeclarator" && parent.id.name;
            if (!name) return;

            const body = node.callee.body.body || [];
            const hasSelfCall = body.some(
              stmt =>
                stmt.type === "ExpressionStatement" &&
                stmt.expression.type === "CallExpression" &&
                stmt.expression.callee.name === name
            );

            if (hasSelfCall) {
              context.report({
                node,
                message: "Arrow‑function IIFE '{{name}}' recursively calls itself – may cause a stack overflow",
                data: { name }
              });
            }
          }
        };
      }
    }
  }
};
```

### 3.2 Wire the plugin

`.eslintrc.json`

```json
{
  "plugins": ["no-self-iife"],
  "rules": {
    "no-self-iife/no-self-iife": "error"
  }
}
```

### 3.3 Run the lint

```bash
yarn eslint src/**/*.ts --ext .ts,.js
```

All offending IIFEs (including those inside `ua-parser-js` if you imported the source) will be reported with file + line numbers. Fix them by adding a proper terminating condition or by refactoring to a regular function.

---

## 4️⃣ Runtime guard (quick dev‑only check)

`src/app/debug/stack-guard.ts`

```ts
let depth = 0;
const MAX_DEPTH = 1e5; // safe ceiling

export function guard<T extends (...args: any[]) => any>(fn: T, name: string): T {
  return ((...args: any[]) => {
    if (++depth > MAX_DEPTH) {
      throw new RangeError(`Potential infinite recursion in IIFE "${name}"`);
    }
    try {
      return fn(...args);
    } finally {
      depth--;
    }
  }) as unknown as T;
}
```

Wrap a suspect IIFE:

```ts
import { guard } from '../debug/stack-guard';

const parseUA = guard(function parseUA(){ /* … */ }, 'parseUA');
parseUA();   // still an IIFE but now guarded
```

Run the app (`yarn ng serve`). When the guard trips you’ll see a clean error message that tells you exactly which IIFE is looping, before the native stack overflow occurs.

---

## 5️⃣ Global error listener (no source rebuild)

Add at the top of `src/main.ts`:

```ts
window.addEventListener('error', ev => {
  const err = ev.error;
  if (err && /Maximum call stack size exceeded/.test(err.message)) {
    console.error('🚨 Stack overflow detected →', err.stack);
  }
});
```

When the app loads, the console prints a stack trace; the **last distinct file** in that trace points to the offending IIFE (e.g., `ua-parser.min.js` or `main.js`).

---

## 6️⃣ What to do after you locate the culprit

1. **Add a termination condition** (counter, `if (…) return;`, etc.).  
2. **Refactor** – replace the recursive IIFE with a normal named function called once.  
3. **Upgrade `ua-parser-js`** (many older releases bundled a recursive parser).  

```bash
yarn upgrade ua-parser-js@latest
```

4. Re‑run the production esbuild build (`yarn ng build --configuration production`) and verify the error disappears.

---

## 7️⃣ Quick cheat‑sheet (one‑liner)

```bash
# Build un‑optimised bundle
yarn ng build --configuration production --optimization=false --source-map=true --output-hashing=none

# Find self‑calling IIFEs
grep -RnwE '(\(\s*function[^(]*\([^)]*\)\s*\{|\(\s*\([^)]*\)\s*=>\s*\{' dist/ > /tmp/i.txt
awk -F: '{
  file=$1; line=$2;
  cmd="sed -n "line",${line}+30p " file; cmd|getline src; close(cmd);
  if (src ~ /function[[:space:]]+([a-zA-Z0-9_$]+)[[:space:]]*\([^)]*\)[[:space:]]*\{[^}]*\1\s*\(/ ||
      src ~ /([a-zA-Z0-9_$]+)\s*=>\s*\{[^}]*\1\s*\(/) print file ":" line
}' /tmp/i.txt > /tmp/recursive-iifes.txt
```

Open any line from `/tmp/recursive-iifes.txt`, fix the code, rebuild, and the **Maximum call stack size exceeded** error goes away.

--- 

### 🎉 That’s the complete, Yarn + esbuild‑compatible workflow to **detect, isolate, and fix** the IIFE causing a stack‑overflow in your Angular 20 PWA. Happy debugging!
