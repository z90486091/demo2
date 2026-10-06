# SHIR High CPU Investigation (Postgres Flexible Server -> SHIR -> Oracle DWH)

## Context
- Source: Azure Database for PostgreSQL Flexible Server
- SHIR: on-prem VMware VM, 16 vCPU / 48 GB RAM, Windows Defender running
- Sink: Oracle DWH (on-prem)
- Symptom: many `diawp.exe` processes, CPU > 90% often
- Scale-up 8 -> 12 -> 16 vCPU gave no relief, only more `diawp.exe` processes
- Working hypothesis: concurrent job limit is on Auto, so it scales with vCPU and fills any capacity added
- Secondary suspects: Defender real-time scanning, VMware CPU contention, per-copy load (parallel copies, wide columns, sink batch size)
- Nothing below is confirmed applied. Record the current value of each setting before changing it.

## Who needs access to what
- ADF Studio / Azure Portal: needs someone with ADF access (Reader is enough for viewing, Contributor to change)
- SHIR VM: needs someone with admin on the VM (Windows team)
- VMware host: needs the virtualization team (vCenter)
- Oracle DWH: needs the DBA team
- Postgres Flexible Server: needs the Azure / DB owner (Azure Monitor metrics)

---

## A. Defender / antivirus (VM admin required)

### Why it was raised
- Defender real-time protection scans files on read/write and on process/DLL load
- SHIR writes logs, temp files and may spill buffers to disk; each `diawp.exe` start loads DLLs
- `MsMpEng.exe` (Antimalware Service Executable) competes for the same CPU
- Likely a contributor, not the root cause: Postgres -> Oracle copy is mostly in-memory streaming, so AV load tracks disk activity, not row throughput

### Check first (evidence before changes)
- [ ] During a spike, Task Manager -> Details -> sort by CPU. Record CPU % of `MsMpEng.exe` vs total of all `diawp.exe`
- [ ] If `MsMpEng.exe` is under ~5% of total CPU: AV is not the problem
- [ ] If `MsMpEng.exe` is 15%+ sustained: AV is a real contributor
- [ ] Defender performance recording (PowerShell as admin):
  - `New-MpPerformanceRecording -RecordTo C:\temp\defender.etl` (run during spike, stop when prompted)
  - `Get-MpPerformanceReport -Path C:\temp\defender.etl -TopProcesses 10 -TopFiles 10`
  - Look for SHIR folders or `diawp.exe` in top scanned files/processes
- [ ] List current exclusions: `Get-MpPreference | Select-Object ExclusionPath, ExclusionProcess`
- [ ] Check whether Group Policy / Intune / Defender for Endpoint manages the exclusions (local changes may be overwritten)

