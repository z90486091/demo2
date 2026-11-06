# Runbook: Cookie Collision Between Two IIS Sites on One Hostname

## 1. Problem
- Two separate IIS websites on the same VM, same hostname `dev01-app-na-domain.com`
  - Site 1: `https://dev01-app-na-domain.com/abc`
  - Site 2: `https://dev01-app-na-domain.com/ghi`
- Logging into site 1, then site 2 in the same browser breaks the first session (cookie mismatch)
- Route: `AFD -> WAF -> AGW -> APIM` (hub) -> `VM hosting IIS` (spoke)

## 2. Root Cause
- Cookies are scoped by **host (+ path)**, not by IIS site
- Both apps share the host, and likely use the same default cookie names with `Path=/`
  - Classic ASP.NET defaults: `.ASPXAUTH`, `ASP.NET_SessionId`, `__RequestVerificationToken`
  - ASP.NET Core defaults: `.AspNetCore.Cookies`, `.AspNetCore.Session`, `.AspNetCore.Antiforgery.*`
- Rule: any cookie with the same **name + host + path** gets overwritten, whatever its purpose
- Second login overwrites the first app's cookie
- **Not the cause:** AFD, WAF, AGW, APIM (they pass cookies through; they do not merge them)

## 3. Fix Summary
- Give each app **unique cookie names** (main fix)
- Optionally scope each cookie `Path` to `/abc` or `/ghi`
- `Path` must match what the **browser sees**, not the IIS path (APIM may rewrite paths)
- Expiry/deletion alone does **not** fix the collision (see section 9)

## 4. Step 1: Identify the Framework (per site)
- **Check A: Browser DevTools -> Application -> Cookies**
  - `.ASPXAUTH` / `ASP.NET_SessionId` = classic ASP.NET
  - `.AspNetCore.Cookies` / `.AspNetCore.Session` = ASP.NET Core
- **Check B: IIS Manager -> Application Pools -> the site's pool**
  - ".NET CLR version v4.0" = classic
  - "No Managed Code" = usually Core
- **Check C: Site folder on the VM**
  - `web.config` with `<system.web>` + `bin\` DLLs = classic
  - `web.config` with `<aspNetCore ...>` + `*.runtimeconfig.json` = Core
- **Check D: Response headers**
  - `X-AspNet-Version` / `X-Powered-By: ASP.NET` = classic
  - `Server: Kestrel` = Core (out-of-process)
- Record result per site before continuing
  - Site 1 (`/abc`): ____
  - Site 2 (`/ghi`): ____

## 5. Step 2: Classify the Cookies (does purpose matter? yes)
- **Capture first**
  - Log into `/abc`, then `/ghi`, in one browser
  - DevTools -> Application -> Cookies: note every cookie Name, Domain, Path
  - DevTools -> Network: check `Set-Cookie` response headers on each login to see which hop sets which cookie
  - Same Name + Domain + Path appearing for both apps = collision candidate
- **Rename these (app-owned, per-user state)**
  - Auth: `.ASPXAUTH`, `.AspNetCore.Cookies`
  - Session: `ASP.NET_SessionId`, `.AspNetCore.Session`
  - Anti-forgery (CSRF): `__RequestVerificationToken`, `.AspNetCore.Antiforgery.*`
  - Custom app cookies: culture, tenant, "remember me", tracking
- **Infra cookies (usually leave alone)**
  - AGW affinity: `ApplicationGatewayAffinity`, `ApplicationGatewayAffinityCORS`
  - AFD affinity: `ASLBSA`, `ASLBSACORS`
  - IIS ARR: `ARRAffinity` (only if ARR is installed)
  - Affinity pins a browser to a **server**, not an app
  - Both apps are on the same VM, so a shared affinity value is harmless
- **Record result**
  - Colliding app cookies: ____
  - Infra cookies seen: ____

## 6. Step 3A: Fix for Classic ASP.NET
- Edit `web.config` of **each** site (diffs are illustrative; match your actual lines)
- Site 1 (`/abc`):

```diff
 <system.web>
   <authentication mode="Forms">
-    <forms loginUrl="~/Login" />
+    <forms loginUrl="~/Login" name=".ASPXAUTH_ABC" path="/abc" />
   </authentication>
+  <sessionState cookieName="ASP.NET_SessionId_ABC" />
 </system.web>
```

- Site 2 (`/ghi`): same change with `_GHI` and `path="/ghi"`
- **Anti-forgery cookie (conditional)**
  - Only needed if the app uses `@Html.AntiForgeryToken()` or `[ValidateAntiForgeryToken]` (MVC / Web Pages)
  - Skip for plain WebForms with no anti-forgery
  - `__RVT` = **R**equest**V**erification**T**oken; `__RVT_ABC` is just a chosen unique name
  - Edit `Global.asax.cs`:

```diff
+using System.Web.Helpers;

 protected void Application_Start()
 {
+    AntiForgeryConfig.CookieName = "__RVT_ABC";
     // existing code
 }
