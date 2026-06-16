// proxy.js
import http from 'http';
import fetch from 'node-fetch';
import { HttpsProxyAgent } from 'https-proxy-agent';
import Proxifly from 'proxifly';

const proxifly = new Proxifly();

let agent = null;

async function refreshProxy() {
  const p = await proxifly.getProxy({ protocol: 'http', anonymity: 'elite', https: true, quantity: 1, format: 'json' });
  agent = new HttpsProxyAgent(`http://${p.ip}:${p.port}`);
  console.log('Using proxy:', p.ip, p.port);
}

await refreshProxy();
setInterval(refreshProxy, 5 * 60 * 1000); // rotate every 5 min

http.createServer(async (req, res) => {
  const target = `https://opencode.ai/zen/v1${req.url}`;
  const body = ['GET','HEAD'].includes(req.method) ? null : await new Promise(r => { const c = []; req.on('data', d => c.push(d)); req.on('end', () => r(Buffer.concat(c))); });

  const upstream = await fetch(target, {
    method: req.method,
    headers: { ...req.headers, host: 'opencode.ai' },
    body,
    agent,
  });

  res.writeHead(upstream.status, Object.fromEntries(upstream.headers));
  upstream.body.pipe(res);
}).listen(7860);
