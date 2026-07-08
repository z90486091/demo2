# Oracle → Postgres Migration: ora2pg (DDL) + Debezium (DML)

## Architecture Principle

| Concern | Owner | Enforcement |
|---|---|---|
| Schema (DDL) | **ora2pg** | Generates + applies all Postgres DDL. `schema.evolution: none` on the DBZ sink prevents it from ever creating/altering tables. |
| Data (DML) | **Debezium** | LogMiner captures row-level INSERT/UPDATE/DELETE from Oracle, streams via Kafka, sink writes to pre-existing Postgres tables. |
| Sink DB | **Read-only for humans** | No manual `CREATE`/`ALTER`/`INSERT`/`UPDATE` against Postgres, ever. All writes come from ora2pg (DDL) or the DBZ sink connector (DML). Verification is `SELECT`-only. |

This is a hard constraint, not a suggestion: if a Postgres table is
missing or a column is wrong, the fix goes back through ora2pg
regeneration — never a manual `ALTER TABLE` on the sink.

## Object Type → Tool Applicability

Not every Oracle object type is DBZ-relevant. Tables generate DML
events; everything else is DDL-only (ora2pg's job) or has no direct
Postgres/DBZ equivalent at all.

| Object Type | ora2pg (DDL) | Debezium (DML) |
|---|---|---|
| Tables | Yes | Yes — full CRUD |
| Composite PK / Identity / Virtual col / JSON / XMLType / TSTZ / Interval | Yes | Yes (as table columns) |
| Partitioned tables | Yes | Yes |
| Self-referencing FK | Yes | Yes (watch insert ordering) |
| Compressed tables | Yes (COMPRESS dropped, flagged) | Yes |
| Multi-column unique constraints | Yes | Yes |
| GTT (Global Temp Table) | Yes (→ pgtt extension) | **No** — session-scoped, never hits redo logs |
| Indexes (B-tree, unique, function-based) | Yes | N/A |
| Bitmap index | Yes (converted or dropped, flagged) | N/A |
| Views | Yes | N/A — read-only, no row events |
| Materialized views | Yes | **No** — refresh is a bulk internal op, not row DML |
| Synonyms | Yes (often flattened) | N/A |
| Sequences | Yes | N/A directly (consumed via table inserts only) |
| Triggers | Yes (manual rework likely) | N/A — DBZ sees only the resulting row change |
| Functions / Procedures / Packages | Yes (manual rework, packages hardest) | N/A — DML they *perform* is captured, the code itself is not |
| Object types / VARRAY / nested tables | Yes (→ composite type/JSONB/hstore, high rework) | Yes, if used as a table column — high serialization risk |
| DB links | **Manual** — no direct migration, needs `postgres_fdw`/`oracle_fdw` setup | N/A, and must be excluded from `table.include.list` (LogMiner can't mine remote redo) |
| Flashback/AS OF queries | N/A — Oracle-only feature | N/A |

## Prerequisites

- Existing POC stack running: `docker compose up -d` (Oracle, Kafka,
  Connect, Postgres, AKHQ)
- `ora2pg` service added to `docker-compose.yml`
- Postgres image built with `pgtt`, `orafce`, `xml2` extensions
  (stock `postgres:15` does not ship these — custom Dockerfile
  required, see prior extension notes)
- `oracle_source_ddl_dml.sql` and `oracle-source.json` /
  `postgres-sink.json` from this project

## Part 1 — Source Execution (Oracle FREEPDB1)

All of this runs against Oracle. Nothing here touches Postgres.

### 1.1 CDB-level setup (once)

```bash
docker exec -it debezium-poc-oracle-1 sqlplus / as sysdba
```

Run **Part A** of `oracle_source_ddl_dml.sql` (common user + grants,
`CDB$ROOT` context). Enable ARCHIVELOG mode if not already done.

### 1.2 PDB-level schema + data (once)

Still in the same sqlplus session:

```sql
ALTER SESSION SET CONTAINER = FREEPDB1;
```

Run **Part B** (all DDL: tables, GTT, indexes, views, MV, synonym,
triggers, functions, procedure, package, types) and **Part C** (DML)
from `oracle_source_ddl_dml.sql`.

### 1.3 Confirm objects exist

```sql
SELECT object_type, COUNT(*) FROM user_objects GROUP BY object_type;
SELECT table_name FROM user_tables ORDER BY table_name;
```

## Part 2 — Schema Migration (ora2pg → Postgres DDL)

ora2pg is the **only** thing allowed to write DDL to Postgres.

### 2.1 Export DDL from Oracle

```bash
docker exec -it debezium-poc-ora2pg-1 bash
ora2pg -t TABLE -c ora2pg.conf -o tables.sql
ora2pg -t VIEW -c ora2pg.conf -o views.sql
ora2pg -t SEQUENCE -c ora2pg.conf -o sequences.sql
ora2pg -t INDEX -c ora2pg.conf -o indexes.sql
ora2pg -t FUNCTION -c ora2pg.conf -o functions.sql
ora2pg -t PROCEDURE -c ora2pg.conf -o procedures.sql
ora2pg -t PACKAGE -c ora2pg.conf -o packages.sql
ora2pg -t TYPE -c ora2pg.conf -o types.sql
ora2pg -t SYNONYM -c ora2pg.conf -o synonyms.sql
ora2pg -t TRIGGER -c ora2pg.conf -o triggers.sql
```

Review each generated file for `-- WARNING` / `-- FIXME` comments —
these mark objects ora2pg could not translate automatically
(bitmap indexes, VARRAY/nested tables, packages, COMPRESS clauses).

### 2.2 Apply DDL to Postgres — via ora2pg only

```bash
ora2pg -t TABLE -c ora2pg.conf
ora2pg -t VIEW -c ora2pg.conf
ora2pg -t SEQUENCE -c ora2pg.conf
ora2pg -t INDEX -c ora2pg.conf
ora2pg -t FUNCTION -c ora2pg.conf
ora2pg -t PROCEDURE -c ora2pg.conf
ora2pg -t TYPE -c ora2pg.conf
```

`ora2pg.conf` holds the Postgres connection target — this executes
DDL directly, no manual `psql` step, no hand-edited SQL applied by a
person.

Do **not** run `ora2pg -t TABLE` with `--data` here — that would
pre-populate rows outside of Debezium, defeating the DML-via-DBZ
requirement. DDL-only passes.

## Part 3 — Data Migration (Debezium DML)

### 3.1 Update source connector table list

Edit `oracle-source.json` — `table.include.list` must match every
table ora2pg just created (see reference list at the bottom of
`oracle_source_ddl_dml.sql`). Exclude GTT, views, MV, synonyms.

### 3.2 Deploy connectors

```bash
curl -X DELETE http://localhost:8083/connectors/oracle-source-connector
curl -X POST -H "Content-Type: application/json" \
  --data @oracle-source.json http://localhost:8083/connectors

curl -X POST -H "Content-Type: application/json" \
  --data @postgres-sink.json http://localhost:8083/connectors
```

`postgres-sink.json` must have `"schema.evolution": "none"` —
enforces that DBZ never creates/alters tables; it only writes rows
into what ora2pg already built.

### 3.3 Check connector health

```bash
curl http://localhost:8083/connectors/oracle-source-connector/status
curl http://localhost:8083/connectors/postgres-sink-connector/status
```

Or visually via AKHQ: `http://localhost:8080`

## Part 4 — Sink Verification (Postgres) — READ-ONLY

No `CREATE`, `ALTER`, `INSERT`, `UPDATE`, `DELETE` against Postgres
past this point. `SELECT` only.

### 4.1 Confirm schema landed (ora2pg's work)

```bash
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db -c "\dt"
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db -c "\dv"
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db -c "\ds"
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db -c "\df"
```

Compare table/column list against Oracle source
(`user_tables`/`user_tab_columns`) — this validates ora2pg, not DBZ.

### 4.2 Confirm data landed (Debezium's work)

```bash
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT * FROM customers ORDER BY id;"
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT * FROM orders ORDER BY id;"
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT * FROM order_items ORDER BY order_id, line_no;"
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT * FROM org_chart ORDER BY id;"
```

Row counts should match Oracle post-DML state:

```sql
-- run on Oracle side for comparison
SELECT COUNT(*) FROM customers;
SELECT COUNT(*) FROM orders;      -- excludes CANCELLED (deleted)
SELECT COUNT(*) FROM order_items;
```

### 4.3 Confirm CRUD propagation end-to-end

On Oracle:

```sql
UPDATE customers SET email = 'test-verify@test.com' WHERE id = 1;
COMMIT;
```

On Postgres (wait a few seconds for stream lag):

```bash
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT email FROM customers WHERE id = 1;"
```

Should reflect `test-verify@test.com` — proves DML flowed through
LogMiner → Kafka → sink without any manual Postgres write.

### 4.4 Confirm objects with no DBZ path are absent (as expected)

```bash
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "\dt" | grep -i staging_orders
```

`staging_orders` (GTT source-side) should NOT have live replicated
rows in Postgres — only its structure exists (via ora2pg → pgtt),
data is intentionally never streamed.

## Known Failure Points (route back to ora2pg, never patch Postgres directly)

- Missing sink table → `postgres-sink-connector` status shows FAILED,
  "relation does not exist" → re-run `ora2pg -t TABLE` for that table.
- Column type mismatch (e.g. JSON vs JSONB, VARRAY vs hstore) → sink
  write fails → adjust `ora2pg.conf` type mapping, regenerate DDL.
- New Oracle column added later → `schema.evolution: none` means sink
  fails on that field → re-run ora2pg DDL export/apply for that table
  BEFORE resuming DBZ DML for it.
