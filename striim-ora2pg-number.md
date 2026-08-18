## ON POSTGRES
> [!NOTE]
NUMERIC is exact, arbitrary-precision, and lossless — it can represent anything Oracle's NUMBER can, including scale>0 and values beyond ±9.2×10¹⁸.
BIGINT is a narrowing conversion: it silently assumes the column is always integer (scale=0) and always fits in 8 bytes. If the source NUMBER ever holds a decimal or a value >19 digits, BIGINT either errors on insert or (worse) already lost data during initial load.
Trade-off: BIGINT is faster and smaller (fixed 8 bytes vs. variable-length NUMERIC), which is why it's the "optimize later" target — but only after you've proven the actual data is integer-only and bounded. Doing it automatically per-run, inconsistently, is the actual problem here, not which type is "better" in isolation.

> [!IMPORTANT]
So ENV2 (BIGINT) is the one at overflow/precision risk — that's where to point your queries first.

```sql
-- ============================================================
-- 1) Confirm same table/column set exists in both schemas
-- ============================================================
SELECT
    coalesce(e1.table_name, e2.table_name)  AS table_name,
    coalesce(e1.column_name, e2.column_name) AS column_name,
    e1.data_type AS env1_type,
    e2.data_type AS env2_type
FROM (SELECT table_name, column_name, data_type
      FROM information_schema.columns
      WHERE table_schema = 'env1') e1
FULL OUTER JOIN (SELECT table_name, column_name, data_type
                 FROM information_schema.columns
                 WHERE table_schema = 'env2') e2
  ON e1.table_name = e2.table_name AND e1.column_name = e2.column_name
WHERE e1.data_type IS DISTINCT FROM e2.data_type
ORDER BY table_name, column_name;

-- ============================================================
-- 2) Full precision/scale detail for every NUMERIC column (env1)
--    and every BIGINT column (env2), side by side, for columns
--    that came from Oracle NUMBER
-- ============================================================
SELECT table_schema, table_name, column_name, data_type,
       numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema IN ('env1','env2')
  AND data_type IN ('numeric','bigint')
ORDER BY table_name, column_name, table_schema;

-- ============================================================
-- 3) Risk check: any NUMERIC column in env1 that actually holds
--    non-integer (scale > 0) values right now?
--    -> If yes, that column would BREAK or silently truncate
--       if it were ever cast to BIGINT (as env2 did).
--    Run per-table; template below, generate one per flagged column.
-- ============================================================
SELECT column_name, count(*) AS fractional_rows
FROM env1.<table_name>
WHERE <numeric_column> <> trunc(<numeric_column>)
GROUP BY column_name;

-- Simpler single-column version:
SELECT count(*) AS fractional_rows
FROM env1.<table_name>
WHERE <numeric_column> <> trunc(<numeric_column>);

-- ============================================================
-- 4) Risk check: any NUMERIC column in env1 whose values exceed
--    BIGINT range (i.e. would fail if env2-style mapping applied)
-- ============================================================
SELECT count(*) AS out_of_bigint_range
FROM env1.<table_name>
WHERE <numeric_column> > 9223372036854775807
   OR <numeric_column> < -9223372036854775808;

-- ============================================================
-- 5) Reverse check: has env2's BIGINT column ever thrown an
--    overflow/precision error on insert? Check Postgres logs
--    for this table (requires log_min_error_statement or similar).
--    Query pg_stat_database for cumulative error counts as a proxy:
-- ============================================================
SELECT datname, xact_rollback
FROM pg_stat_database
WHERE datname = current_database();

-- ============================================================
-- 6) Raw catalog-level precision/scale (bypasses information_schema
--    views in case of driver/version quirks) via pg_attribute
-- ============================================================
SELECT n.nspname AS schema, c.relname AS table_name, a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS full_type,
       CASE WHEN a.atttypmod > 0
            THEN ((a.atttypmod - 4) >> 16) & 65535
       END AS precision,
       CASE WHEN a.atttypmod > 0
            THEN (a.atttypmod - 4) & 65535
       END AS scale
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('env1','env2')
  AND a.attnum > 0 AND NOT a.attisdropped
  AND format_type(a.atttypid, a.atttypmod) LIKE ANY (ARRAY['numeric%','bigint%'])
ORDER BY c.relname, a.attname;
```

