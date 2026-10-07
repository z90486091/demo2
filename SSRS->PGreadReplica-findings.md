# Runbook: SSRS `RSPROCESSINGABORTED` / PG `40001` Recovery Conflict on Azure PG Flexible Replica

## 0. The error in brief

- Error: `ERROR [40001]: canceling statement due to conflict with recovery`
- Detail: `User query might have needed to see row versions that must be removed`
- Meaning:
  - Primary vacuum or cleanup removed old row versions (dead tuples).
  - Replica must replay that WAL to stay consistent.
  - SSRS query on the replica still needed those old versions (its snapshot).
  - Replay waits up to `max_standby_streaming_delay` (default 30s), then cancels the query.
- SSRS (`RSPROCESSINGABORTED`, `RSERROREXECUTINGCOMMAND`) is only the messenger.
- Dataset `PG_EVENT` is the SSRS label, not a PG object. Match on tables or columns in its SQL.
- No data corruption. The replica is behaving as designed.

## 1. Prerequisites (do once)

- [ ] Diagnostic settings on BOTH primary and replica send to the same Log Analytics workspace:
  - `PostgreSQLLogs` (server logs)
  - `PostgreSQLFlexSessions` (session snapshots, for step 8)
  - `AllMetrics`
- [ ] Confirm which table mode you use:
  ```kusto
  PGSQLServerLogs | getschema
  ```
  - If this errors or is empty, you are in legacy mode. Use `AzureDiagnostics`:
    - `Category == "PostgreSQLLogs"`
    - `message_s` instead of `Message`
    - `LogicalServerName_s` instead of `LogicalServerName`
- [ ] Server parameters that make the later steps possible (check, then set if needed):
  - Replica: `log_min_duration_statement` = `5000` (or `0` briefly) so slow queries appear in logs
  - Primary: `log_autovacuum_min_duration` = `0` so autovacuum runs appear in logs
  - Replica: `log_min_messages` at default or higher is fine; the cancel is logged at ERROR
- [ ] Replace placeholders in every query:
  - `<replica-server-name>`
  - `<primary-server-name>`
  - `<table_or_unique_text_from_PG_EVENT_query>`
  - `<rg>`

---

## Step 1: Confirm the failures and find their time pattern

### Run (hourly trend)

```kusto
let replica = "<replica-server-name>";
PGSQLServerLogs
| where TimeGenerated > ago(14d)
| where LogicalServerName =~ replica
| where Message has "conflict with recovery"
| summarize Cancels = count() by bin(TimeGenerated, 1h)
| render timechart
```

### Run (hour-of-day / day-of-week pattern)

```kusto
let replica = "<replica-server-name>";
PGSQLServerLogs
| where TimeGenerated > ago(14d)
| where LogicalServerName =~ replica
| where Message has "conflict with recovery"
| summarize Cancels = count() by HourOfDay = hourofday(TimeGenerated), DayOfWeek = dayofweek(TimeGenerated)
| order by Cancels desc
```

### Look for

- Zero rows:
  - Cancels are not logged here, or logs go to another workspace or server name.
  - Fix the prerequisites before continuing.
- Spikes at fixed hours or days.
- Spread evenly across the day.
- Note the exact timestamps of the SSRS failures you already know about and check they appear.

### Infer

- Fixed-time spikes:
  - Likely tied to SSRS schedules or subscriptions.
  - Or tied to a primary batch job, ETL, or maintenance window.
  - Carry the times into steps 4, 5 and 6.
- Even spread:
  - Likely continuous write churn on the primary plus generally long queries.
  - Focus on steps 3, 4 and 5.
- Zero rows but SSRS still fails:
  - Check `PGSQLServerLogs` retention and the error level filter.
  - Search plain `Message has "40001"`.

---

## Step 2: Replica lag around the failures

### Run

```kusto
let replica = "<replica-server-name>";
AzureMetrics
| where TimeGenerated > ago(14d)
| where ResourceId has replica
| where MetricName == "physical_replication_delay_in_seconds"
| summarize AvgLag = avg(Average), MaxLag = max(Maximum) by bin(TimeGenerated, 5m)
| render timechart
```

