# Legacy AppService TLS 1.2 to TLS 1.3 Bridge Solutions

## Requirements
* **Source:** Legacy Java App Service (Oracle WebLogic, EOL JRE) restricted to TLS 1.2.
* **Destination:** Third-party API requiring TLS 1.3.
* **Goal:** Bridge the connection without modifying the legacy JRE.

## Solution Options
1. **Azure API Management (APIM):** No-code, managed API gateway handling TLS termination.
2. **Azure Functions (AFA):** Cheap, serverless middleware (Python/Node.js) to relay the payload. 
3. **Dedicated Proxy Container:** NGINX or Envoy in Azure Container Apps to tunnel traffic.

## Final Solution: Azure Functions Proxy

### Node.js (v4 Model)
```javascript
const { app } = require('@azure/functions');

app.http('proxyToModernApi', {
    methods: ['GET', 'POST', 'PUT', 'DELETE'],
    authLevel: 'function',
    handler: async (request, context) => {
        const targetUrl = '[https://modern-tls13-endpoint.com/api](https://modern-tls13-endpoint.com/api)'; 
        let body;
        if (request.method !== 'GET' && request.method !== 'HEAD') {
            body = await request.arrayBuffer(); 
        }
        try {
            const response = await fetch(targetUrl, {
                method: request.method,
                headers: {
                    'Content-Type': request.headers.get('content-type') || 'application/json',
                    'Authorization': request.headers.get('authorization') || ''
                },
                body: body
            });
            return {
                status: response.status,
                body: await response.text(),
                headers: { 'Content-Type': response.headers.get('content-type') }
            };
        } catch (error) {
            return { status: 500, body: "Error connecting" };
        }
    }
});

import azure.functions as func
import requests

app = func.FunctionApp()

@app.route(route="proxy", auth_level=func.AuthLevel.FUNCTION)
def proxy(req: func.HttpRequest) -> func.HttpResponse:
    target_url = "[https://modern-tls13-endpoint.com/api](https://modern-tls13-endpoint.com/api)"
    headers = {k: v for k, v in req.headers.items() if k.lower() != 'host'}
    
    try:
        resp = requests.request(
            method=req.method,
            url=target_url,
            headers=headers,
            data=req.get_body(),
            timeout=15
        )
        return func.HttpResponse(
            body=resp.content,
            status_code=resp.status_code,
            mimetype=resp.headers.get('Content-Type', 'application/json')
        )
    except Exception:
        return func.HttpResponse("Error connecting", status_code=500)


## Java Legacy Client (TLS 1.2 PoC)
```java
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import java.net.URL;
import java.io.BufferedReader;
import java.io.InputStreamReader;

public class Tls12Client {
    public static void main(String[] args) throws Exception {
        // Force TLS 1.2
        SSLContext sslContext = SSLContext.getInstance("TLSv1.2");
        sslContext.init(null, null, new java.security.SecureRandom());
        SSLContext.setDefault(sslContext);

        URL url = new URL("https://<your-function-app>.azurewebsites.net/api/proxy");
        HttpsURLConnection conn = (HttpsURLConnection) url.openConnection();
        conn.setRequestMethod("GET");
        conn.setRequestProperty("x-functions-key", "<your-function-key>");

        BufferedReader in = new BufferedReader(new InputStreamReader(conn.getInputStream()));
        String line;
        while ((line = in.readLine()) != null) {
            System.out.println(line);
        }
        in.close();
    }
}