### If AV is a contributor
- Do NOT disable Defender. Add scoped exclusions through your security team
- Candidate path exclusions (verify actual paths on the VM):
  - SHIR install folder (typically `C:\Program Files\Microsoft Integration Runtime\`)
  - SHIR data/log folder (typically under `C:\ProgramData\Microsoft\DataTransfer\`)
  - Any temp folder the SHIR uses for spill
- Candidate process exclusions: `diawp.exe`, `DIAHostService.exe` (confirm names in Task Manager)
- Expected impact: reduces scan overhead on SHIR file I/O; modest gain. Does not fix too many concurrent jobs
- Get security sign-off and document the exclusion

---

## B. SHIR node settings (ADF Studio)
- [ ] Manage -> Integration runtimes -> SHIR -> Nodes
- [ ] Record: Concurrent Jobs (Running / Limit), node version, CPU, available memory
- [ ] Note whether the limit is auto-derived or manual
- [ ] Record SHIR version (older versions had CPU/memory bugs) and whether auto-update is on

### Proposed starting values (to test, not confirmed)
- Concurrent Jobs: 6
- Degree of copy parallelism: 2
- Rule of thumb: `concurrent jobs x copy parallelism` ~ 8-12 on 16 vCPU
- Many small tables: jobs 8, parallelism 1
- Few huge tables: jobs 3-4, parallelism 3-4
- Tune on 5-minute average CPU: > 80% lower by 1-2; < 50% with queueing raise by 1-2

---

## C. Count and identify copy activities

### In ADF Studio (Monitor)
- [ ] Monitor -> Pipeline runs -> pick a spike window -> open run -> Activity runs
- [ ] Filter Activity type = Copy; note Integration runtime column = your SHIR
- [ ] Note which pipelines trigger at the same minute
- [ ] Per activity run -> Output (glasses icon): `usedParallelCopies`, `rowsCopied`, `dataRead`, `copyDuration`, `throughput`

### In Azure Monitor (Metrics)
- [ ] ADF resource -> Metrics -> chart SHIR CPU utilization, available memory, queue length, concurrent jobs for the spike window
- [ ] Overlay with trigger times

### In Log Analytics (only if diagnostic settings are on; adjust columns to your schema)
```kusto
ADFActivityRun
| where TimeGenerated > ago(24h) and ActivityType == "Copy"
| where Status in ("Succeeded","Failed")
| extend o = parse_json(Output)
| project Start, End, PipelineName, ActivityName,
          DurationSec = datetime_diff('second', End, Start),
          RowsCopied = tolong(o.rowsCopied),
          MBRead = tolong(o.dataRead) / 1048576,
          ParallelCopies = toint(o.usedParallelCopies),
          IR = tostring(o.effectiveIntegrationRuntime)
| order by Start asc
```
- [ ] Use Start/End overlap to calculate peak concurrent copies
- [ ] Compare peaks against CPU spikes

### Record
| Window | Peak concurrent copies | Pipelines involved | Avg CPU | Notes |
|--------|------------------------|--------------------|---------|-------|
|        |                        |                    |         |       |

---

## D. Copy activity settings to inspect
- Where: Author -> pipeline -> Copy activity -> Source / Sink / Settings tabs, or `{}` for full JSON
- If Git-linked: `/pipeline/<name>.json` in the repo

### Checklist
- [ ] `parallelCopies`: missing = Auto (likely culprit)
- [ ] Source type: `AzurePostgreSqlSource` or `PostgreSqlV2Source`
- [ ] Source query: `SELECT *`? wide `text` / `jsonb` / `bytea` columns?
- [ ] Source partition options: dynamic range with many partitions?
- [ ] Watermark / `WHERE` filter present, or full reload every run?
- [ ] Sink type: `OracleSink` or `OracleV2Sink`
- [ ] `writeBatchSize`: missing = default 10000
- [ ] `writeBatchTimeout`: missing = default 30 min
- [ ] Pre-copy script on the sink?
- [ ] Parent ForEach: `batchCount` (default 20 if missing) and `isSequential`
- [ ] Staging: not supported for an Oracle sink

### Reference sample (starting values, to diff against)
```json
{
  "name": "Copy_PG_to_OracleDWH",
  "type": "Copy",
  "policy": { "timeout": "0.12:00:00", "retry": 1, "retryIntervalInSeconds": 60 },
  "typeProperties": {
    "source": {
      "type": "AzurePostgreSqlSource",
      "query": "SELECT col_a, col_b, col_c FROM public.my_table WHERE updated_at >= '@{pipeline().parameters.watermark}'",
      "queryTimeout": "02:00:00"
    },
    "sink": {
      "type": "OracleSink",
      "writeBatchSize": 10000,
      "writeBatchTimeout": "00:30:00"
    },
    "parallelCopies": 2,
    "enableStaging": false
  }
}
```

---

## E. VMware host (virtualization team)
- [ ] CPU Ready % for the SHIR VM during spikes (sustained > 5% per vCPU is a concern)
- [ ] CPU co-stop (large vCPU counts can hurt scheduling)
- [ ] Memory ballooning / swapping on the VM
- [ ] Host CPU utilization and VM count on the host
- [ ] Check whether 16 vCPU is oversized for the host (fewer vCPUs can sometimes schedule better)

## F. Source and sink side
- Postgres Flexible Server (Azure Monitor): CPU, active connections, network egress, long-running queries during spikes
- Oracle DWH (DBA team): active sessions from the ADF user, array insert waits, CPU, indexes/triggers on target tables, redo/undo pressure
- Slow source or sink keeps `diawp.exe` processes alive longer and stacks them up

## G. Change plan (apply one at a time, record results)
1. [ ] Record baselines (sections A-F)
2. [ ] Set Concurrent Jobs manually (start 6)
3. [ ] Set `parallelCopies` explicitly (start 2)
4. [ ] Set ForEach `batchCount` to match the node cap
5. [ ] Stagger triggers
6. [ ] Trim source columns, tune `writeBatchSize`
7. [ ] If AV evidence supports it: request scoped exclusions
8. [ ] Re-measure CPU, run duration, failure rate after each change

### Results log
| Date | Change | Concurrent jobs | CPU avg/peak | Run duration | Notes |
|------|--------|-----------------|--------------|--------------|-------|
|      |        |                 |              |              |       |

## H. What to bring back for a diff
- Pipeline JSON: Copy activity(ies) and parent ForEach
- Node screenshot showing Concurrent Jobs (Running/Limit)
- Task Manager / Defender recording summary from a spike
- Peak concurrent copy count