### Look for

- Lag peaks that line up with the cancel spikes from step 1.
- Sustained lag that grows while a long query runs, then drops after the cancel.
- Flat near-zero lag even during cancels.

### Infer

- Lag climbs, then drops right after a cancel:
  - Replay was stalled waiting on a long query.
  - After the delay limit, replay cancelled the query and caught up.
  - Confirms the `max_standby_streaming_delay` mechanism.
- Lag already high before the query started:
  - Replica is under-resourced or the primary write rate is too high.
  - Fix is capacity or write volume, not only parameters.
- Flat near-zero lag:
  - Conflicts are short and sharp (small `max_standby_streaming_delay` or tiny cleanup records).
  - Still consistent with the same root cause.

---

## Step 3: Current and historical standby parameter values

- KQL cannot read live settings. It only sees changes.

### Run (live values, CLI)

```bash
az postgres flexible-server parameter show -g <rg> --server-name <replica> --name max_standby_streaming_delay
az postgres flexible-server parameter show -g <rg> --server-name <replica> --name hot_standby_feedback
az postgres flexible-server parameter show -g <rg> --server-name <primary> --name hot_standby_feedback
```

### Or run on the replica (psql)

```sql
SHOW max_standby_streaming_delay;
SHOW max_standby_archive_delay;
SHOW hot_standby_feedback;
```

### Run (who changed what, KQL)

```kusto
AzureActivity
| where TimeGenerated > ago(90d)
| where OperationNameValue =~ "MICROSOFT.DBFORPOSTGRESQL/FLEXIBLESERVERS/CONFIGURATIONS/WRITE"
| project TimeGenerated, Caller, ResourceId, ActivityStatusValue, Properties
| order by TimeGenerated desc
```

```kusto
PGSQLServerLogs
| where TimeGenerated > ago(90d)
| where Message has_any ("max_standby_streaming_delay", "max_standby_archive_delay", "hot_standby_feedback")
| project TimeGenerated, LogicalServerName, Message
| order by TimeGenerated desc
```

### Look for

- `max_standby_streaming_delay`:
  - Default is 30000 ms (30s).
  - Compare with the P95 and Max query durations from step 4.
- `hot_standby_feedback`: `on` or `off`.
- A recent parameter change that coincides with the start of the failures.

### Infer

- Delay value shorter than typical `PG_EVENT` runtime:
  - Direct cause. Any overlapping cleanup record will cancel the query.
- `hot_standby_feedback = off`:
  - Primary does not know the replica needs old rows, so vacuum removes them freely.
  - This is the usual setting that makes these cancels frequent.
- `hot_standby_feedback = on` and cancels still happen:
  - Cancels are from other conflict types (see step 7) or from replica restarts, failovers or lock conflicts.
  - Check the conflict breakdown in step 7.
- Recent change by a named caller:
  - Correlate the change time with step 1 trends. Roll back if it started the problem.

---

## Step 4: How long does the `PG_EVENT` query run?

### Run

```kusto
let replica = "<replica-server-name>";
PGSQLServerLogs
| where TimeGenerated > ago(14d)
| where LogicalServerName =~ replica
| where Message startswith "duration:"
| where Message has "<table_or_unique_text_from_PG_EVENT_query>"
| extend DurationSec = todouble(extract(@"duration: ([\d\.]+) ms", 1, Message)) / 1000.0
| summarize Runs = count(), P50 = percentile(DurationSec, 50), P95 = percentile(DurationSec, 95), Max = max(DurationSec) by bin(TimeGenerated, 1d)
```

### Look for

- `P50`, `P95` and `Max` per day.
- Compare each against `max_standby_streaming_delay` from step 3.
- Days where `Max` or `P95` jumps.
- Zero rows:
  - `log_min_duration_statement` is too high or unset, or the match text is wrong.
  - Cancelled queries are not logged as `duration:` lines, so the failed runs may be missing. Judge from the successful ones.

### Infer

- `P50` or `P95` above the delay (e.g. > 30s):
  - Query is inherently too long for the replica settings.
  - Tune the query or raise the delay.
