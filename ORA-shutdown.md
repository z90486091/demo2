# Oracle DB Shutdown for Traffic Cutoff — Discussion Summary

## What "Oracle shutdown" entails
- Full instance shutdown (not just read-only) — no connections possible at all, including CDC readers.
- Precondition: Striim must have consumed all outstanding redo/archive logs up to the final SCN, or in-flight transactions are lost.
- AppDev/ETL traffic must be diverted before shutdown — Oracle won't accept new sessions after.
- Rollback is heavier than a read-only lockdown: requires restarting instance, reopening listener, revalidating state.
- Flagged sequencing risk: whether shutdown replaces or follows the read-only lockdown step changes rollback safety margin.

## Striim "ONLINE" status ≠ caught up
- ONLINE only means the CDC reader is running/connected, not that it has processed all data.
- Real check: replication lag ≈ 0 (Striim's captured SCN matches Oracle's current SCN, no backlog).
- Correct order: status ONLINE → lag ≈ 0 → capture final SCN → shut down Oracle.

## Oracle shutdown steps, in sequence
1. Confirm Striim ONLINE, lag ≈ 0, captured SCN matches Oracle's current SCN.
2. Notify AppDev/ETL to divert/pause all application traffic away from Oracle.
3. Confirm no active sessions remain (`v$session`); kill stragglers if needed.
4. Stop the Oracle Listener (`lsnrctl stop`) — blocks new incoming connections.
5. Run `SHUTDOWN IMMEDIATE` (not `ABORT`) on the DB engine — lets in-flight transactions finish cleanly.
6. Verify instance is fully down (no PMON/SMON processes running).
7. DBA signs off shutdown complete before the next cutover step proceeds.

**Listener-vs-engine order clarified:** stop the listener *first*, then `SHUTDOWN IMMEDIATE` — this is best practice, not a hard Oracle requirement (the two are independent processes).

## How to get the SCN

**From Oracle:**
- `SELECT CURRENT_SCN FROM V$DATABASE;` — live system SCN.
- `SELECT DBMS_FLASHBACK.GET_SYSTEM_CHANGE_NUMBER FROM DUAL;` — alternate method, same value.
- `SELECT MAX(SEQUENCE#) FROM V$LOG;` / `V$ARCHIVED_LOG` — check latest redo/archived log generated, to compare against what Striim has consumed.

**From Striim:**
- Web UI → Flow → source OracleReader component → Monitor/Stats panel → "Read SCN" / "Committed SCN" (label varies by version).
- TQL/console: `SHOW <OracleReader_component_name>;` or `MON <flow_name>;` — surfaces reader's current position including last-read SCN.
- Internal checkpoint table (e.g. `ChkptTable` in target, if persisted) also stores last committed SCN per source.

**Validation:** Oracle's `CURRENT_SCN` should equal (or be ≤) Striim's reported read/committed SCN to confirm CDC is fully caught up before shutdown.