> [!NOTE]
Run query 1 first — it'll give you the exact list of mismatched columns to target with 3/4 against ENV1's live data. 
Any hit on query 3 or 4 is hard proof ENV2's BIGINT choice is unsafe for that column, independent of anything Striim-side.

## ON ORACLE
Run these against ORA1 and ORA2 for the same table/column list from your PG query 1.
```sql
-- ============================================================
-- 1) Catalog-level precision/scale for the affected columns,
--    both instances — this is the #1 suspect
-- ============================================================
SELECT table_name, column_name, data_type,
       data_precision, data_scale, data_length
FROM all_tab_columns
WHERE owner = 'YOUR_SCHEMA'
  AND table_name IN ('TABLE1','TABLE2', ...)   -- from PG mismatch list
ORDER BY table_name, column_name;

-- data_precision IS NULL AND data_scale IS NULL  -> unconstrained NUMBER
-- data_precision IS NULL AND data_scale = 0      -> NUMBER(*,0) variant
-- These ambiguous cases are exactly where driver/tool defaults diverge.

-- ============================================================
-- 2) Confirm DDL text is byte-identical between ORA1 and ORA2
--    (catches an untracked ALTER on one side)
-- ============================================================
SELECT dbms_metadata.get_ddl('TABLE', 'TABLE1', 'YOUR_SCHEMA') FROM dual;
-- run on both instances, diff the output

-- ============================================================
-- 3) Actual data profile — does the column ever hold a
--    non-integer or out-of-BIGINT-range value on either side?
-- ============================================================
SELECT
    COUNT(*)                                            AS total_rows,
    SUM(CASE WHEN <col> <> TRUNC(<col>) THEN 1 ELSE 0 END) AS fractional_rows,
    SUM(CASE WHEN <col> > 9223372036854775807
              OR <col> < -9223372036854775808 THEN 1 ELSE 0 END) AS out_of_bigint_range,
    MIN(<col>) AS min_val,
    MAX(<col>) AS max_val,
    MAX(LENGTH(TRUNC(ABS(<col>))))                      AS max_integer_digits
FROM YOUR_SCHEMA.TABLE1;
-- run on both ORA1 and ORA2 — if profiles differ, Striim's data-sampling
-- inference (if that's the path it uses) explains the divergence directly

-- ============================================================
-- 4) Instance/version/patch level — different ojdbc metadata
--    behavior can trace back to this
-- ============================================================
SELECT * FROM v$version;
SELECT instance_name, host_name, version, version_full FROM v$instance;

-- ============================================================
-- 5) NLS settings — can affect how numeric metadata is
--    reported/interpreted over JDBC in edge cases
-- ============================================================
SELECT parameter, value FROM nls_database_parameters
WHERE parameter LIKE 'NLS_NUMERIC%' OR parameter LIKE 'NLS_TERRITORY%';

-- ============================================================
-- 6) Was the column ever altered? (audits only go back as far
--    as retention/flashback allows — worth a quick check)
-- ============================================================
SELECT * FROM dba_tab_modifications
WHERE table_name = 'TABLE1' AND table_owner = 'YOUR_SCHEMA';
```

> [!NOTE]
Priority order: run #1 and #2 first — if data_precision/data_scale and DDL are identical across ORA1/ORA2, the divergence is 100% in Striim's tooling/config (driver version, app-level ColumnMap, or pre-existing target table), not the source. If they differ, you've found your root cause immediately and don't need to go further into Striim internals.
