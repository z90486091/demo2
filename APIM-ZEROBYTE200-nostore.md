### In APIM > API > DESIGN > OUTBOUND, 

Insert this policy to force `no-store` for zero-byte responses

```xml
<outbound>
    <base />
    <choose>
        <when condition="@(context.Response.StatusCode == 200 && context.Response.Headers.GetValueOrDefault("Content-Length","") == "0")">
            <set-header name="Cache-Control" exists-action="override">
                <value>no-store</value>
            </set-header>
        </when>
    </choose>
</outbound>
```
