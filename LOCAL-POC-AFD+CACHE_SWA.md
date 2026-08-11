# Local WSOD & Cache Triage Runbook

## 1. Setup Mock AFD (CDN Simulator)

### Option A: Express Proxy (Scripted Freezing)
Create `mock-afd.js` to manually freeze the cache state:
```javascript
const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const app = express();
let frozenNgsw = null;

app.get('/freeze', async (req, res) => {
  const fetch = (await import('node-fetch')).default;
  const response = await fetch('http://localhost:4280/ngsw.json');
  frozenNgsw = await response.text();
  res.send('Manifest frozen!');
});

app.get('/ngsw.json', (req, res, next) => {
  if (frozenNgsw) return res.header('Cache-Control', 'public, max-age=3600').send(frozenNgsw);
  next();
});

app.use('/', createProxyMiddleware({ target: 'http://localhost:4280', changeOrigin: true }));
app.listen(8080, () => console.log('Proxy on :8080. SWA on :4280.'));

```

### Option B (Optional): Nginx via Docker (Time-Based Caching)

Create `nginx.conf` to strictly cache all responses for 60 minutes:

```nginx
events {}
http {
    proxy_cache_path /tmp/nginx_cache levels=1:2 keys_zone=afd_cache:10m max_size=1g inactive=60m use_temp_path=off;
    server {
        listen 8080;
        location / {
            proxy_pass [http://host.docker.internal:4280](http://host.docker.internal:4280);
            proxy_cache afd_cache;
            proxy_cache_key "$scheme$request_method$host$request_uri";
            proxy_cache_valid 200 60m;
            add_header X-Cache-Status $upstream_cache_status;
        }
    }
}

```

Run: `docker run --rm -p 8080:8080 -v $(pwd)/nginx.conf:/etc/nginx/nginx.conf:ro nginx:alpine`

## 2. Reproduce WSOD Deterministically

1. **Build & Serve:**
`npx nx build <app-name>`
`npx @azure/static-web-apps-cli start ./dist/apps/<app-name> --port 4280`
2. **Start Proxy:** Run either the Node script or the Nginx Docker container.
3. **Initialize SW:** Open `http://localhost:8080` in Chrome.
4. **Lock Cache:**
* *Option A:* Open `http://localhost:8080/freeze` in a new tab.
* *Option B:* Cache is automatically locked for 60m by Nginx on first load.


5. **Simulate Deployment:** Modify a component in your Angular app, then re-run `npx nx build <app-name>`.
6. **Trigger WSOD:** Reload `http://localhost:8080`. The browser receives the stale `ngsw.json`, attempts to fetch deleted `.js` chunks, and fails silently (WSOD).

## 3. Apply the Fixes

### A. Server-Side Prevention (`staticwebapp.config.json`)

Force bypass of AFD and browser caching for critical entry points:

```json
{
  "routes": [
    { "route": "/ngsw*.json", "headers": { "cache-control": "no-cache, no-store, must-revalidate" } },
    { "route": "/ngsw-worker.js", "headers": { "cache-control": "no-cache, no-store, must-revalidate" } },
    { "route": "/index.html", "headers": { "cache-control": "no-cache, no-store, must-revalidate" } }
  ]
}

```

### B. Client-Side Self-Healing (`main.ts`)

Catch orphaned chunk requests and reset the Service Worker:

```typescript
window.addEventListener('error', (event) => {
  if (event.message?.includes('Loading chunk') || event.message?.includes('CSS chunk')) {
    if (navigator.serviceWorker) {
      navigator.serviceWorker.getRegistrations().then((registrations) => {
        registrations.forEach(reg => reg.unregister());
        window.location.reload();
      });
    }
  }
});

```

## 4. Validate Fix

1. Restart SWA CLI and your chosen proxy.
2. Clear browser cache/Storage completely.
3. Repeat Section 2 steps.
4. **Expected Result:** The `staticwebapp.config.json` headers prevent proxy caching of the manifest, and the `main.ts` fallback ensures recovery.
