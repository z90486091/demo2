import http from 'http';
import https from 'https';
import { Transform } from 'stream';

const TARGET_API = 'https://opencode.ai/zen/v1';

http.createServer((req, res) => {
  const target = `${TARGET_API}${req.url}`;
  const start = Date.now();
  
  const headers = { ...req.headers };
  delete headers.host;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000);

  console.log(`\n[REQ] ${req.method} -> ${target}`);
  
  const upstreamReq = https.request(target, {
    method: req.method,
    headers,
    signal: controller.signal
  }, (upstreamRes) => {
    clearTimeout(timeoutId);
    const duration = Date.now() - start;

    if (upstreamRes.statusCode >= 500) {
      console.error(`[OUTAGE] OpenCodeAI returned HTTP ${upstreamRes.statusCode} (Server Error)`);
    } else {
      console.log(`[RES] Status: ${upstreamRes.statusCode} | Time: ${duration}ms`);
    }

    const respHeaders = { ...upstreamRes.headers };
    delete respHeaders['content-length'];
    res.writeHead(upstreamRes.statusCode, respHeaders);

    let buffer = '';
    const metricTracker = new Transform({
      transform(chunk, encoding, callback) {
        buffer += chunk.toString();
        let lineBreak;
        while ((lineBreak = buffer.indexOf('\n')) !== -1) {
          const line = buffer.substring(0, lineBreak).trim();
          buffer = buffer.substring(lineBreak + 1);
          if (line.startsWith('data:')) {
            const strData = line.replace(/^data:\s*/, '');
            if (strData !== '[DONE]') {
              try {
                const parsed = JSON.parse(strData);
                if (parsed.usage) {
                  const { prompt_tokens, completion_tokens, total_tokens } = parsed.usage;
                  console.log(`[TOKENS] Prompt: ${prompt_tokens} | Completion: ${completion_tokens} | Total: ${total_tokens}`);
                }
              } catch {}
            }
          }
        }
        callback(null, chunk);
      }
    });

    upstreamRes.pipe(metricTracker).pipe(res);
  });

  upstreamReq.on('error', (err) => {
    clearTimeout(timeoutId);
    
    if (err.name === 'AbortError') {
      console.error(`[OUTAGE] OpenCodeAI timed out after 30 seconds.`);
    } else {
      console.error(`[OUTAGE] OpenCodeAI network connection failed: ${err.message}`);
    }

    if (!res.headersSent) {
      res.writeHead(504, { 'Content-Type': 'text/plain' });
      res.end(`Gateway Error: OpenCodeAI is unreachable.`);
    }
  });

  req.pipe(upstreamReq);
}).listen(7860, () => console.log('Diagnostic Proxy running on port 7860'));
