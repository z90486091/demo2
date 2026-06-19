import http from 'http';
import { Readable } from 'stream';
import { Agent } from 'undici';

const TARGET_API = process.env.TARGET_API || 'https://opencode.ai/zen/v1';
const PORT = Number(process.env.PORT || 7860);

// native fetch() ignores the node-style `agent` option entirely.
// the correct way to control pooling is `dispatcher`, passed an undici.Agent.
const dispatcher = new Agent({ keepAliveTimeout: 30000, connections: 256 });

http.createServer(async (req, res) => {
  req.socket.setNoDelay(true);
  res.socket.setNoDelay(true);

  const target = `${TARGET_API}${req.url}`;
  const headers = { ...req.headers };
  delete headers.host;
  const body = ['GET', 'HEAD'].includes(req.method) ? null : req;

  const controller = new AbortController();
  let timeoutId = setTimeout(() => controller.abort(), 30000);
  const bumpTimeout = () => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => controller.abort(), 30000);
  };

  try {
    const start = Date.now()
    console.log(`[REQ] ${new Date().toISOString()}: ${req.method} -> ${target}`);
    const upstream = await fetch(target, {
      method: req.method,
      headers,
      body,
      duplex: body ? 'half' : undefined,
      dispatcher,
      signal: controller.signal
    });

    const duration = Date.now() - start;
    if (upstream.status >= 500) {
      console.error(`[OUTAGE] upstream returned HTTP ${upstream.status} (Server Error)`);
    } else {
      console.log(`[RES] Status: ${upstream.status} | Time: ${duration}ms`);
    }

    const respHeaders = Object.fromEntries(upstream.headers);
    delete respHeaders['content-length'];
    delete respHeaders['content-encoding'];
    delete respHeaders['transfer-encoding'];
    res.writeHead(upstream.status, respHeaders);

    if (upstream.body) {
      let buf = '';
      const tokenRe = /"prompt_tokens":(\d+).*?"completion_tokens":(\d+).*?"total_tokens":(\d+)/;
      const node = Readable.fromWeb(upstream.body);

      node.on('data', chunk => {
        bumpTimeout();
        res.write(chunk);
        buf += chunk;
        const m = tokenRe.exec(buf);
        if (m) { 
          console.log(`[TOKENS] Prompt: ${m[1]} | Completion: ${m[2]} | Total: ${m[3]}`);
          buf = ''; 
        }
        else if (buf.length > 2000) { buf = buf.slice(-500); }
      });

      node.on('end', () => { clearTimeout(timeoutId); res.end(); });
      node.on('error', () => { 
        clearTimeout(timeoutId); 
        console.error(`[OUTAGE] Stream error: ${err.message}`);
        res.end(); 
      });
    } else {
      clearTimeout(timeoutId);
      res.end();
    }
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      console.error(`[OUTAGE] Upstream timed out (30s idle).`);
    } else {
      console.error(`[OUTAGE] Network connection failed: ${err.message}`);
    }
    if (!res.headersSent) {
      res.writeHead(504, { 'Content-Type': 'text/plain' });
      res.end('Gateway Error: OpenCodeAI is unreachable.');
    }
  }
}).listen(PORT, () => console.log(`[proxy-v4-corrected] listening on ${PORT} -> ${TARGET_API}`));
