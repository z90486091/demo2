# **Angular SW Cache Issue Resolution**

[https://gemini.google.com/app/1e14ed381afcf2be](https://gemini.google.com/app/1e14ed381afcf2be)

*User prompt: Big finding — reframes everything. Angular's service worker adds a third cache layer (in-browser, per-user), separate from AFD and any server-side cache. Most likely tie-in to what you've already confirmed: SW checks for updates by fetching ngsw.json on each load and comparing hashes If ngsw.json itself gets cached by AFD (stale), SW clients keep seeing "no update available" → serve old cached app shell/chunks forever, per-browser AFD purge → next ngsw.json fetch is fresh → SW finally detects the real update → explains why server-side purge fixes a client-side symptom Next check: confirm ngsw.json's cache-control in staticwebapp.config.json — if it's not explicitly no-cache, this is your strongest lead yet, and ties both AFD's role AND the intermittent, purge-fixable pattern together in one coherent mechanism. CONTEXT: AZURE CLOUD ARCH FLOW: HUB(AFD \-\> WAF \-\> FIREWALL \-\> APP GATEWAY \-\> APIM) \----\> SPOKE(SWA)*

Response: TLDR: Correct. A cached ngsw.json prevents Angular's Service Worker from detecting new deployment hashes. Enforce Cache-Control: no-cache, no-store, must-revalidate in staticwebapp.config.json.

---

*User prompt: WHAT IS NGSW.JSON AND WHAT IS AN EXAMPLE CONTENT?*

Response: TLDR: ngsw.json is Angular Service Worker's generated manifest file containing application version hashes, URLs, and caching strategies.

`{`  
  `"configVersion": 1,`  
  `"timestamp": 1700000000000,`  
  `"index": "/index.html",`  
  `"assetGroups": [`  
    `{`  
      `"name": "app",`  
      `"installMode": "prefetch",`  
      `"updateMode": "prefetch",`  
      `"cacheQueryOptions": {`  
        `"ignoreSearch": true`  
      `},`  
      `"urls": [`  
        `"/favicon.ico",`  
        `"/index.html",`  
        `"/main.d41d8cd98f00b204e980.js",`  
        `"/styles.e258102e3b2e564d6021.css"`  
      `],`  
      `"patterns": []`  
    `}`  
  `],`  
  `"hashTable": {`  
    `"/favicon.ico": "a1b2c3d4e5f6...",`  
    `"/index.html": "f6e5d4c3b2a1...",`  
    `"/main.d41d8cd98f00b204e980.js": "1234567890ab...",`  
    `"/styles.e258102e3b2e564d6021.css": "cdef12345678..."`  
  `},`  
  `"navigationUrls": [`  
    `{`  
      `"positive": true,`  
      `"regex": "^/.*$"`  
    `}`  
  `]`  
`}`

---

*User prompt: SO THE SOLUTION IS TO SET NO-CACHE FOR /NGSW.JSON IN SWA.CONFIG.JSON?*

Response: TLDR: Yes. Add a route rule for /ngsw.json in staticwebapp.config.json enforcing Cache-Control: no-cache, no-store, must-revalidate.

`{`  
  `"routes": [`  
    `{`  
      `"route": "/ngsw.json",`  
      `"headers": {`  
        `"cache-control": "no-cache, no-store, must-revalidate"`  
      `}`  
    `}`  
  `]`  
`}`

---

*User prompt: WHY ARE THESE ALSO ADDITIONALLY REQUIRED? no-store, must-revalidate WONT no-cache SUFFICE?*

Response: TLDR: Browsers and intermediate caches often misinterpret no-cache as "cache it, but revalidate before use." Adding no-store forbids caching entirely, while must-revalidate prevents stale serving if revalidation fails. Combining all three guarantees immediate delivery of fresh data.

---

*User prompt: SO WHAT IS BEST PRACTICE? A) no-cache, OR B) no-cache, no-store, must-revalidate C) SOMETHING ELSE*

Response: TLDR: **Option B** (no-cache, no-store, must-revalidate) is best practice for manifest/configuration files like ngsw.json to prevent aggressive proxy caching.

---

*User prompt: SWA.CONFIG.JSON HAS MANY ENTRIES... 80% OF WHICH ARE ONLY "NO-CACHE"... 20% ARE CACHE WITH "MAX-AGE"*

Response: TLDR: no-cache allows caching but forces server revalidation via ETags. That works for assets, but for ngsw.json, no-store is safest to completely bypass AFD/browser caching.

---

*User prompt: WHY NOT USE ALL 3 FOR NO-CACHE INSTEAD OF JUST 1 FOR \_ALL\_ ROUTES IN SWA.CONFIG.JSON WHICH SKIP CACHING?*

Response: TLDR: Because no-store completely prevents caching, forcing full file downloads every time. Using it everywhere breaks ETag revalidation (304 Not Modified) and wastes bandwidth on normal non-manifest assets.

