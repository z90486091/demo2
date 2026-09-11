# WSOD / Stuck-Redirect Investigation — Final Ripgrep Checklist

Context: prod is currently stable (zero reports, ~7-10 days high/peak traffic,
after AFD cache disabled). This is NOT an active incident — this checklist is
for confirming/ruling out a latent bug, next time there's PC access.

Working theory: `catchError` in the App→Authy `ngOnInit` redirect flow has a
fall-through case (`isAuthyError === true`) that does nothing — no dispatch,
no nav, no log. If nothing else resets the `isRedirecting` flag on that
specific path, it could stay `true` forever for that session (stuck spinner).

---

## 1. Where does `isRedirecting` get set to `true`?

```bash
rg -n -B5 "isRedirecting:\s*true" --type ts
```

**Next step per result:**
- Dispatch site has no status-code/error awareness (looks like "request
  started" logic) → `true` = generic "auth check in flight," not tied to a
  specific failure mode. Move to step 2, this isn't informative on its own.
- Dispatch site is tied to a specific condition (e.g. only on 401/403, or
  only on stale-session detection) → note the exact trigger condition, may
  narrow which real-world scenario reproduces this.
- No results at all → `isRedirecting` isn't set via a literal boolean
  anywhere findable this way; it's likely computed/derived. Different
  investigation needed (check selectors/computed state instead).

---

## 2. Where does `isRedirecting` get reset to `false`?

```bash
rg -n -B5 "isRedirecting:\s*false" --type ts
```

**Next step per result:**
- `false` only appears under a **success** case (e.g. `on(AuthActions.
  authenticated, ...)` or similar login-success/signup action) → confirms
  the bug theory: no reset exists for the App→Authy failure path
  specifically. Proceed to step 3.
- `false` also appears under a **generic error/failure** action that would
  fire regardless of error type (including `AUTHY_ERROR`) → bug theory is
  likely dead, this component's `catchError` fall-through isn't the actual
  problem. Stop here, re-open only if a real incident recurs.
- `false` appears in a **different component/file** than where `true` is
  set (e.g. the Authy→App success-callback component, not the App→Authy
  redirect component) → supports the theory further: the reset only exists
  on the path that presumes success, and is unreachable if Authy errors out
  before redirecting back. Proceed to step 3.

---

## 3. Is the reset action reachable from the `AUTHY_ERROR` branch specifically?

```bash
rg -n "AUTHY_ERROR" -l
rg -n "throw.*AUTHY_ERROR"
```

**Next step per result:**
- Throw site found, and it's inside `authFacade.handle()` (or deeper, e.g.
  an HTTP interceptor) with no accompanying dispatch/reset call on that
  exact line/branch → confirms the gap end-to-end: nothing resets the flag
  when this specific error is thrown. This is the strongest evidence for
  the bug. Proceed to step 4 only if/when you want to actually patch it.
- Throw site dispatches its own reset action before throwing → bug theory
  dead, `catchError` in `ngOnInit` never needed to handle it. Stop here.
- No throw site found in current code → `AUTHY_ERROR` may be dead/unused
  string, or thrown dynamically (e.g. from a shared error-mapping utility
  by string comparison elsewhere) → broaden search:
  `rg -n "'AUTHY_ERROR'|\"AUTHY_ERROR\""` (without `throw` prefix).

---

## 4. (Only if steps 1–3 confirm the bug) — apply the fix

Add a dispatch on the `AUTHY_ERROR` fall-through branch in `ngOnInit`'s
`catchError`, using whichever real reset action step 2 identified — do not
invent an action name; use the confirmed one from the codebase.

```diff
 catchError(error => {
 	const isAuthyError = error === AUTHY_ERROR;
 	if (!isAuthyError) {
 		this.router.navigate(['/generic-error'])
+	} else {
+		this.store.dispatch(/* confirmed reset action from step 2 */);
 	}
 	return of(undefined)
 })
```

---

## Notes / already-ruled-out

- MCSSE (Maximum call stack size exceeded) — treated as BAU, decoupled from
  WSOD (occurs on non-blank-page sessions too).
- AFD as root cause — ruled out (zero-byte-200s timestamp-correlate across
  unrelated third-party domains too, points to client-side/network-path).
- Duplicate/reused `state` query param — expected behavior, red herring.
- Authy endpoint itself being the bug — no reliable evidence it's even
  self-hosted; not considered the bug.
- AFD cache disabled → zero reports for ~7-10 days at high traffic — best
  current evidence the *previously live* issue was cache-related, separate
  from this latent `isRedirecting` question.