- `P50` short but `Max` long:
  - Intermittent slow runs (parameter-dependent plans, cold cache, bloat, concurrent load).
  - Check the plan for the slow parameter values.
- Duration rising over days:
  - Table growth or bloat or stale statistics.
  - Check `pg_stat_user_tables` for `n_dead_tup` and `last_autovacuum`, and run `ANALYZE`.

---

## Step 5: Primary autovacuum activity vs. cancellations

### Run (what vacuum is cleaning, per table)

```kusto
let primary = "<primary-server-name>";
PGSQLServerLogs
| where TimeGenerated > ago(14d)
| where LogicalServerName =~ primary
| where Message startswith "automatic vacuum of table"
| extend Table = extract(@'table "([^"]+)"', 1, Message),
         Removed = toint(extract(@"tuples: (\d+) removed", 1, Message))
| summarize Vacuums = count(), TuplesRemoved = sum(Removed) by Table, bin(TimeGenerated, 1h)
| order by TuplesRemoved desc
```

### Run (overlay vacuums and cancels)

```kusto
let primary = "<primary-server-name>";
let replica = "<replica-server-name>";
let vac = PGSQLServerLogs
    | where TimeGenerated > ago(7d) and LogicalServerName =~ primary
    | where Message startswith "automatic vacuum of table"
    | summarize Vacuums = count() by bin(TimeGenerated, 15m);
let cancels = PGSQLServerLogs
    | where TimeGenerated > ago(7d) and LogicalServerName =~ replica
    | where Message has "conflict with recovery"
    | summarize Cancels = count() by bin(TimeGenerated, 15m);
vac
| join kind=fullouter cancels on TimeGenerated
| project TimeGenerated = coalesce(TimeGenerated, TimeGenerated1), Vacuums = coalesce(Vacuums, 0), Cancels = coalesce(Cancels, 0)
| render timechart
```

### Look for

- Which tables have the highest `TuplesRemoved`.
- Whether those tables are the ones the `PG_EVENT` query reads.
- Whether cancels follow vacuum spikes within the same or the previous 15-minute bin.

### Infer

- Cancels follow vacuums on the same tables the report reads:
  - Classic snapshot conflict. Confirmed cause.
  - Fix options: `hot_standby_feedback = on`, a longer delay, or a shorter query.
- Heavy vacuum on high-churn tables (UPDATE/DELETE heavy):
  - Source of the cleanup records.
  - Consider reducing churn, or tuning per-table autovacuum so cleanup runs in smaller, more frequent batches.
- Cancels with no matching vacuum:
  - Look at other conflict types in step 7, or at replica lag in step 2.

---

## Step 6: Concurrent SSRS sessions on the replica

### Run

```kusto
PGSQLPgStatActivitySessions
| where TimeGenerated > ago(7d)
| where LogicalServerName =~ "<replica-server-name>"
| where State == "active"
| summarize ActiveSessions = dcount(Pid) by bin(TimeGenerated, 5m), ApplicationName
| render timechart
```

- Table and column names vary by setup. Check with `PGSQLPgStatActivitySessions | getschema`.

### Look for

- Which `ApplicationName` dominates (SSRS often shows as `Npgsql` or the ODBC driver name).
- Peaks in active sessions that line up with step 1 spikes.
- Sessions that stay active for a long time (check `query_start` or `xact_start` columns if present).

### Infer

- Many concurrent report sessions during cancels:
  - More overlapping snapshots means more chance of a conflict.
  - Stagger SSRS schedules or limit concurrency.
- One long-lived session during each cancel:
  - Single heavy query is the culprit. Tune it (step 4).
- Non-SSRS applications also active:
  - Another workload may be the long reader. Do not assume it is SSRS only.

---

## Step 7: Confirm the exact conflict type (run on the replica)

- This is the definitive check. KQL cannot replace it.

### Run (psql on the replica)

```sql
SELECT datname, confl_snapshot, confl_lock, confl_bufferpin, confl_deadlock, confl_tablespace
FROM pg_stat_database_conflicts
WHERE datname = current_database();
```