---

*User prompt: SO WHAT KIND OF ROUTES+ASSETS NEED ALL 3? WE ARE USING ANGULAR19 WITH WEBBACK AND ESBUILD, AND NX*

Response: TLDR: Only critical version manifests, entry html, and dynamic metadata need all three. Content-addressed (hashed) build output uses aggressive caching instead.

### **1\. Require All Three (no-cache, no-store, must-revalidate)**

> * **Service Worker Manifest:** /ngsw.json (Triggers app updates).  
> * **Service Worker Script:** /ngsw-worker.js, /ngsw-manifest.json, /safety-worker.js.  
> * **Application Entrypoint:** /index.html (Points to current bundle hashes).  
> * **Environment / Config Files:** /assets/config.json, /\*.env.json (Runtime configs).

### **2\. Require Single no-cache (Revalidate via ETag)**

> * **Unhashed Static Assets:** Images/icons without dynamic hashes (e.g., /favicon.ico, /assets/images/logo.png).  
> * **Localized Translation Files:** /assets/i18n/\*.json (If deployed without content hashes).

### **3\. Require max-age (Immutable / Cache Forever)**

> * **Hashed App Bundles (esbuild/Webpack output):** /\*.js, /\*.css (e.g., main.a1b2c3d4.js, styles.f6e5d4c3.css).  
  * *Header:* Cache-Control: public, max-age=31536000, immutable  
  * *Reason:* Angular/esbuild generates a unique hash on code changes, making old URLs immutable and safely cacheable forever.

---

*User prompt: GENERATE A SAMPLE AZURE SWA.CONFIG.JSON FOR THE ABOVE*

`Response: {`  
  `"routes": [`  
    `{`  
      `"route": "/ngsw.json",`  
      `"headers": {`  
        `"cache-control": "no-cache, no-store, must-revalidate"`  
      `}`  
    `},`  
    `{`  
      `"route": "/ngsw-worker.js",`  
      `"headers": {`  
        `"cache-control": "no-cache, no-store, must-revalidate"`  
      `}`  
    `},`  
    `{`  
      `"route": "/ngsw-manifest.json",`  
      `"headers": {`  
        `"cache-control": "no-cache, no-store, must-revalidate"`  
      `}`  
    `},`  
    `{`  
      `"route": "/index.html",`  
      `"headers": {`  
        `"cache-control": "no-cache, no-store, must-revalidate"`  
      `}`  
    `},`  
    `{`  
      `"route": "/assets/config.json",`  
      `"headers": {`  
        `"cache-control": "no-cache, no-store, must-revalidate"`  
      `}`  
    `},`  
    `{`  
      `"route": "/assets/*",`  
      `"headers": {`  
        `"cache-control": "no-cache"`  
      `}`  
    `},`  
    `{`  
      `"route": "/*.js",`  
      `"headers": {`  
        `"cache-control": "public, max-age=31536000, immutable"`  
      `}`  
    `},`  
    `{`  
      `"route": "/*.css",`  
      `"headers": {`  
        `"cache-control": "public, max-age=31536000, immutable"`  
      `}`  
    `}`  
  `],`  
  `"navigationFallback": {`  
    `"rewrite": "/index.html",`  
    `"exclude": ["/assets/*", "/*.{png,jpg,jpeg,gif,svg,ico,js,css,json}"]`  
  `}`  
`}`

---

*User prompt: WHAT DOES IMMUTABLE DO? IE HOW DOES IT AFFECT CACHE BEHAVIOR?*

Response: TLDR: immutable tells browsers the response body will never change. The browser won't send revalidation requests (conditional GET / If-None-Match) on page refreshes, serving it instantly from cache.

---

*User prompt: WHAT TAKES PRECEDENCE? ROUTE FOR "/\*.JS" OR "/ngsw-worker.js" ? IN THE EXAMPLE ABOVE*

Response: TLDR: /ngsw-worker.js takes precedence. Azure Static Web Apps evaluates rules sequentially from top to bottom, stopping at the first matching route.

---

*User prompt: DID U GET OVERALL CONTEXT OF MY PROBLEM STATEMENT: BASICALLY I AM GETTING A WSOD FOR MY WEBAPP..... AFD LOGS SHOW THAT CONTENT IS BEING CACHED (TCP\_HIT) WHICH PRE-SUPPOSES THAT AT LEAST ONE SUCCESSFUL 200, NON-ZERO BYTE RESPONSE WAS GENERATED EARLIER (TCP\_MISS) SO THAT WD MEAN THAT AT SOME POINT THE BLANK PAGE GOT STORED ON THE AFD CACHE... AM I MAKING SENSE SO FAR? Y/N*

Response: YES.

