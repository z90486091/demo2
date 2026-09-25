# Azure App Service, JBoss EAP, JPA, and PostgreSQL Operations Guide

## Contents

1. [Count PostgreSQL connections](#count-postgresql-connections)
2. [Detect lock waits on PostgreSQL Flexible Server](#detect-lock-waits-on-postgresql-flexible-server)
3. [Understand cold starts with Always On](#understand-cold-starts-with-always-on)
4. [Detect JBoss EAP database connection-pool usage](#detect-jboss-eap-database-connection-pool-usage)
5. [Get App Service logs](#get-app-service-logs)
6. [Pre-warm Azure App Service](#pre-warm-azure-app-service)

---

## Count PostgreSQL Connections

If you only have Azure Portal access, you can view the overall PostgreSQL connection count without database credentials.

### Azure Portal

1. Open the Azure portal.
2. Open your **Azure Database for PostgreSQL Flexible Server**.
3. Select **Monitoring → Metrics**.
4. Select the `Active connections` metric.
5. Choose an aggregation:
   - `Maximum` to see the highest number during the selected period
   - `Average` to see the average
6. Select a short time range such as `Last 30 minutes`.

This shows connections reaching PostgreSQL from all clients. It does not identify exactly which connections came from a specific App Service.

### Connection count by application

The exact pool usage cannot be determined from Azure PostgreSQL metrics alone. For that, the JBoss EAP datasource pool must expose runtime statistics.

The approximate maximum number of connections is:

```text
maximum pool size × number of App Service instances
```

For example:

```text
4 App Service instances × 20 connections per pool = approximately 80 possible connections
```

---

## Detect Lock Waits on PostgreSQL Flexible Server

### Important limitation

The Azure Portal Metrics blade does not show the exact blocking process ID, SQL statement, or lock holder.

For precise real-time information, database access is normally required to query:

```sql
pg_stat_activity
pg_locks
```

If you do not have database access, use Azure monitoring and server logs.

### Flexible Server troubleshooting

1. Open the PostgreSQL Flexible Server.
2. Select **Help → Troubleshooting** or **Diagnose and solve problems**.
3. Review categories such as:
   - Locking and blocking
   - Waits
   - Long-running queries
   - Performance

The available views depend on the server configuration and enabled telemetry.

### Enable PostgreSQL lock logging

In the PostgreSQL Flexible Server:

1. Open **Settings → Server parameters**.
2. Find:

```text
log_lock_waits
```

3. Set it to:

```text
on
```

4. Save the change.

This records lock waits that exceed PostgreSQL's `deadlock_timeout` setting.

### Send logs to Log Analytics

1. Open the PostgreSQL Flexible Server.
2. Select **Diagnostic settings**.
3. Create or edit a diagnostic setting.
4. Send logs to a **Log Analytics workspace**.
5. Enable PostgreSQL server logs.
6. Save the setting.

Then open the workspace and select **Logs**.

Example query:

```kusto
AzureDiagnostics
| where TimeGenerated > ago(24h)
| where ResourceProvider == "MICROSOFT.DBFORPOSTGRESQL"
| where Category == "PostgreSQLLogs"
| where Message has_any ("lock", "waiting", "deadlock")
| order by TimeGenerated desc
```

Depending on the diagnostic configuration, the table may instead be:

```kusto
PGSQLServerLogs
| where TimeGenerated > ago(24h)
| where ErrorMessage has_any ("lock", "waiting", "deadlock")
| order by TimeGenerated desc
```

### Query Store waits

If Query Store is enabled, inspect wait information in the `PGSQLQueryStoreWaits` table:

```kusto
PGSQLQueryStoreWaits
| where TimeGenerated > ago(24h)
| where EventType has_any ("Lock", "LWLock")
    or Event has_any ("Lock", "transactionid", "relation")
| summarize waits = sum(Calls) by EventType, Event, QueryId
| order by waits desc
```

### Difference between lock waits and deadlocks

- **Lock wait:** A query is waiting for another transaction to release a lock.
- **Deadlock:** PostgreSQL detects a circular dependency and aborts one transaction.
- **Query Store waits:** Historical or sampled information; they may not show a lock happening at this exact moment.
- **`pg_stat_activity` and `pg_locks`:** The most precise real-time method, but they require database access.

---

## Understand Cold Starts with Always On

**Always On prevents idle unloading, but it does not prevent every type of cold start.**

Cold-start behavior can still occur after:

- Deployments
- Configuration changes
- App Service restarts
- Crashes
- Platform maintenance
- Scale-out events
- Scale-in followed by instance replacement
- Slot creation or startup
- Slow JBoss or JPA initialization

### Verify Always On

1. Open the App Service.
2. Go to **Configuration → General settings**.
3. Confirm:

```text
Always On = On
```

4. Select **Save**.

Also verify the setting on the specific deployment slot receiving traffic.

### Other checks

Review:

- **Scale up** to verify the pricing tier supports Always On
- **Scale out** to identify newly added or removed instances
- **Activity log** for deployments, restarts, and configuration changes
- **Diagnose and solve problems** for restart and availability information
- **Application Insights** for startup time and dependency delays

### JBoss-specific startup delays

A JBoss EAP cold start may include:

- JVM startup
- Class loading
- Spring or CDI initialization
- JPA persistence-unit initialization
- Entity scanning
- PostgreSQL datasource initialization
- Connection-pool creation
- Secret and configuration loading

Avoid expensive work during application startup whenever possible.

---

## Detect JBoss EAP Database Connection-Pool Usage

When using JPA on JBoss EAP, the connection pool belongs to the **JBoss EAP datasource**. Azure App Service does not expose its exact usage through the normal Azure Portal metrics.

### Enable datasource statistics

Replace `MyPostgresDS` with the JBoss datasource name:

```bash
/subsystem=datasources/data-source=MyPostgresDS:write-attribute(name=statistics-enabled,value=true)
```

### Read pool statistics

```bash
/subsystem=datasources/data-source=MyPostgresDS/statistics=pool:read-resource(include-runtime=true)
```

Important values include:

| Statistic | Meaning |
|---|---|
| `InUseCount` | Connections currently checked out by the application |
| `AvailableCount` | Idle connections currently available |
| `MaxUsedCount` | Highest simultaneous usage observed |
| `WaitCount` | Requests that had to wait for a connection |
| `MaxWaitCount` | Maximum number waiting simultaneously |
| `AverageBlockingTime` | Average time waiting for a connection |
| `TimedOut` | Connection acquisition timeouts |
| `CreatedCount` | Connections created |
| `DestroyedCount` | Connections destroyed |

### Managed domain command

For a managed domain, include the host and server:

```bash
/host=HOST_NAME/server=SERVER_NAME/subsystem=datasources/data-source=MyPostgresDS/statistics=pool:read-resource(include-runtime=true)
```

### JBoss management console

If available:

1. Open the JBoss management console, commonly on port `9990`.
2. Go to **Runtime**.
3. Select the server.
4. Open **Subsystems → Datasources**.
5. Select the PostgreSQL datasource.
6. Open or enable pool statistics.

### Signs of pool exhaustion

Pool pressure is likely if:

```text
InUseCount is close to the configured max-pool-size
WaitCount is increasing
AverageBlockingTime is increasing
TimedOut is greater than 0
```

### Common JBoss pool errors

Search JBoss logs for:

```text
IJ000453: Unable to get managed connection
IJ000655: No managed connections available
javax.resource.ResourceException
WFLYJCA
timeout waiting for connection
connection is not available
```

### Datasource configuration

A typical datasource configuration contains:

```xml
<pool>
    <min-pool-size>5</min-pool-size>
    <max-pool-size>50</max-pool-size>
</pool>
```

The JPA persistence unit should reference the JBoss datasource:

```xml
<jta-data-source>java:/jdbc/MyPostgresDS</jta-data-source>
```

The pool size is configured in JBoss EAP, not normally in `persistence.xml`.

---

## Get App Service Logs

### Live logs

1. Open **Azure Portal → App Services**.
2. Select the App Service.
3. Select **Monitoring → Log stream**.
4. Reproduce the issue or wait for the next request.

For JBoss EAP, search for:

```text
IJ000453
IJ000655
WFLYJCA
ResourceException
timeout waiting for connection
connection is not available
```

### Enable application logging

Go to:

**App Service → Monitoring → App Service logs**

Enable the available options:

- Application logging
- Application logging to filesystem
- Web server logging
- Detailed error messages

Select **Save**, then return to **Log stream**.

### Custom-container logging

For a Linux or custom-container App Service, JBoss logs must be sent to standard output or standard error to appear in App Service **Log stream**.

If JBoss writes only to a file inside the container, Azure may not display that file in the live stream. Configure the container or JBoss logging so that `server.log` is written to stdout/stderr or forwarded to persistent storage.

### Download logs

For a Linux App Service, logs may be accessed through:

```text
https://<app-name>.scm.azurewebsites.net/api/logs/docker
```

You can also use:

**App Service → Development Tools → Advanced Tools → Go → Debug console**

Common locations include:

```text
/home/LogFiles/
/home/LogFiles/Application/
/home/LogFiles/docker/
/home/site/wwwroot/
```

For a custom JBoss container, the JBoss log may instead be in the container's configured log directory.

### Send logs to Log Analytics

1. Open the App Service.
2. Select **Diagnostic settings**.
3. Select **Add diagnostic setting**.
4. Send logs to a Log Analytics workspace.
5. Enable the available App Service log categories.
6. Save the setting.
7. Open **Logs** in the workspace.

Example query:

```kusto
AppServiceConsoleLogs
| where TimeGenerated > ago(24h)
| where ResultDescription has_any (
    "IJ000453",
    "IJ000655",
    "WFLYJCA",
    "ResourceException",
    "connection",
    "pool",
    "timeout"
)
| project TimeGenerated, AppName, InstanceId, ResultDescription
| order by TimeGenerated desc
```

Another possible table is:

```kusto
AppServicePlatformLogs
| where TimeGenerated > ago(24h)
| where Message has_any ("JBoss", "WFLY", "IJ000", "connection", "pool")
| order by TimeGenerated desc
```

### Application Insights

If Application Insights is enabled:

1. Open **App Service → Application Insights**.
2. Select **Failures → Exceptions**.
3. Search for:

```text
ResourceException
IJ000453
IJ000655
timeout
connection pool
Could not obtain connection
```

Useful information to correlate includes:

- App Service instance ID
- Request duration
- PostgreSQL dependency duration
- JBoss startup messages
- Connection acquisition errors

---

## Pre-Warm Azure App Service

The recommended setup is:

```text
Always On: On
Minimum instances: 2 or more
Deployment method: staging slot
Warm-up path: /health/warmup
Health Check path: /health/ready
Warm-up action: initialize JBoss/JPA and test one database connection
Deployment process: warm staging, then swap
```

### Enable Always On

1. Open the App Service.
2. Go to **Configuration → General settings**.
3. Set **Always On** to **On**.
4. Select **Save**.

### Create a warm-up endpoint

Create a lightweight endpoint such as:

```text
GET /health/warmup
```

It should:

- Load the application context
- Verify required configuration and secrets
- Initialize the JPA datasource
- Optionally obtain and release one PostgreSQL connection
- Return HTTP `200` only when the application is ready
- Avoid expensive queries and migrations

Do not run database migrations or heavy work in the warm-up endpoint.

### Create and warm a deployment slot

1. Open **App Service → Deployment slots**.
2. Create a `staging` slot.
3. Deploy the new JBoss application to staging.
4. Enable **Always On** for the staging slot.
5. Call the warm-up endpoint:

```text
https://<app-name>-staging.azurewebsites.net/health/warmup
```

6. Confirm that it returns HTTP `200`.
7. Review logs and Application Insights.
8. Swap staging into production.

### Configure swap warm-up

Add these application settings under:

**App Service → Configuration → Application settings**

```text
WEBSITE_SWAP_WARMUP_PING_PATH=/health/warmup
WEBSITE_SWAP_WARMUP_PING_STATUSES=200
```

If the app uses a deployment slot, configure the settings on the relevant slot as well.

### Health Check

Configure:

**App Service → Monitoring → Health check**

Use a fast readiness endpoint such as:

```text
/health/ready
```

The Health Check endpoint should:

- Return quickly
- Verify essential application readiness
- Avoid expensive database queries
- Return a non-success status if the application cannot serve requests

Health Check helps App Service identify unhealthy instances, but it does not fully replace warm-up logic.

### Warm newly scaled instances

When App Service adds an instance, JBoss and the JPA pool must initialize on that instance. To reduce impact:

- Keep at least two production instances
- Avoid aggressive autoscale rules
- Use deployment slots
- Keep startup work minimal
- Monitor JBoss initialization time
- Use a readiness endpoint
- Keep database connection-pool limits appropriate for the number of instances

### External periodic warm-up

An Azure Function, Logic App, automation job, or availability test can periodically call:

```text
https://<app-name>.azurewebsites.net/health/warmup
```

This may reduce idle-related startup behavior, but it does not guarantee that every App Service instance is warmed. Deployment-slot warm-up is more reliable for releases.

### Verify warm-up

Use:

- **App Service → Log stream**
- **Application Insights**
- JBoss `server.log`
- PostgreSQL dependency telemetry

Look for:

```text
JPA initialization completed
Datasource initialized
PostgreSQL connection acquired
HTTP 200 from /health/warmup
```

Also check for:

```text
IJ000453
IJ000655
ResourceException
timeout waiting for connection
```

---

## Practical Troubleshooting Sequence

When users report slow first requests or database connection failures:

1. Check **App Service → Log stream**.
2. Check for JBoss pool errors such as `IJ000453` and `IJ000655`.
3. Check **Application Insights** request and dependency duration.
4. Check PostgreSQL **Active connections** in Azure Metrics.
5. Check the JBoss datasource pool using the management console or CLI.
6. Check whether the App Service recently restarted or scaled.
7. Confirm **Always On** is enabled for the active slot.
8. Confirm the warm-up endpoint returns HTTP `200`.
9. Warm the staging slot before deployment.
10. Compare the JBoss pool maximum with:

```text
maximum pool size × number of App Service instances
```

Do not increase the JBoss pool size without checking the PostgreSQL server connection limit and the number of App Service instances.