- Run it twice, a few hours apart (or before and after a known failure), and compare the counters.
- Counters reset on restart or failover, so note the server start time:
  ```sql
  SELECT pg_postmaster_start_time();
  ```

### Look for

- `confl_snapshot` increasing.
- Other columns increasing instead.

### Infer

- `confl_snapshot` rising:
  - Matches your error message exactly (old row versions removed).
  - Fixes: `hot_standby_feedback`, longer delay, shorter query.
- `confl_lock` rising:
  - Primary took an `ACCESS EXCLUSIVE` lock (DDL, `TRUNCATE`, `VACUUM FULL`, some `ALTER TABLE`) that the replica replays.
  - Fix: schedule DDL outside report windows. `hot_standby_feedback` will not help.
- `confl_bufferpin` rising:
  - Page cleanup conflicts. Often hint-bit or pruning related. A longer delay is the main lever.
- `confl_deadlock` or `confl_tablespace` rising: rare. Investigate separately.

---

## Step 8 (optional): Other checks that support the diagnosis

### On the primary: is the replica holding back vacuum or lagging?

```sql
SELECT application_name, state, sent_lsn, replay_lsn,
       write_lag, flush_lag, replay_lag
FROM pg_stat_replication;
```

- Large `replay_lag` correlates with cancels, as in step 2.

### On the primary: dead tuple pressure on the report tables

```sql
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;
```

- High `n_dead_tup` on report tables means heavy churn and a bloat risk if you enable `hot_standby_feedback`.

### On the replica: longest running queries right now

```sql
SELECT pid, application_name, state, now() - xact_start AS xact_age,
       now() - query_start AS query_age, left(query, 120) AS query
FROM pg_stat_activity
WHERE state <> 'idle' AND backend_type = 'client backend'
ORDER BY xact_start NULLS LAST;
```

- Look for transactions much older than the delay setting.
- SSRS drivers sometimes hold transactions open ("idle in transaction"). Check those too:
  ```sql
  SELECT pid, application_name, state, now() - xact_start AS xact_age
  FROM pg_stat_activity
  WHERE state = 'idle in transaction';
  ```

---

## Decision table: findings to fix

| Finding | Likely root cause | Fix (tradeoff) |
|---|---|---|
| `P95` or `Max` of `PG_EVENT` > `max_standby_streaming_delay`, `confl_snapshot` rising | Query outlives the replay wait | Tune query and indexes first. Then raise delay (more replica lag). |
| `hot_standby_feedback = off`, cancels follow primary vacuum spikes | Primary cleans rows the replica still needs | Turn on `hot_standby_feedback` (primary bloat and slower vacuum if queries run long). |
| Cancels spike at fixed times with many concurrent SSRS sessions | Overlapping report schedules | Stagger schedules, limit concurrency. |
| `confl_lock` rising | DDL or exclusive locks on the primary replayed on the replica | Move DDL outside report windows. |
| Lag already high before the report starts | Replica under-sized or write rate too high | Scale the replica, reduce write bursts. |
| Duration trending up over days, `n_dead_tup` high | Bloat or stale stats | Vacuum and analyze tuning, review indexes. |
| Non-SSRS app is the long reader | Wrong culprit assumed | Fix that workload, or give it its own replica. |

## Recommended order of fixes (least risky first)

- 1. Tune the `PG_EVENT` query (filters, indexes, fewer rows, avoid `SELECT *`).
- 2. Stagger SSRS schedules and reduce concurrency.
- 3. Raise `max_standby_streaming_delay` on the replica to just above the query P95 (watch lag).
- 4. Enable `hot_standby_feedback` if dead tuple growth on the primary is acceptable.
- 5. Pre-aggregate into a summary table, or use SSRS snapshots or caching for the heavy dataset.
- 6. Add retry logic in the SSRS subscription or caller as a safety net, not a fix.

## Notes

- Verify the current state before changing anything. Do not assume earlier suggestions were applied.
- Re-run steps 1 and 7 after each change to confirm cancels drop.
- Azure may mark some parameters as static (restart needed). Check the parameter's "Requires restart" attribute before changing.