Your logic is sound regarding CDN mechanics: TCP\_HIT proves AFD previously cached a 200 OK response that it served as the WSOD.

However, in Angular SW architecture, there are **two distinct places** caching can cause a WSOD:

> 1. **AFD Caching a Blank Page (Server-Side):** AFD cached an empty or corrupted index.html (or critical js chunk) on a TCP\_MISS, then served that same empty payload to everyone from edge memory (TCP\_HIT).  
> 2. **Angular Service Worker Caching (Client-Side Memory):** AFD cached a stale ngsw.json. The client SW downloaded this stale manifest and tried to load hashed chunks (main.oldHash.js) that no longer existed on origin, causing an uncaught runtime JS error during boot — which manifests in the browser as a WSOD, even though AFD is returning TCP\_HIT for valid assets.

---

*User prompt: WHAT IS THE FIX FOR 2? ONLY THIS? { "route": "/ngsw.json", "headers": { "cache-control": "no-cache, no-store, must-revalidate" } },*

Response: TLDR: No. You must apply no-cache, no-store, must-revalidate to **all** Service Worker control files and index.html, plus handle orphan client caches.

### **1\. SWA Configuration (Server Header Rules)**

Include all SW manifests and the entry point in staticwebapp.config.json:

`{`  
  `"route": "/ngsw.json",`  
  `"headers": { "cache-control": "no-cache, no-store, must-revalidate" }`  
`},`  
`{`  
  `"route": "/ngsw-worker.js",`  
  `"headers": { "cache-control": "no-cache, no-store, must-revalidate" }`  
`},`  
`{`  
  `"route": "/ngsw-manifest.json",`  
  `"headers": { "cache-control": "no-cache, no-store, must-revalidate" }`  
`},`  
`{`  
  `"route": "/index.html",`  
  `"headers": { "cache-control": "no-cache, no-store, must-revalidate" }`  
`}`

### **2\. Application Logic (Client Self-Healing)**

If clients are already stuck with broken caches, server-side header changes won't fix browsers that aren't checking the server. Handle chunk load errors globally in Angular to unregister the Service Worker and force a hard re-fetch:

`// main.ts /ErrorHandler`  
`window.addEventListener('error', (event) => {`  
  `if (event.message?.includes('Loading chunk') || event.message?.includes('CSS chunk')) {`  
    `if (navigator.serviceWorker) {`  
      `navigator.serviceWorker.getRegistrations().then((registrations) => {`  
        `for (const registration of registrations) {`  
          `registration.unregister();`  
        `}`  
        `window.location.reload();`  
      `});`  
    `}`  
  `}`  
`});`

---

*User prompt: 2\. IS THIS SPECIFIC TO "CHUNKLOADERROR" HANDLING?*

Response: TLDR: Yes. It targets chunk-loading failures (such as ChunkLoadError or missing asset errors) caused when the Service Worker tries to fetch old JavaScript or CSS hashed files that no longer exist on the server.

---

*User prompt: WHY DOESN ANGULAR 19 EVEN NEED A NGSW IN THE FIRST PLACE?*

Response: TLDR: Angular 19 **does not** automatically include or require ngsw.json. It is only present if explicitly added via @angular/pwa or configured in angular.json for offline PWA support and client-side caching.

---

*User prompt: PRESENCE OF NGSW.JSON INDICATES THAT THIS WEBAPP IS CSR OR SSR?*

Response: TLDR: **CSR (Client-Side Rendering)**. Angular's Service Worker (ngsw.json) is designed for client-side PWAs to cache static browser assets (index.html, JS, CSS) and work offline. SSR bypasses SW-based app shell caching because pages are rendered dynamically on the server.

---

*User prompt: HOW CAN I TEST THIS LOCALLY ON MY PC? IE SETUP A LOCAL AFD LIKE SERVICE AND RUN WEBAPP LOCALLY... I NEED TO REPRODUCE, TRIAGE AND FIX LOCALLY*

Response: TLDR: You cannot run Azure Front Door locally, but you can simulate AFD caching and headers using **Nginx** or **Caddy** sitting in front of the **Azure Static Web Apps CLI (@azure/static-web-apps-cli)**.

### **Step 1: Serve App with Local SWA CLI**

Run your Angular build and start SWA CLI to enforce staticwebapp.config.json locally:

`# 1. Build Angular app`  
`npx nx build <app-name>`

`# 2. Run SWA CLI pointing to build folder and config`  
`npx @azure/static-web-apps-cli start ./dist/apps/<app-name> --config ./staticwebapp.config.json --port 4280`

### **Step 2: Simulate AFD CDN Layer with Nginx**

