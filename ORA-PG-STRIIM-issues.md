A) DBA Team

Which table(s) failed in the last Initial Load run, and what was the exact error/exception message?
Can you share the Initial Load app's exception log for that run before the next truncate?
Is Initial Load one single app covering all tables, or split per table/group?
Why does a single table failure trigger a full truncate of all tables, not just the failed one?
What's the current Validation Report status per table (in-sync/out-of-sync)?
Which tables are currently on CDC, and which are still pending successful Initial Load?
Has CDC ever run against a table before its Initial Load succeeded?
Is exception handling set to HALT or CONTINUE on write errors — per app?
Are recurring failures on the same table(s) each time, or different ones?
What's the retry/backoff process — manual or automated?

B) Microsoft/Striim

Is Initial Load meant to be architected as one monolithic app or per-table/group apps for large table counts?
What's the recommended failure-isolation pattern — table-level retry vs. full-app retry?
Can exception state/logs be exported or persisted before a table truncate+retry?
What commonly causes recurring Initial Load failures on Oracle JSON/CLOB/UDT columns?
Does LogMiner-based CDC have known unsupported operation codes (e.g., 255/UNSUPPORTED) for JSON columns, similar to Debezium?
What's the recommended Validation (Validata) run cadence during active migration?
Can Initial Load and CDC be scoped/started per-table, independent of other tables' status?
Is there a way to get proactive alerting when Initial Load halts, rather than relying on manual status checks?
What's your reference architecture for isolating snapshot failures from full-pipeline resets at scale?
