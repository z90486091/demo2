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
- Second login overwrites the first app's cookie
- **Not the cause:** AFD, WAF, AGW, APIM (they pass cookies through; they do not merge them)

## 3. Fix Summary
- Give each app **unique cookie names**
- Optionally scope each cookie `Path` to `/abc` or `/ghi`
- `Path` must match what the **browser sees**, not the IIS path (APIM may rewrite paths)

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

## 5. Step 2A: Fix for Classic ASP.NET
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

## 6. Step 2B: Fix for ASP.NET Core
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

## 7. Step 3: Deploy and Verify
- Redeploy both sites
- Clear old cookies for `dev01-app-na-domain.com` (they linger)
- Test in a **fresh incognito window**
- Log into `/abc`, then `/ghi`, then return to `/abc`
- DevTools -> Application -> Cookies should show:
  - Two distinct auth cookie names
  - Two distinct session cookie names
  - `/abc` session still valid after logging into `/ghi`
- Do not assume the fix is applied; confirm cookie names in DevTools

## 8. Gotchas
- Unique **names** matter more than `Path`
- If APIM rewrites paths, set `Path` to the browser-visible path
- If `Path` is set but the app issues redirects to `/` outside the prefix, cookie may not be sent; check in DevTools
- Auth cookie rename logs out existing users once (expected)

## 9. Open Items for Office PC
- [ ] Confirm framework per site (Step 1)
- [ ] Confirm whether anti-forgery is used (classic only)
- [ ] Confirm browser-visible path vs IIS path (APIM rewrite policy)
- [ ] Apply changes in dev01, then verify per Step 3