Create a local nginx.conf to proxy requests to localhost:4280 while caching responses locally (simulating AFD's edge cache).

nginx.conf:

`events {}`

`http {`  
    `# Define local proxy cache path`  
    `proxy_cache_path /tmp/nginx_cache levels=1:2 keys_zone=afd_cache:10m max_size=1g inactive=60m use_temp_path=off;`

    `server {`  
        `listen 8080;`

        `location / {`  
            `proxy_pass http://host.docker.internal:4280;`  
              
            `# Enable CDN Caching`  
            `proxy_cache afd_cache;`  
            `proxy_cache_key "$scheme$request_method$host$request_uri";`  
            `proxy_cache_valid 200 60m;`

            `# Ignore client Cache-Control headers if testing stale caching override`  
            `# proxy_ignore_headers Cache-Control;`

            `# Add Debug Header to track HIT/MISS like AFD`  
            `add_header X-Cache-Status $upstream_cache_status;`  
        `}`  
    `}`  
`}`

### **Step 3: Run Nginx via Docker**

`docker run --rm -p 8080:8080 -v $(pwd)/nginx.conf:/etc/nginx/nginx.conf:ro nginx:alpine`

### **Step 4: Reproduce the Issue locally**

> 1. Access http://localhost:8080 in your browser.  
> 2. Inspect Response Headers: Look for X-Cache-Status: MISS, then reload to see X-Cache-Status: HIT.  
> 3. Check ngsw.json cache behavior:  
>    `curl -I http://localhost:8080/ngsw.json`

> 4. Update a file, re-build, and observe if the browser gets stuck on the stale ngsw.json serving old JS chunk URLs (WSOD).

---

*User prompt: HOW CAN I REPRODUCE THE WSOD BLANK PAGE LOCALLY IN A DETERMINISTIC FASHION?*

Response: TLDR: Serve a stale ngsw.json pointing to non-existent JS chunk hashes using a simple local proxy, or manually inject a broken cache state into your browser's Cache Storage.

### **Method 1: Manual Browser Cache Injection (Fastest)**

> 1. **Build and Serve:** Run your app locally via npx swa start. Open http://localhost:4280 so the Service Worker installs.  
> 2. **Corrupt the Cache:** Open DevTools → **Application** tab → **Cache Storage**.  
> 3. **Delete modern JS chunks:** Find the ngsw:db:...:assets:app:cache bucket. Right-click and delete the main JS/CSS bundle entries (e.g., main.a1b2c3d4.js), simulating a deployment where old chunks were wiped from origin.  
> 4. **Break the Manifest:** Open **Application** → **Storage** → **IndexedDB** → ngsw:db → manifests. Change a JS hash/URL in the saved ngsw.json record to point to a non-existent file name like main.DEADBEEF.js.  
> 5. **Reproduce:** Uncheck "Bypass for network" in DevTools → **Service Workers**, then hard refresh (Cmd+Shift+R or Ctrl+F5). The SW serves index.html from cache, attempts to dynamically import main.DEADBEEF.js, fails, and triggers a WSOD.

### **Method 2: Scripted Stale Server Simulation (Deterministic)**

Use a lightweight Node/Express mock proxy in front of swa start to explicitly freeze ngsw.json across builds:

`// mock-afd.js`  
`const express = require('express');`  
`const { createProxyMiddleware } = require('http-proxy-middleware');`

`const app = express();`  
`let frozenNgsw = null;`

`// Intercept ngsw.json to simulate a stale CDN (AFD TCP_HIT)`  
`app.get('/ngsw.json', (req, res, next) => {`  
  `if (req.query.freeze === 'true' && !frozenNgsw) {`  
    `console.log('[AFD MOCK] Freezing ngsw.json snapshot...');`  
    `// Capture current version`  
  `}`  
  `if (frozenNgsw) {`  
    `console.log('[AFD MOCK] Serving STALE ngsw.json (TCP_HIT simulation)');`  
    `return res.header('Cache-Control', 'public, max-age=3600').send(frozenNgsw);`  
  `}`  
  `next();`  
`});`

`// Proxy everything else to SWA CLI`  
`app.use('/', createProxyMiddleware({ target: 'http://localhost:4280', changeOrigin: true }));`

`app.listen(8080, () => console.log('Mock AFD Proxy running on http://localhost:8080'));`

#### **Reproduction Steps:**

> 1. Start SWA CLI: npx @azure/static-web-apps-cli start ./dist/apps/\<app-name\> \--port 4280  
> 2. Start Proxy: node mock-afd.js  
> 3. Load http://localhost:8080 in Chrome to register SW v1.  
> 4. Freeze manifest: Save the current output of http://localhost:4280/ngsw.json into the frozenNgsw variable in mock-afd.js.  
> 5. Make a code change and rebuild the Angular app (generating new hash filenames like main.newHash.js and deleting old main.oldHash.js).  
> 6. Reload http://localhost:8080. The SW fetches the frozen ngsw.json (mocking AFD stale hit), thinks nothing changed, and requests deleted v1 assets → **WSOD reproduced**.

---