```

  - Site 2: use `"__RVT_GHI"`
  - Renames the cookie only; the hidden form field keeps its default name (fine)
- **machineKey check (classic only)**
  - If both sites share the same `machineKey` (explicit in `web.config`, or same auto-generated key), one app can decrypt the other's auth cookie
  - Symptom: confusing partial-login behavior
  - Fix direction: distinct `machineKey` per site
  - Confirm current state in each `web.config` before changing anything

## 7. Step 3B: Fix for ASP.NET Core
- Edit `Program.cs` of **each** site; **no `web.config` change needed**
  - Core ignores `<system.web>` (`<forms>`, `<sessionState>`)
  - Its `web.config` only holds the `<aspNetCore>` IIS handler entry
  - Touch `web.config` only for IIS-level needs (env vars, hosting model)
- Site 1 (`/abc`), illustrative; match your actual code:

```diff
-builder.Services.AddAuthentication("Cookies").AddCookie();
+builder.Services.AddAuthentication("Cookies").AddCookie(o =>
+{
+    o.Cookie.Name = ".auth_abc";
+    o.Cookie.Path = "/abc";
+});
+builder.Services.AddSession(o => { o.Cookie.Name = ".sess_abc"; o.Cookie.Path = "/abc"; });
+builder.Services.AddAntiforgery(o => o.Cookie.Name = ".af_abc");
```

- Site 2 (`/ghi`): same with `_ghi` names and `/ghi` path
- **Optional: Data Protection isolation** (both apps may share one default key ring on the same server)

```diff
+builder.Services.AddDataProtection().SetApplicationName("app-abc");
```

  - Site 2: `"app-ghi"`

## 8. Step 4: Deploy and Verify
- Redeploy both sites
- Clear old cookies for `dev01-app-na-domain.com` (they linger)
- Test in a **fresh incognito window**
- Log into `/abc`, then `/ghi`, then return to `/abc`
- DevTools -> Application -> Cookies should show:
  - Two distinct auth cookie names
  - Two distinct session cookie names
  - `/abc` session still valid after logging into `/ghi`
- Do not assume the fix is applied; confirm cookie names in DevTools

## 9. Cookie Expiry / Deletion (cleanup only, not the fix)
- **Why expiry alone fails**
  - Both apps still write the same name, so each login overwrites the other's cookie
  - A delete is a `Set-Cookie` with a past date on the same name + host + path
  - App 1 logging out would also wipe App 2's cookie
- **Where expiry helps**
  - After renaming, old cookies (e.g. `.ASPXAUTH` with `Path=/`) linger in browsers until they expire
  - A legacy `Path=/` cookie is sent to both apps and can cause confusing behavior next to the new path-scoped cookies
  - Fix: each app sends an expired `Set-Cookie` for the old name
  - Name, domain, and path must match exactly, or the delete is ignored
- **Lifetime notes**
  - Session cookies (no expiry) die when the browser closes
  - Persistent cookies (`Expires`/`Max-Age`) survive restarts
  - Shorter lifetimes reduce how long stale cookies linger
- **Order of work**
  - Rename first
  - Clear cookies manually on test machines
  - Add legacy-cookie expiry code only if users hit stale-cookie issues

## 10. Terminology: Two Different "Pools"
- **IIS app pool**
  - A worker process (`w3wp.exe`) on the VM that runs one or more IIS sites
  - View in IIS Manager -> Application Pools
  - Used in Step 1 (Check B) to identify classic vs Core
  - Isolates crashes, memory, identity per site
  - Does **not** isolate cookies (cookies live in the browser)
- **Backend pool (AGW / AFD)**
  - A group of servers the gateway load-balances across
  - Affinity cookies pin a browser to one server in that pool
  - Same VM for both apps = shared affinity value is harmless
  - Matters only if `/abc` and `/ghi` route to **different** backend pools or servers
  - Then one shared affinity cookie keeps flipping between them

## 11. Escalation Path (if renaming does not resolve it)
- Compare the backend pool and routing rule for `/abc` vs `/ghi` in AGW
- Check APIM policies/path rewrites for each route (affects browser-visible `Path`)
- Check AFD routing/caching rules for `Set-Cookie` handling on both paths
- Re-capture `Set-Cookie` headers per hop (Network tab) to see where a cookie is added or altered
- Check `machineKey` (classic) or Data Protection key ring (Core) overlap

## 12. Gotchas
- Unique **names** matter more than `Path`
- If APIM rewrites paths, set `Path` to the browser-visible path
- If `Path` is set but the app redirects to `/` outside its prefix, the cookie may not be sent; check in DevTools
- Auth cookie rename logs out existing users once (expected)

## 13. Open Items for Office PC
- [ ] Confirm framework per site (Step 1)
- [ ] Capture and classify cookies per site (Step 2)
- [ ] Confirm whether anti-forgery is used (classic only)
- [ ] Check `machineKey` overlap (classic) or Data Protection overlap (Core)
- [ ] Confirm browser-visible path vs IIS path (APIM rewrite policy)
- [ ] Confirm both routes hit the same backend pool/server
- [ ] Apply changes in dev01, then verify per Step 4
