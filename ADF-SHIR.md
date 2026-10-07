# SHIR High CPU Investigation

## Goal
- Find what caused the SHIR CPU spikes (some sustained ~1 hour) across 3-4 consecutive days, one day with notably more sustained spikes

## Setup
- Copy source: Azure Database for PostgreSQL Flexible Server (Copy reads only from Postgres)
- SHIR: on-prem VMware VM, 16 vCPU / 48 GB RAM
- Copy sink: Oracle DWH, on-prem (Copy writes only to Oracle)
- Symptom: many `diawp.exe` processes, CPU often > 90%
- Scaling the VM 8 -> 12 -> 16 vCPU had no effect

## Pipeline design
- Metadata-driven: Lookup activities run first and read dataset-definition JSONs hosted on ADLS
- Those JSONs say which datasets the later (non-Lookup) activities connect to and use
- After the Lookups: Copy and Script activities
- A failed or timed-out Lookup blocks that pipeline's Copy/Script activities (unless the dependency condition is set to Failed/Completed)
- The size of the metadata and the ForEach `batchCount` decide how many Copies start together

## Known facts
- Defender / Antimalware Service: ruled out (1 process of each)
- Activity types: Lookup, Copy, Script
- Concurrent Jobs on the SHIR node: **28, set manually**
- Activity timeout: 10 minutes
- Copy activity:
  - `usedParallelCopies` = 1 (Degree of copy parallelism = Auto)
  - Peak connections: Postgres 1, Oracle 2
  - Sink write batch size = 50000 (default is 10000)
  - Sink write batch timeout = 0 (meaning unverified; may be "no timeout")
  - Max DIU = Auto (irrelevant on a SHIR)
  - Source queries are ADF expressions that resolve to SQL (check the resolved SQL in Monitor -> Activity run -> Input)
- Lookup: reads small JSONs from ADLS, so negligible CPU on its own
- From memory (unverified): about 10-20 Lookup activities timed out during the period
- Script: contents and target not yet inspected
- Log Analytics `AzureMetrics` is empty, so SHIR CPU cannot be joined in KQL yet
- SHIR CPU is visible on the ADF Metrics chart

## Hypotheses (to confirm or reject)
- H1: 28 single-threaded jobs on 16 vCPU oversubscribes the CPU
- H2: 10-minute timeouts plus retries/reruns restart many activities together, creating bursts of new `diawp.exe` processes (and possibly lingering hung ones)
- H3: per-copy load is high (batch size 50000, wide columns, `SELECT *`, slow Oracle sink keeping copies alive)
- H4: Script activity on Oracle holds locks or runs long, stalling Copy sinks and holding job slots
- H5: non-ADF cause (VMware CPU contention, another process on the VM)

## Lookup timeouts: symptom or trigger?
- Lookups use almost no CPU, so exclude them from any CPU/load estimate
- Keep them as evidence until timing is checked:
  - Timed out AFTER the CPU climbed: symptom (SHIR saturated or all 28 slots busy), ignore them
  - Timed out BEFORE the CPU climbed: possible trigger (timeout -> retry/rerun -> full Copy fan-out starts at once)
- They only take SHIR job slots if the ADLS linked service runs on the SHIR; if it uses the Azure IR, a timeout has a different cause (ADLS access, throttling)
- If on the SHIR, ADLS traffic passes through the on-prem proxy and SSL inspection (possible slow or flaky path; no evidence yet)
- Lookup output is capped (about 5000 rows / 4 MB, from memory); a large metadata JSON can fail

## Open items (answerable from ADF Studio, no VM access)
- [ ] ADLS linked service: "Connect via integration runtime" = SHIR or Azure IR?
- [ ] Script activity: Settings tab (linked service, script text). Does it run on Postgres or Oracle? Any DML, truncate or stored procedure?
- [ ] Dependency condition on activities after each Lookup (Succeeded / Failed / Completed)
- [ ] `policy.retry` and `policy.timeout` on Lookup, Copy, Script
- [ ] ForEach `batchCount` and `isSequential` (unset batchCount defaults to 20)
- [ ] Which triggers start these pipelines; do several share the same minute?
- [ ] Were the ~10-20 timed-out Lookups inside the spike windows, before them, or spread out?

## Investigation steps (UTC times throughout)

