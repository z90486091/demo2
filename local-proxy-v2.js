import http from 'http';

const TARGET_API = 'https://opencode.ai/zen/v1';

http.createServer(async (req, res) => {
  const target = `${TARGET_API}${req.url}`;
  const body = ['GET', 'HEAD'].includes(req.method) 
    ? null 
    : await new Promise(r => {
        const c = [];
        req.on('data', d => c.push(d));
        req.on('end', () => r(Buffer.concat(c)));
      });

  try {
    console.log(`Routing directly to: ${target}`);
    const upstream = await fetch(target, {
      method: req.method,
      headers: { 
        'content-type': req.headers['content-type'],  
        'authorization': req.headers['authorization'],  
        'accept': req.headers['accept'] || '*/*',  
        'user-agent': req.headers['user-agent'] || 'Mozilla/5.0'
      },
      body,
      // signal: AbortSignal.timeout(15000)
    });

    res.writeHead(upstream.status, Object.fromEntries(upstream.headers));
    const reader = upstream.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      res.write(value);
    }
    return res.end();
  } catch (err) {
    console.error(`\n[FAIL]: ${err.message}`);
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'text/plain' });
      res.end(`Bad Gateway: ${err.message}`);
    }
  }
}).listen(7860, () => console.log('Local Proxy running on port 7860'));
