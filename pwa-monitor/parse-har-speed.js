// parse-har-speed.js — run independently against any existing HAR file
const fs = require('fs');

const harPath = process.argv[2];
if (!harPath) {
  console.error('Usage: node parse-har-speed.js <path-to-har>');
  process.exit(1);
}

const har = JSON.parse(fs.readFileSync(harPath, 'utf-8'));

const speedEntries = har.log.entries
  .filter(e => e.response.bodySize > 0 && e.timings.receive > 0)
  .map(e => ({
    url: e.request.url,
    bytes: e.response.bodySize,
    ms: e.timings.receive,
    kbps: (e.response.bodySize * 8 / 1024) / (e.timings.receive / 1000),
  }));

console.log(JSON.stringify(speedEntries, null, 2));
