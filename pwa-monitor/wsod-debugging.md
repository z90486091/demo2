# AUTHY_ERR Debug Cheatsheet

## Breakpoints to set (DevTools → Sources → click line number in gutter)

1. `authy.service.ts` — `handle()` entry / the `setIsAuthRedirecting(true)` dispatch line
2. `authy.service.ts` — the `throw Error(() => 'AUTHY_ERR')` line (or your temp `throw 'AUTHY_ERR'`)
3. `auth.callback.component.ts` — first line inside `catchError(error => {...})`
4. `auth.callback.component.ts` — the `if(!typeof error === 'string' && ...)` condition line
5. `authy.service.ts` — the `setIsAuthRedirecting(false)` dispatch line (gated on query-param/account condition) — set this to confirm it's NOT hit on the AUTHY_ERR path

Step through in order: F10 (step over), F11 (step into), F8 (resume to next breakpoint).

## Force the throw (poor-man's debugger)

```diff
 handle() {
+	throw 'AUTHY_ERR'; // TEMP debug throw — revert after
 	return this.http.get(this.authyUrl).pipe(
 		catchError(() => throw Error(() => 'AUTHY_ERR')),
 	);
 }
```

Revert before commit/deploy.

## What to watch, step by step

| Step | Where | Expected (per thesis) | If different |
|---|---|---|---|
| 1 | `isRedirecting` initial | `false` | — |
| 2 | Right before/at `handle()` call | `false → true` | reset already exists earlier than thought |
| 3 | Forced throw fires | enters `catchError` | if it DOESN'T enter here, something upstream is catching it first — new lead |
| 4 | `auth.callback.component.ts` catch condition | always evaluates `false` (precedence bug) → `/generic-error` never called | if it DOES navigate, the precedence bug isn't what you think — re-check the pasted code vs real code |
| 5 | After `catchError` returns `of(undefined)` | `isRedirecting` stays `true` — no dispatch | if it flips to `false` here, there's a reset path neither of us found — most valuable possible surprise |
| 6 | Next reload / fresh page load | resets to `false` (in-memory, no persistence) | if it's still `true` after a fresh load, localStorage/persistence theory is back in play |

## Quick checks while stepped in

- Inspect `error` value at the `catchError` callback — is it literally the string `'AUTHY_ERR'`, or an `Error` object? (confirms/denies the throw-site bug)
- Check call stack at the moment of throw — anything upstream you didn't expect?
- Watch NgRx state panel (if extension installed) or `console.log` the store's auth slice — confirm actual `true`/`false` transitions match the table above

## After the session

- Revert the temp `throw` line
- Note any step where reality diverged from the "Expected" column — that's the actual finding, not the whole table