### 1. Pick spike windows
- [ ] From the ADF Metrics chart (SHIR CPU), note start/end of 3-4 spikes, including the ~1 hour ones and the heaviest day

### 2. Copy activities with concurrency
- Counts concurrent Copy activities per 5 minutes; includes queue time, so it is an upper bound
```kusto
let conc = ADFActivityRun
| where TimeGenerated > ago(24h) and ActivityType == "Copy"
| where Status in ("Succeeded","Failed")
| extend t = range(bin(Start,1m), bin(End,1m), 1m)
| mv-expand t to typeof(datetime)
| summarize c = count() by t
| summarize PeakConc = max(c) by Bin = bin(t, 5m);
ADFActivityRun
| where TimeGenerated > ago(24h) and ActivityType == "Copy"
| where Status in ("Succeeded","Failed")
| extend o = parse_json(Output)
| extend Bin = bin(Start, 5m)
| project Start, End, PipelineName, ActivityName,
          DurationSec = datetime_diff('second', End, Start),
          RowsCopied = tolong(o.rowsCopied),
          MBRead = tolong(o.dataRead) / 1048576,
          ParallelCopies = toint(o.usedParallelCopies),
          IR = tostring(o.effectiveIntegrationRuntime), Bin
| join kind=leftouter conc on Bin
| project-away Bin*
| order by Start asc
```

### 3. All activities, per 5-minute window, with flags
- Covers Lookup, Copy, Script and all statuses
- For Copy: `Postgres` = source side, `Oracle` = sink side
- Lookup and Script failures are grouped separately (their target is not identifiable from the log)
- `QueueSec` / `FirstByteSec` come from Copy `executionDetails`; field names are from memory. If those columns are empty, open one Copy run's Output in Monitor and check `executionDetails`
```kusto
ADFActivityRun
| where TimeGenerated > ago(7d)
| where ActivityType in ("Copy","Lookup","Script")
| where Status in ("Succeeded","Failed","Cancelled")
| extend o = parse_json(Output)
| extend ed = o.executionDetails[0]
| extend DurationSec = datetime_diff('second', End, Start),
         QueueSec = toreal(ed.detailedDurations.queuingDuration),
         FirstByteSec = toreal(ed.detailedDurations.timeToFirstByte),
         ErrMsg = tostring(parse_json(Error).message)
| extend Side = case(
    Status != "Failed", "n/a",
    ActivityType == "Copy" and ErrMsg has "'Source' side", "Postgres",
    ActivityType == "Copy" and ErrMsg has "'Sink' side", "Oracle",
    ActivityType in ("Lookup","Script"), "Lookup/Script",
    "Unknown")
| sort by PipelineRunId asc, ActivityName asc, Start asc
| extend Attempt = row_number(1, PipelineRunId != prev(PipelineRunId) or ActivityName != prev(ActivityName))
| summarize
    Runs = count(),
    Failed = countif(Status == "Failed"),
    FailedPostgres = countif(Side == "Postgres"),
    FailedOracle = countif(Side == "Oracle"),
    FailedLookupScript = countif(Side == "Lookup/Script"),
    Retries = countif(Attempt > 1),
    Queued60s = countif(QueueSec > 60),
    AvgQueueSec = round(avg(QueueSec), 1),
    MaxFirstByteSec = max(FirstByteSec),
    AvgDurationSec = round(avg(DurationSec), 1),
    MaxDurationSec = max(DurationSec)
    by Window = bin(Start, 5m), ActivityType
| extend Flag = case(
    Queued60s > 0 or AvgQueueSec > 30, "QUEUE: job cap saturated",
    Retries > 0, "RETRIES: restart churn",
    MaxFirstByteSec > 60, "POSTGRES: slow connect/read",
    FailedOracle > 0, "ORACLE: sink failures",
    FailedPostgres > 0, "POSTGRES: source failures",
    FailedLookupScript > 0, "LOOKUP/SCRIPT: failures",
    Failed > 0, "FAILURES: other",
    "")
| order by Window asc
```
- Use: sort or filter the `Flag` column and look only at rows whose `Window` is inside a spike window from step 1

