# AppDynamics Investigation: Oracle DWH CPU Spikes (with SSRS SQL Server)

## Goal
- Identify what caused the CPU spikes on the Oracle DWH, using AppDynamics only
- Build a timeline (before, during, after) for each spike window, then drill down to the session / query statement text behind it
- SHIR / ADF is out of scope for this line of investigation

## Constraints
- Solo work, no DBA or other-team help
- AppD admin access to both collectors: Oracle DWH and SSRS SQL Server
- No direct DB access
- Avoid screenshots; capture values and timestamps as text notes unless there is no other way
- Metric names and menu locations in this file are from memory; match them to the actual Controller

## Known context
- Oracle DWH: 48 cores (per AppD)
- Baseline CPU on a normal weekday: about 25-40%
- Workloads sharing the DWH: SSRS reporting (heavy report SQL runs on Oracle), billing jobs, ADF ETLs, a full load from one source DB, backups (4 AM log backups, 6 PM incremental, US Eastern), hourly MV refreshes
- SSRS SQL Server holds only the report catalog and scheduling; it shows when reports were requested, not the cost of the report SQL
- A past spike: 98-99% CPU for 4-5 hours, which caused missed report deliveries
- SSRS top wait is believed to be `LCK_M_S` / `LCK_M_X` (shared / exclusive lock waits), present all the time; not yet viewed for a spike window

## Preparation
- [ ] List spike windows: start, end, timezone (use one timezone everywhere)
- [ ] Pick one baseline window per spike: same weekday and hour in a quiet week
- [ ] Check data resolution for each window (my recollection: 1-minute for a few hours, 10-minute for about 2 days, then hourly; verify). Do the most recent spike first
- [ ] Time range for every view: spike start -60 min to end +60 min

## Step 1: one graph first (Metrics Browser)
- Metrics: Oracle DWH host CPU % and SSRS SQL Server host CPU %, same time range
- Note:
  - Start: time Oracle CPU leaves baseline, and the time it crosses 80%
  - Order: SSRS CPU before, with or after Oracle
  - End: time CPU drops back; sudden (kill or job end) or gradual
- Reading:
  - SSRS first: report side likely involved
  - Oracle alone: probably not report-driven
  - Sudden drop: something was killed or finished
- Add the next graph only after this one is done

## Step 2: further graphs, one unit per graph (add one at a time)
- Session counts: Oracle active sessions, SSRS active sessions, blocked sessions (both)
  - Oracle active sessions above the core count (48) means CPU queueing
- Rate per second: Oracle executions per second and SSRS batch requests per second
  - Compare timing and shape, not height; use a secondary axis or split graphs where scales differ
- Oracle only: physical reads per second (full-table-scan signal)
- Never mix percent, counts and rates in one graph

## Step 3: hotspots to mark in each graph
- First mover (which metric, which system, what time)
- Threshold crossing (80% CPU)
- Plateau: level and length
- Shape: steady (sustained sessions) vs periodic peaks (scheduled jobs)
- Last to recover (often the culprit's footprint)
- Repetition: same sequence in every spike window and absent in the baseline
- Alignment with known schedule points: backups, hourly MV refresh, reporting peak window

## Step 4: drill down to the culprit (DB Monitoring, same time range as the graph)
- Oracle DWH collector:
  - Queries tab: sort by total time or CPU; open the top queries to read the statement text, executions and wait breakdown
  - Sessions / Clients: group by user, program, client machine (SSRS service account, billing user, ADF user, others)
  - Blocked sessions: note the blocker's statement
  - Check that a suspect query's activity matches the shape and timing of the CPU graph; no match rules it out
- Match pattern to target:
  - CPU and active sessions high: top queries by CPU, sessions per user
  - Periodic peaks: same query at each peak time
  - Physical reads spiking: sort by reads; look for scans in the statement text
  - Blocked sessions rising: the blocking session's statement
- SSRS SQL Server collector, same window:
  - Which ReportServer queries ran, and the top waits (see next section)
  - Link to Oracle by time and by the SSRS account in Oracle's Sessions tab

## SSRS wait check
- `LCK_M_S` / `LCK_M_X` are lock waits (time blocked, not CPU consumed)
- Compare total wait time for the spike window against the baseline window
  - Well above baseline: SSRS sessions stalling or piling up (slow, long-running reports)
  - Flat vs baseline: not part of the story, drop it
  - Rising only after Oracle CPU climbs: SSRS is a victim
- Waits that would matter more for CPU: `SOS_SCHEDULER_YIELD`, `ASYNC_NETWORK_IO`, `CXPACKET` / `CXCONSUMER`, `PAGEIOLATCH_*`
- Steady presence cannot explain why a spike happened on a particular day; only a change from baseline can

## Per-spike timeline template
- Spike ID / date:
- Window (start-end, timezone):
- Baseline window used:
- T-60 to start: baseline levels, anything moving early:
- First mover (system, metric, time):
- 80% CPU crossing time:
- Plateau (level, length):
- Recovery time and what dropped first / last:
- Top suspect query (statement start, user, program, time range active):
- Evidence match (does its activity fit the CPU graph shape?):
- Waits: SSRS lock waits vs baseline:
- Confidence: shows (data) vs infers (inference):

## Results log
| Spike | Window | First mover | Top suspect (user / query start) | Matches graph? | Notes |
|-------|--------|-------------|----------------------------------|----------------|-------|
|       |        |             |                                  |                |       |

## Caveats
- Metrics show timing, not which SQL ran; the culprit claim needs the Queries / Sessions drill-down
- Query data is sampled, so short-lived statements can be missed
- Long statements (for example 500-line report queries) can be truncated; use the visible part, user and timing to name the report
- Older windows may be coarse or aged out
- Metric names, tab names and resolution defaults are unverified
- Nothing in this file is assumed to be applied or already checked
