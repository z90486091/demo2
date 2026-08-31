## In Oracle SOURCE
```diff
+++ oracle_precutover_checks.sql
+-- 1. Row counts per table (compare against Postgres after)
+SELECT table_name, num_rows
+FROM user_tables
+ORDER BY table_name;
+
+-- 2. Actual row counts (num_rows is stale stats-based; use for large tables only)
+SELECT 'SELECT '''||table_name||''' tbl, COUNT(*) cnt FROM '||table_name||' UNION ALL'
+FROM user_tables;
+
+-- 3. Sequence current values -> must exceed max(pk) on target after migration
+SELECT sequence_name, last_number
+FROM user_sequences
+ORDER BY sequence_name;
+
+-- 4. Map sequences to tables/columns (for regenerating on Postgres side)
+SELECT ut.table_name, ucc.column_name, us.sequence_name, us.last_number
+FROM user_tab_columns ut
+JOIN user_sequences us ON 1=1
+JOIN user_cons_columns ucc ON ucc.table_name = ut.table_name
+WHERE ut.data_default LIKE '%'||us.sequence_name||'%';
+
+-- 5. Grants currently held by app/service accounts (to replicate on Postgres)
+SELECT grantee, table_name, privilege
+FROM user_tab_privs
+ORDER BY grantee, table_name;
+
+-- 6. Empty-string vs NULL audit (columns where both exist — at risk in Striim collapse)
+SELECT owner, table_name, column_name
+FROM all_tab_columns
+WHERE nullable = 'Y' AND data_type LIKE '%CHAR%';
+-- then per flagged column:
+-- SELECT COUNT(CASE WHEN col = '' THEN 1 END) empties,
+--        COUNT(CASE WHEN col IS NULL THEN 1 END) nulls
+-- FROM table_name;
+
+-- 7. JSON columns still pending CDC support (cross-check against known blocker list)
+SELECT owner, table_name, column_name
+FROM all_tab_columns
+WHERE data_type = 'JSON';
```

## In Postgres TARGET

```diff
+++ postgres_precutover_checks.sql
+-- 1. Row counts per table (compare against Oracle)
+SELECT relname AS table_name, n_live_tup AS approx_rows
+FROM pg_stat_user_tables
+ORDER BY relname;
+
+-- 2. Exact row counts (slower, use pre-cutover only)
+SELECT table_schema, table_name
+FROM information_schema.tables
+WHERE table_schema = 'public';
+-- then dynamically COUNT(*) each
+
+-- 3. Sequence vs max(pk) check — the exact class of bug from UAT
+SELECT s.relname AS sequence_name,
+       pg_sequence_last_value(s.oid) AS seq_value
+FROM pg_class s
+WHERE s.relkind = 'S';
+-- cross-reference each against: SELECT MAX(id) FROM <owning_table>;
+
+-- 4. Grants currently applied (verify parity with Oracle's user_tab_privs)
+SELECT grantee, table_name, privilege_type
+FROM information_schema.role_table_grants
+WHERE table_schema = 'public'
+ORDER BY grantee, table_name;
+
+-- 5. Empty-string vs NULL audit (verify Striim didn't collapse distinctness)
+SELECT table_name, column_name
+FROM information_schema.columns
+WHERE table_schema = 'public' AND data_type LIKE '%char%';
+-- then per flagged column:
+-- SELECT COUNT(*) FILTER (WHERE col = '') AS empties,
+--        COUNT(*) FILTER (WHERE col IS NULL) AS nulls
+-- FROM table_name;
+
+-- 6. Replication lag / slot status (Debezium + Striim slots)
+SELECT slot_name, active, restart_lsn,
+       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS lag_bytes
+FROM pg_replication_slots;
+
+-- 7. Constraint/index parity check (catch anything ora2pg skipped)
+SELECT conname, conrelid::regclass, contype
+FROM pg_constraint
+JOIN pg_namespace n ON n.oid = connamespace
+WHERE n.nspname = 'public';
```