### 4. Timeouts around spike windows (answers: before or after the CPU climb?)
- Fill the window rows from step 1
- Includes the 30 minutes before each window; `MinFromSpikeStart` is negative if the timeout was before the spike started
```kusto
let windows = datatable(WStart:datetime, WEnd:datetime) [
    datetime(2026-10-03 08:00:00), datetime(2026-10-03 09:00:00),
    datetime(2026-10-04 13:00:00), datetime(2026-10-04 14:00:00)
];
ADFActivityRun
| where TimeGenerated > ago(7d)
| where ActivityType in ("Copy","Lookup","Script")
| where Status == "Failed"
| extend DurationSec = datetime_diff('second', End, Start)
| extend ErrMsg = tostring(parse_json(Error).message), ErrCode = tostring(parse_json(Error).errorCode)
| where ErrMsg has_any ("timeout","timed out","Timeout") or DurationSec between (570 .. 630)
| extend k = 1
| join kind=inner (windows | extend k = 1) on k
| where Start <= WEnd and End >= WStart - 30m
| extend MinFromSpikeStart = datetime_diff('minute', End, WStart)
| project WStart, WEnd, MinFromSpikeStart, Start, End, DurationSec, PipelineName, ActivityName, ActivityType, ErrCode, ErrMsg
| order by WStart asc, Start asc
```

### 5. Optional follow-up: timeouts per hour (shows the heavy day)
```kusto
ADFActivityRun
| where TimeGenerated > ago(7d)
| where ActivityType in ("Copy","Lookup","Script")
| where Status == "Failed"
| extend DurationSec = datetime_diff('second', End, Start)
| extend ErrMsg = tostring(parse_json(Error).message)
| where ErrMsg has_any ("timeout","timed out","Timeout") or DurationSec between (570 .. 630)
| summarize Timeouts = count(), Pipelines = dcount(PipelineName) by Hour = bin(Start, 1h), ActivityType
| order by Hour asc
```

### 6. Optional follow-up: failures by side and error type
- Shows whether connection problems appear on the Postgres side, the Oracle side, or both
```kusto
ADFActivityRun
| where TimeGenerated > ago(7d)
| where ActivityType in ("Copy","Lookup","Script")
| where Status == "Failed"
| extend ErrMsg = tostring(parse_json(Error).message), ErrCode = tostring(parse_json(Error).errorCode)
| extend Side = case(
    ActivityType == "Copy" and ErrMsg has "'Source' side", "Postgres",
    ActivityType == "Copy" and ErrMsg has "'Sink' side", "Oracle",
    ActivityType in ("Lookup","Script"), "Lookup/Script",
    "Unknown")
| extend ErrType = case(
    ErrMsg has_any ("timeout","timed out"), "Timeout",
    ErrMsg has_any ("ORA-","Oracle"), "Oracle error",
    ErrMsg has_any ("refused","reset","closed","unreachable","network","connect"), "Connection",
    ErrMsg has_any ("password","authentication","login","denied"), "Auth",
    ErrMsg has_any ("too many","max_connections","remaining connection slots"), "Connection limit",
    "Other")
| summarize Failures = count(), Pipelines = dcount(PipelineName), Example = take_any(substring(ErrMsg, 0, 200))
    by Hour = bin(Start, 1h), Side, ErrType, ErrCode
| order by Hour asc
```
- The "'Source' side" / "'Sink' side" wording is from memory; check it against a real error. Rows with `Side = Unknown` need a manual read of `ErrMsg`

### 7. Read the results
| Finding (in spike windows) | Meaning | Next |
|----------------------------|---------|------|
| Flag `QUEUE`, or `PeakConc` near 28 | H1 | Lower Concurrent Jobs (start ~10) |
| Flag `RETRIES`, or timeouts every ~10 min | H2 | Check `policy.retry`, fix the slow dependency, stagger |
| Lookup timeouts with negative `MinFromSpikeStart` | Lookup timeout may trigger the Copy wave | Check retries/reruns after those Lookups, ADLS linked service IR, trigger overlap |
| Lookup timeouts only after the CPU climb | Symptom | Ignore Lookups |
| Flag `POSTGRES` (slow connect/read or source failures) | Postgres or network path to Azure | Check Postgres CPU/connections and network |
| Flag `ORACLE`, or `ORA-` in errors, long copy durations | Oracle sink slow or locked | DBA review of sessions, waits, locks |
| Flag `LOOKUP/SCRIPT` on Script | H4 | Inspect the Script content and target |
| Same pipeline/activity repeating | Specific culprit | Inspect its SQL, sink, locks |
| Few small copies, no flags, CPU still high | H5 | VM and VMware checks (step 8) |
| Few large copies running most of the hour | H3 | Batch size, columns, Oracle waits |

