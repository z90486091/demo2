```diff
{
  "routes": [
    {
      "route": "/ngsw.json",
      "headers": {
-       "Cache-Control": "no-store"
+       "Cache-Control": "no-cache"
      }
    },
    {
      "route": "/index.html",
      "headers": {
+       "Cache-Control": "no-cache"
      }
    },
    {
      "route": "/*.js",
      "headers": {
+       "Cache-Control": "public, max-age=31536000, immutable"
      }
    },
    {
      "route": "/*.css",
      "headers": {
+       "Cache-Control": "public, max-age=31536000, immutable"
      }
    },
    {
      "route": "/assets/*",
      "headers": {
+       "Cache-Control": "public, max-age=31536000, immutable"
      }
    },
    {
      "route": "/manifest.webmanifest",
      "headers": {
+       "Cache-Control": "no-cache"
      }
    }
  ]
}
```

Rationale, by file class:

- `index.html`, `ngsw.json`, `manifest.webmanifest` — **never long-cache**. These are the entry points the SW/browser checks to detect a new deploy. `no-cache` (revalidate every time, not `no-store`) is the standard Angular SW guidance already discussed in this thread.
- `*.js`, `*.css` — esbuild/Angular CLI outputs these with **content hashes in the filename** (`main.a1b2c3.js`). A hashed filename can be cached forever safely — a new deploy produces a new filename, never overwriting the old one. `immutable` tells the browser to skip revalidation entirely, which is the actual performance win of content hashing.
- `assets/*` (images, fonts you own) — same logic, if these are also hashed by your build; if any are NOT hashed (e.g. a static logo referenced by fixed name), pull that one out into its own shorter-cache rule instead.

This is unrelated to the third-party zero-byte HAR finding — those are external domains' own headers, not something your `staticwebapp.config.json` can control either way.
