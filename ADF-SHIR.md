# SHIR High CPU Investigation

## Goal
- Find what caused the SHIR CPU spikes (some sustained ~1 hour) across 3-4 consecutive days, one day with notably more sustained spikes

## Setup
- Source: Azure Database for PostgreSQL Flexible Server
- SHIR: on-prem VMware VM, 16 vCPU / 48 GB RAM
- Sink: Oracle DWH (on-prem)
- Symptom: many `diawp.exe` processes, CPU often > 90%
- Scaling the VM 8 -> 12 -> 16 vCPU had no effect

## Known facts
- Defender / Antimalware Service: ruled out (1 process of each)
- Activity types in pipelines: Copy, Lookup, Script
- Concurrent Jobs on the SHIR node: **28, set manually**
- Activity timeout: 10 minutes
- Copy activity:
  - `usedParallelCopies` = 1 (Degree of copy parallelism = Auto)
  - Peak connections: source 1, target 2
  - Sink write batch size = 50000 (default is 10000)
  - Sink write batch timeout = 0 (meaning unverified; may be "no timeout")
  - Max DIU = Auto (irrelevant on a SHIR)
  - Source queries are ADF expressions that resolve to SQL (check the resolved SQL in Monitor -> Activity run -> Input)
- Log Analytics `AzureMetrics` is empty, so SHIR CPU cannot be joined in KQL yet
- SHIR CPU is visible on the ADF Metrics chart

## Hypotheses (to confirm or reject)
- H1: 28 single-threaded jobs on 16 vCPU oversubscribes the CPU
- H2: 10-minute timeouts plus retries restart many activities together, creating bursts of new `diawp.exe` processes (and possibly lingering hung ones)
- H3: per-copy load is high (batch size 50000, wide columns, `SELECT *`, slow Oracle sink keeping copies alive)
- H4: non-ADF cause (VMware CPU contention, another process on the VM)

## Investigation steps (UTC times throughout)

### 1. Pick spike windows
- [ ] From the ADF Metrics chart (SHIR CPU), note start/end of 3-4 spikes, including the ~1 hour ones and the heaviest day

### 2. Copy activities with concurrency (Log Analytics)
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

### 3. Timeouts inside spike windows
- Fill the window rows from step 1
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
| where Start <= WEnd and End >= WStart
| project WStart, WEnd, Start, End, DurationSec, PipelineName, ActivityName, ActivityType, ErrCode, ErrMsg
| order by WStart asc, Start asc
```

### 4. Timeouts per hour (find the heavy day)
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
- If the timeout filter returns nothing, remove the `where ErrMsg ...` line and inspect the error text
- If `Status` values differ: `ADFActivityRun | distinct Status`

### 5. Read the results
| Finding | Meaning | Next |
|---------|---------|------|
| `PeakConc` near 28 when CPU is high | H1 | Lower Concurrent Jobs (start ~10) |
| Timeouts clustered every ~10 min in spike windows | H2 | Check `policy.retry`, fix the slow dependency, stagger |
| Same pipeline/activity timing out repeatedly | Specific culprit | Inspect its SQL, sink, locks |
| `ORA-` in `ErrMsg` | Oracle slow or locked | DBA review |
| Few small copies, no timeouts, CPU still high | H4 | VM and VMware checks (step 6) |
| Few large copies running most of the hour | H3 | Batch size, columns, Oracle waits |

### 6. Checks by other teams (same windows)
- VM admin: Task Manager during a spike
  - Total `diawp.exe` CPU vs other processes
  - Any `diawp.exe` with uptime longer than 10 minutes (timed-out processes not exiting)
- Virtualization team: CPU Ready %, co-stop, ballooning/swapping for the VM
- DBA team: Oracle DWH sessions, waits and locks for the ADF user, long-running DML from Script activities
- Azure side: Postgres CPU, connections, long-running queries

### 7. Enable CPU in Log Analytics (optional, needs ADF Contributor)
- ADF -> Monitoring -> Diagnostic settings -> tick **AllMetrics** for the Log Analytics destination
- Fills going forward only (no backfill)
- Check names: `AzureMetrics | distinct MetricName` (expected `IntegrationRuntimeCpuPercentage`, unverified)
- Without it, use an Azure Workbook with a Metrics item (SHIR CPU) above a Logs item (step 2 query) on the same time range

## Change plan (one at a time, record each result)
- [ ] Record current settings before any change (Concurrent Jobs, retry, timeouts, batch size)
- [ ] Lower Concurrent Jobs from 28 to about 10, then tune on 5-minute average CPU (> 80% lower by 1-2; < 50% with queueing raise by 1-2)
- [ ] Check `policy.retry` and `policy.timeout` on the pipelines in the timeout results
- [ ] Test write batch size 10000 on one pipeline vs 50000
- [ ] Set an explicit write batch timeout and verify what 0 means
- [ ] Stagger triggers; set ForEach `batchCount` to match the cap
- [ ] Tell the DBA team about the connection and load change (28 jobs x 2 = up to ~56 Oracle sessions)

## Results log
| Date | Change | Concurrent jobs | CPU avg/peak | Timeouts | Notes |
|------|--------|-----------------|--------------|----------|-------|
|      |        |                 |              |          |       |