### 8. Checks by other teams (same windows)
- VM admin: Task Manager during a spike
  - Total `diawp.exe` CPU vs other processes
  - Any `diawp.exe` with uptime longer than 10 minutes (timed-out processes not exiting)
- Virtualization team: CPU Ready %, co-stop, ballooning/swapping for the VM
- DBA team: Oracle DWH sessions, waits and locks for the ADF user, long-running DML from Script, session count (28 jobs x 2 = up to ~56)
- Azure side: Postgres CPU, connections, long-running queries

### 9. Enable CPU in Log Analytics (optional, needs ADF Contributor)
- ADF -> Monitoring -> Diagnostic settings -> tick **AllMetrics** for the Log Analytics destination
- Fills going forward only (no backfill)
- Check names: `AzureMetrics | distinct MetricName` (expected `IntegrationRuntimeCpuPercentage`, unverified)
- Without it, use an Azure Workbook with a Metrics item (SHIR CPU) above a Logs item (step 2 query) on the same time range

## Change plan (one at a time, record each result)
- [ ] Record current settings before any change (Concurrent Jobs, retry, timeouts, batch size, `batchCount`)
- [ ] Lower Concurrent Jobs from 28 to about 10, then tune on 5-minute average CPU (> 80% lower by 1-2; < 50% with queueing raise by 1-2)
- [ ] Review `policy.retry` / `policy.timeout` on Lookup, Copy, Script
- [ ] Set ForEach `batchCount` to match the cap; stagger triggers
- [ ] Test write batch size 10000 on one pipeline vs 50000
- [ ] Set an explicit write batch timeout and verify what 0 means
- [ ] Tell the DBA team about the connection and load change

## Caveats
- None of the KQL has been run against the real workspace
- `executionDetails` field names and the "Source/Sink side" error wording are unverified
- The Lookup timeout count (10-20) is from memory
- Nothing in this file is assumed to be applied; verify current state before building on it

## Results log
| Date | Change | Concurrent jobs | CPU avg/peak | Timeouts | Notes |
|------|--------|-----------------|--------------|----------|-------|
|      |        |                 |              |          |       |

## Addendum

**What to look for in "Script" activity types**
- Likely: pre-copy cleanup, post-copy merge or watermark updates, and audit logging, usually on Oracle.
- Red flags are long-running DML, truncate or delete on tables a Copy is writing to, and unbounded parallelism.
- A Script mostly costs time and locks, not SHIR CPU.

**What you will probably find**
- **Pre-copy:** `TRUNCATE`, `DELETE ... WHERE`, or disabling indexes and constraints on the target.
- **Post-copy:** `MERGE` or `INSERT ... SELECT` from a staging table into the final table, or a stored procedure call.
- **Control and logging:** watermark updates, audit or run-log inserts, status flags.
- **Maintenance:** stats gathering (`DBMS_STATS`), index rebuilds, partition operations.
- In a metadata-driven setup, the script text may be built from the ADLS JSON values as an expression. If so, check the resolved SQL in Monitor → Activity run → Input.

**Red flags**
- **`TRUNCATE` or `DELETE` on a table a Copy is writing to:** locks or waits, so the Copy runs long, holds its slot and may time out.
- **Large `MERGE`, `UPDATE` or `DELETE` with no `WHERE` or batching:** minutes-long statements that hit the 10-minute timeout, then retry and redo the work.
- **Same script running in parallel across many ForEach iterations against the same table:** lock contention, and it fills job slots while waiting.
- **Missing indexes on the merge or delete key:** full scans on a big DWH table.
- **Stats gathering or index rebuild during business hours:** heavy load on Oracle.
- **Multiple statements in one script block:** a failure part-way can leave partial changes, and a retry reruns everything.
- **Retry set above 0 on a non-idempotent script:** duplicates or double deletes.
- **Dynamic SQL built from metadata with no validation:** one bad JSON entry can produce an unbounded statement.
- **Commit behaviour you can't see:** long transactions hold undo and locks until the activity ends.

