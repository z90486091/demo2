import http from 'http';
import { Readable, Transform } from 'stream';

const TARGET_API = 'https://opencode.ai/zen/v1';

http.createServer(async (req, res) => {
  const target = `${TARGET_API}${req.url}`;
  const start = Date.now();
  
  const headers = { ...req.headers };
  delete headers.host;

  const body = ['GET', 'HEAD'].includes(req.method) 
    ? null 
    : await new Promise(r => {
        const c = [];
        req.on('data', d => c.push(d));
        req.on('end', () => r(Buffer.concat(c)));
      });

  // Setup a 10-second timeout to prevent infinite hanging
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000);

  try {
    console.log(`\n[REQ] ${req.method} -> ${target}`);
    
    const upstream = await fetch(target, {
      method: req.method,
      headers,
      body,
      duplex: body ? 'half' : undefined,
      signal: controller.signal
    });

    clearTimeout(timeoutId);
    const duration = Date.now() - start;

    // Check if OpenCodeAI returned a server error code
    if (upstream.status >= 500) {
      console.error(`[OUTAGE] OpenCodeAI returned HTTP ${upstream.status} (Server Error)`);
    } else {
      console.log(`[RES] Status: ${upstream.status} | Time: ${duration}ms`);
    }

    const respHeaders = Object.fromEntries(upstream.headers);
    delete respHeaders['content-length'];
    res.writeHead(upstream.status, respHeaders);

    if (upstream.body) {
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
              if (strData === '[DONE]') continue;
              try {
                const parsed = JSON.parse(strData);
                if (parsed.usage) {
                  const { prompt_tokens, completion_tokens, total_tokens } = parsed.usage;
                  console.log(`[TOKENS] Prompt: ${prompt_tokens} | Completion: ${completion_tokens} | Total: ${total_tokens}`);
                }
              } catch {}
            }
          }
          callback(null, chunk);
        }
      });
      Readable.fromWeb(upstream.body).pipe(metricTracker).pipe(res);
    } else {
      res.end();
    }
  } catch (err) {
    clearTimeout(timeoutId);
    
    // Distinguish between timeout and network routing failures
    if (err.name === 'AbortError') {
      console.error(`[OUTAGE] OpenCodeAI timed out after 10 seconds.`);
    } else {
      console.error(`[OUTAGE] OpenCodeAI network connection failed: ${err.message}`);
    }

    if (!res.headersSent) {
      res.writeHead(504, { 'Content-Type': 'text/plain' });
      res.end(`Gateway Error: OpenCodeAI is unreachable.`);
    }
  }
}).listen(7860, () => console.log('Diagnostic Proxy running on port 7860'));