**Hotspots for your problem**
- Scripts that run on Oracle at the same time as the Copy sinks writing to it.
- Scripts that block until the 10-minute timeout, then retry. Timing out and retrying fits the restart-churn suspect.
- Scripts launched in volume by the same fan-out as the Copies.

**Where to look**
- ADF Studio → Author → pipeline → Script activity → Settings: linked service, script text, script type (Query or NonQuery), and the Retry and Timeout values in General.
- Monitor → Activity run → Input shows the resolved SQL, and Output shows duration and rows affected.
- The DBA team can match Script statements to Oracle long-running sessions, lock waits and blocking sessions in the spike windows.

**Caveats**
- This is a general picture of what such scripts usually contain, not what yours do.
- A Script's CPU cost on the SHIR itself is small, since the work runs on the database. Its impact on the spikes is indirect, through slot occupancy, blocked Copies and retries.


**Useful LAW kqls**
- Seven queries for the Log Analytics workspace (LAW), each a full query.
- Untested here. Column names are from memory, so check them against the schema pane if one fails.

**1. Which ADF tables have data**
```kusto
Usage
| where TimeGenerated > ago(7d)
| summarize MB = round(sum(Quantity), 1) by DataType
| order by MB desc
```
- Look for `ADFActivityRun`, `ADFPipelineRun`, `ADFTriggerRun` and `AzureMetrics`.

**2. Activity runs by day, pipeline, type and status**
```kusto
ADFActivityRun
| where TimeGenerated > ago(7d)
| where Status in ("Succeeded","Failed","Cancelled")
| summarize Runs = count(),
            Failed = countif(Status == "Failed"),
            AvgSec = round(avg(datetime_diff('second', End, Start)), 1),
            MaxSec = max(datetime_diff('second', End, Start))
    by Day = bin(Start, 1d), PipelineName, ActivityType
| order by Day asc, Runs desc
```
- Gives you the organizing Monitor lacks.

**3. Activity starts per hour (find the heavy day and hour)**
```kusto
ADFActivityRun
| where TimeGenerated > ago(7d)
| where Status in ("Succeeded","Failed","Cancelled")
| summarize Starts = count() by Hour = bin(Start, 1h), ActivityType
| order by Hour asc
| render timechart
```

**4. Triggers firing in the same minute**
```kusto
ADFTriggerRun
| where TimeGenerated > ago(7d)
| summarize Triggers = count(), TriggerNames = make_set(TriggerName, 10) by Minute = bin(TimeGenerated, 1m)
| where Triggers > 1
| order by Triggers desc
```
- Overlapping triggers would fit the fan-out suspicion.

**5. Slowest activities in the week**
```kusto
ADFActivityRun
| where TimeGenerated > ago(7d)
| where Status in ("Succeeded","Failed","Cancelled")
| extend DurationSec = datetime_diff('second', End, Start)
| top 50 by DurationSec desc
| project Start, End, DurationSec, PipelineName, ActivityName, ActivityType, Status
```

**6. Retries by activity**
```kusto
ADFActivityRun
| where TimeGenerated > ago(7d)
| where Status in ("Succeeded","Failed","Cancelled")
| summarize Attempts = count(), Failures = countif(Status == "Failed")
    by PipelineRunId, PipelineName, ActivityName, ActivityType
| where Attempts > 1
| summarize RetriedActivities = count(), TotalExtraAttempts = sum(Attempts - 1)
    by PipelineName, ActivityName, ActivityType
| order by TotalExtraAttempts desc
```
- Retries restart `diawp.exe` processes, so the top rows are the pipelines to look at first.

**7. Top error messages**
```kusto
ADFActivityRun
| where TimeGenerated > ago(7d)
| where Status == "Failed"
| extend ErrCode = tostring(parse_json(Error).errorCode),
         ErrMsg = substring(tostring(parse_json(Error).message), 0, 200)
| summarize Failures = count(), Pipelines = dcount(PipelineName), FirstSeen = min(Start), LastSeen = max(Start)
    by ActivityType, ErrCode, ErrMsg
| order by Failures desc
```

**Notes**
- Times are UTC.
- Query 6 assumes each retry appears as a separate row with the same `PipelineRunId` and `ActivityName`. If counts look off, that assumption is wrong.
- Query 4 depends on `ADFTriggerRun` being collected, which is a separate diagnostic category.
