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

## File Tree

```
.
├── docker-compose.yml
├── Dockerfile.connect
├── drivers
│   └── ojdbc8.jar
├── init-scripts                        # runs AUTOMATICALLY, first container init only
│   └── 01-create-user.sql              # c##dbzuser + grants (CDB$ROOT)
├── ora2pg-config
│   ├── ora2pg.conf
│   ├── tables.sql / views.sql / mviews.sql / sequences.sql
│   ├── functions.sql / procedures.sql / packages.sql / types.sql
│   ├── synonyms.sql / triggers.sql / grants.sql
│   └── (generated output/log files)
├── oracle-source.json                  # Debezium source connector config
├── postgres-sink.json                  # Debezium sink connector config
└── scripts                             # run MANUALLY, in order, after container is healthy
    ├── enable-archivelog.sql           # ARCHIVELOG + supplemental logging (CDB level)
    └── create-schema+seed-data.sql     # Oracle-side schema + seed DML (PDB level)
```

## Why `enable-archivelog.sql` and `create-schema+seed-data.sql` Are Manual, Not Init Scripts

`gvenzl/oracle-free` supports two hooks:

- `/container-entrypoint-initdb.d` — runs automatically, once, on first
  database initialization only. Skipped entirely on any restart of an
  already-initialized database.
- `/container-entrypoint-startdb.d` — runs automatically on every
  container start.

`enable-archivelog.sql` issues `SHUTDOWN IMMEDIATE` / `STARTUP MOUNT`
against the instance. Running a shutdown/restart cycle from *inside*
an automated init-hook risks conflicting with the entrypoint's own
startup lifecycle tracking (it may hang, or later init scripts may run
against a database that's mid-restart). This has not been proven safe
in this environment, so it stays a manual, explicit step.

`create-schema+seed-data.sql` depends on `c##dbzuser` already existing
(from `01-create-user.sql`) and logically depends on ARCHIVELOG +
supplemental logging being active first, for ordering consistency with
what Debezium will capture going forward. Keeping it manual keeps the
whole sequence linear and inspectable rather than racing against
`initdb.d` timing.

## Object Type → Tool Applicability

| Object Type | ora2pg (DDL) | Debezium (DML) |
|---|---|---|
| Tables | Yes | Yes — full CRUD |
| Composite PK / Identity / Virtual col / TSTZ / Interval | Yes | Yes (as table columns) |
| Native Oracle `JSON` type | Yes | **No** — `ojdbc11-21.15.0.0` driver doesn't implement `getObject()` for `T4CJsonAccessor` (`Invalid column type` on snapshot). Fixable: newer driver build, or store as `CLOB CHECK (col IS JSON)` instead of native `JSON`. |
| Object types (`CREATE TYPE ... AS OBJECT`) / VARRAY / nested tables | Yes (→ composite type/JSONB/hstore, high rework) | **No — hard connector limitation.** Debezium's own docs: *"At this time, you cannot use the Debezium Oracle connector with any of these user-defined types."* Not a bug, not version-specific, no config fixes it. Only path if capture is required: flatten to plain columns / normalize to a child table in Oracle before CDC. |
| Partitioned tables | Yes | Yes |
| Self-referencing FK | Yes | Yes (watch insert ordering) |
| Compressed tables | Yes (COMPRESS dropped, flagged) | Yes |
| Multi-column unique constraints | Yes | Yes, only if a PK also exists (see Known Issues) |
| GTT (Global Temp Table) | Yes (→ pgtt extension) | **No** — session-scoped, never hits redo logs |
| Indexes (B-tree, unique, function-based) | Yes | N/A |
| Bitmap index | Yes (converted or dropped, flagged) | N/A |
| Views | Yes | N/A — read-only, no row events |
| Materialized views | Yes | **No** — refresh is a bulk internal op, not row DML. Debezium's initial snapshot captures schema for MVs regardless of scope; the underlying storage table can still surface as a real Kafka topic even when excluded from `table.include.list` — must be explicitly added to `table.exclude.list` to actually stop it. |
| Synonyms | Yes (often flattened) | N/A |
| Sequences | Yes | N/A directly (consumed via table inserts only) |
| Triggers | Yes (manual rework likely) | N/A — DBZ sees only the resulting row change |
| Functions / Procedures / Packages | Yes (manual rework, packages hardest) | N/A — DML they *perform* is captured, the code itself is not |
| DB links | **Manual** — no direct migration, needs `postgres_fdw`/`oracle_fdw` setup | N/A, and must be excluded from `table.include.list` (LogMiner can't mine remote redo) |
| Flashback/AS OF queries | N/A — Oracle-only feature | N/A |

## Current Exclusion List

Both connector configs must match this list exactly. Six tables/views
excluded, for four distinct reasons:

```
C##DBZUSER.USER_ROLES        — no primary key
C##DBZUSER.EVENTS_LOG        — no primary key
C##DBZUSER.CUSTOMER_PREFS    — native JSON, driver can't read it (fixable)
C##DBZUSER.CUSTOMER_ADDRESSES — object type (STRUCT), hard connector limitation
C##DBZUSER.CUSTOMER_PHONES   — VARRAY, hard connector limitation
C##DBZUSER.MV_CUSTOMER_TOTALS — materialized view backing table, not real DML
```

`oracle-source.json`:
```json
"table.exclude.list": "C##DBZUSER\\.USER_ROLES,C##DBZUSER\\.EVENTS_LOG,C##DBZUSER\\.CUSTOMER_PREFS,C##DBZUSER\\.CUSTOMER_ADDRESSES,C##DBZUSER\\.CUSTOMER_PHONES,C##DBZUSER\\.MV_CUSTOMER_TOTALS"
```

`postgres-sink.json` only needs `USER_ROLES`/`EVENTS_LOG` excluded —
the other four never produce topics once excluded at the source, so
excluding them again here is redundant but harmless:
```json
"topics.regex": "oracle_cdc\\.C__DBZUSER\\.(?!USER_ROLES$|EVENTS_LOG$).*"
```

## Full Sequence — After `docker compose down -v --remove-orphans`

### 1. Bring up Oracle only, wait for healthy

```bash
docker compose up -d oracle
docker compose logs -f oracle   # wait for "DATABASE IS READY TO USE!"
```

### 2. `01-create-user.sql` runs automatically

Confirm it actually ran:

```bash
docker compose logs oracle | grep -i "01-create-user"
```

### 3. Manually enable ARCHIVELOG + supplemental logging

```bash
docker exec -i debezium-poc-oracle-1 sqlplus / as sysdba < scripts/enable-archivelog.sql
```

Confirm:

```bash
docker exec -i debezium-poc-oracle-1 sqlplus / as sysdba
```
```sql
ALTER SESSION SET CONTAINER = CDB$ROOT;

-- expect YES
SELECT supplemental_log_data_min FROM v$database;

-- expect "Database log mode: Archive Mode"
ARCHIVE LOG LIST;
exit;
```

### 4. Manually create schema + seed data

```bash
docker exec -i debezium-poc-oracle-1 sqlplus / as sysdba < scripts/create-schema+seed-data.sql
```

Confirm — **do this before moving on, zero rows here means the script
did not actually run and nothing downstream will work**:

```sql
docker exec -i debezium-poc-oracle-1 sqlplus / as sysdba
ALTER SESSION SET CONTAINER = FREEPDB1;
SELECT object_type, COUNT(*) FROM all_objects WHERE owner = 'C##DBZUSER' GROUP BY object_type;
SELECT table_name FROM all_tables WHERE owner = 'C##DBZUSER' ORDER BY table_name;
exit;
```

### 5. Bring up the rest of the stack

```bash
docker compose up -d

# cd converters
# mvn clean package

#copy custom json converter into connect container
# docker cp target/oracle-json-converter-1.0.jar debezium-poc-connect-1:/kafka/connect/debezium-connector-oracle/
# docker compose restart connect
```

### 6. Export + apply DDL via ora2pg (ora2pg owns all Postgres DDL)

```bash
docker exec -it debezium-poc-ora2pg-1 bash

cd /data
ora2pg -t TABLE -c ora2pg.conf -o tables.sql
ora2pg -t VIEW -c ora2pg.conf -o views.sql
ora2pg -t MVIEW -c ora2pg.conf -o mviews.sql
ora2pg -t SEQUENCE -c ora2pg.conf -o sequences.sql
ora2pg -t FUNCTION -c ora2pg.conf -o functions.sql
ora2pg -t PROCEDURE -c ora2pg.conf -o procedures.sql
ora2pg -t PACKAGE -c ora2pg.conf -o packages.sql
ora2pg -t TYPE -c ora2pg.conf -o types.sql
ora2pg -t SYNONYM -c ora2pg.conf -o synonyms.sql
ora2pg -t TRIGGER -c ora2pg.conf -o triggers.sql
ora2pg -t GRANT -c ora2pg.conf -o grants.sql
```

Sanity-check the exports actually have content before applying —
macOS extended attributes (`com.apple.macl`) on the `ora2pg/` bind
mount have silently produced empty `.sql` files before:

```bash
wc -l tables.sql sequences.sql types.sql
```
If any come back `0`, run `xattr -rc ../ora2pg` (or wherever the
bind-mounted host directory is) and re-export before proceeding.

Review each file for `-- WARNING` / `-- FIXME` comments — these mark
objects ora2pg could not translate automatically (bitmap indexes,
VARRAY/nested tables, packages, COMPRESS clauses).

Apply, in dependency order:

```bash
for f in sequences.sql types.sql tables.sql views.sql mviews.sql \
         functions.sql procedures.sql packages.sql synonyms.sql \
         triggers.sql grants.sql; do
  echo "Loading $f..."
  PGPASSWORD=postgres psql -h postgres -U postgres -d target_db -f "$f"
done
exit
```

**Do not** run `ora2pg -t TABLE` with `--data` — that pre-populates
rows outside of Debezium, defeating the DML-via-DBZ requirement.
DDL-only passes.

Confirm before moving on — **do not deploy connectors until this
shows every table**, the sink cannot write to tables that don't exist:

```bash
docker exec debezium-poc-postgres-1 psql -U postgres -d target_db -c "\dt"
```

### 7. Deploy Debezium connectors

Confirm `oracle-source.json`/`postgres-sink.json` match the exclusion
list above before deploying:

```bash
curl -X POST -H "Content-Type: application/json" \
  --data @oracle-source.json http://localhost:8083/connectors

curl -X POST -H "Content-Type: application/json" \
  --data @postgres-sink.json http://localhost:8083/connectors
```

### 8. Check connector health

```bash
curl -s http://localhost:8083/connectors/oracle-source-connector/status | jq .
curl -s http://localhost:8083/connectors/postgres-sink-connector/status | jq .
```

Or visually via AKHQ: `http://localhost:8080`

### 9. Task/offset verification — mandatory, not optional

**A `RUNNING` sink status does not mean it is consuming.** Observed
repeatedly in this project: the sink task joins its Kafka consumer
group successfully, is assigned partitions, but never actually calls
`poll()` — it sits idle indefinitely with zero offset commits and no
error, indistinguishable from healthy via `/status` alone. Waiting
longer does not fix this; only an explicit task restart does.

```bash
sleep 15
docker compose exec kafka /kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 --describe --group connect-postgres-sink-connector
```

If **any** `CURRENT-OFFSET` shows `-` instead of a number, the sink is
stuck — restart the task and re-check:

```bash
curl -X POST http://localhost:8083/connectors/postgres-sink-connector/tasks/0/restart
sleep 10
docker compose exec kafka /kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 --describe --group connect-postgres-sink-connector
```

`CURRENT-OFFSET` should now match `LOG-END-OFFSET` on every topic
before proceeding to verification.

### 10. Sink Verification (Postgres) — READ-ONLY

No `CREATE`, `ALTER`, `INSERT`, `UPDATE`, `DELETE` against Postgres
past this point. `SELECT` only.

#### 10.1 Confirm schema landed (ora2pg's work)

```bash
docker exec debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "\dt" -c "\dv" -c "\dm" -c "\ds" -c "\di" -c "\df" -c "\dT" -c "\d+ orders" \
  -c "SELECT trigger_name, event_object_table FROM information_schema.triggers;" \
  -c "SELECT conname, conrelid::regclass FROM pg_constraint WHERE contype='f';"
```

#### 10.2 Confirm data landed (Debezium's work)

```bash
docker exec debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT * FROM customers ORDER BY id;" \
  -c "SELECT * FROM orders ORDER BY id;" \
  -c "SELECT * FROM audit_log ORDER BY id;" \
  -c "SELECT * FROM order_totals ORDER BY id;" \
  -c "SELECT * FROM customer_prefs;"
```

If this shows zero rows despite step 9 passing, re-check step 9 — it
means offsets regressed or the task died again; don't proceed further
until `CURRENT-OFFSET` == `LOG-END-OFFSET` and this query shows data.

#### 10.3 Confirm CRUD propagation end-to-end

On Oracle — connect as `c##dbzuser`, not `sys` (an unqualified table
name under a `sqlplus / as sysdba` session resolves against `SYS`'s
own schema and will throw `ORA-00942: table or view does not exist`):

```bash
docker exec -i debezium-poc-oracle-1 sqlplus c##dbzuser/oracle@//localhost:1521/FREEPDB1
```
```sql
UPDATE customers SET email = 'test-verify@test.com' WHERE id = 1;
COMMIT;
```

Or, staying in a `sysdba` session, qualify the table explicitly:

```sql
ALTER SESSION SET CONTAINER = FREEPDB1;
UPDATE C##DBZUSER.CUSTOMERS SET email = 'test-verify@test.com' WHERE id = 1;
COMMIT;
```

On Postgres (wait a few seconds for stream lag — expect ~2-5s at this
data volume once both connectors are confirmed healthy per step 9):

```bash
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT email FROM customers WHERE id = 1;"
```

### 11. Support for JSON cols
Tables containing columns with data type JSON are skipped by LogMiner
unless you have xstream, GoldenGate or other similar enterprise licence

```bash
SQL> select * from customer_prefs;

	ID CUSTOMER_ID
---------- -----------
PREFS
--------------------------------------------------------------------------------
	 1	     1
{"theme":"dark","notifications":true}
```

```bash
show logminer unknown operation here
```

```bash
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db
psql (15.17 (Debian 15.17-1.pgdg13+1))
Type "help" for help.

target_db=# select * from customer_prefs;
 id | customer_id | prefs
----+-------------+-------
(0 rows)

target_db=#
```

#### Non-LogMiner approach

~~> ora2pg.conf patch~~

~~>> `DATA_TYPE JSON:TEXT`~~

IMPORTANT: Deploy kafka jdbc source and sink connector plugin jar ver 10.9.3

```
docker compose exec -u root connect sh -c "
  microdnf -y install tar gzip && \
  curl -L http://client.hub.confluent.io/confluent-hub-client-latest.tar.gz \
  -o /tmp/hub.tar.gz && \
  mkdir -p /opt/confluent-hub && \
  tar -xzf /tmp/hub.tar.gz -C /opt/confluent-hub && \
  /opt/confluent-hub/bin/confluent-hub install \
  --no-prompt confluentinc/kafka-connect-jdbc:10.9.3 \
  --component-dir /kafka/connect/ \
  --worker-configs /dev/null && \
  rm -rf /tmp/hub.tar.gz
"
```

~~docker compose exec -u root connect sh -c "
/opt/confluent-hub/bin/confluent-hub install \
--no-prompt confluentinc/kafka-connect-jdbc:10.9.3 \
--component-dir /kafka/connect/ \
--worker-configs /dev/null
"~~


`docker compose restart connect`

Filtered list of relevant plugins

```
curl -s http://localhost:8083/connector-plugins | grep -i jdbc
[
  {
    "class":"io.confluent.connect.jdbc.JdbcSinkConnector",
    "type":"sink",
    "version":"10.9.3"
  },
  {
    "class":"io.debezium.connector.jdbc.JdbcSinkConnector",
    "type":"sink",
    "version":"3.4.2.Final"
  },
  {
    "class":"io.confluent.connect.jdbc.JdbcSourceConnector",
    "type":"source",
    "version":
    "10.9.3"
  },
  {
    "class":"io.debezium.connector.oracle.OracleConnector",
    "type":"source",
    "version":"3.4.2.Final"
  },
  {
    "class":"io.debezium.connector.postgresql.PostgresConnector",
    "type":"source",
    "version":"3.4.3.Final"
  }
]
```

#### 11.1 Create new source and sink for EACH db table in source which has a JSON datatype column

```json
{
  "name": "jdbc-prefs-source",
  "config": {
    "connector.class": "io.confluent.connect.jdbc.JdbcSourceConnector",
    "connection.url": "jdbc:oracle:thin:@oracle:1521/FREEPDB1",
    "connection.user": "c##dbzuser",
    "connection.password": "oracle",
    "query": "SELECT ID, CUSTOMER_ID, JSON_SERIALIZE(PREFS RETURNING VARCHAR2(4000)) as PREFS FROM C##DBZUSER.CUSTOMER_PREFS",
    "mode": "bulk",
    "topic.prefix": "jdbcoracle__customer_prefs"    
  }
}
```

```json
{
  "name": "jdbc-prefs-sink",
  "config": {
    "connector.class": "io.confluent.connect.jdbc.JdbcSinkConnector",
    "topics": "jdbcoracle__customer_prefs",
    "connection.url": "jdbc:postgresql://host.docker.internal:5432/target_db?stringtype=unspecified",
    "connection.user": "postgres",
    "connection.password": "postgres",
    "auto.create": "true",
    "insert.mode": "upsert",
    "pk.mode": "record_value",
    "pk.fields": "ID",
    "table.name.format": "customer_prefs",
    "quote.sql.identifiers": "never"
  }
}
```
#### 11.2 Deploy new source and sink
```sh
curl -X POST -H "Content-Type: application/json" -d @jdbc-prefs-source.json \
http://localhost:8083/connectors
curl -X POST -H "Content-Type: application/json" -d @jdbc-prefs-sink.json \
http://localhost:8083/connectors
```
#### 11.3 Check status of new source and sink
```sh
curl -s http://localhost:8083/connectors/jdbc-prefs-source/status | jq
curl -s http://localhost:8083/connectors/jdbc-prefs-sink/status | jq
```
#### 11.4 Delete new source and sink
```sh
curl -X DELETE http://localhost:8083/connectors/jdbc-prefs-source
curl -X DELETE http://localhost:8083/connectors/jdbc-prefs-sink
```
> Note: To redeploy, do 11.4 and 11.1, then check 11.3


#### 11.5 Review data landed in sink
> Original data
```
target_db=# select * from customer_prefs;
 id | customer_id |                 prefs
----+-------------+---------------------------------------
  1 |           1 | {"theme":"dark","notifications":true}
(1 row)

target_db=#
```
> Insert new data
```sql
SQL> insert into customer_prefs values(2,2, '{}');

1 row created.

SQL> commit;

Commit complete.

SQL> select * from customer_prefs;

	ID CUSTOMER_ID
---------- -----------
PREFS
--------------------------------------------------------------------------------
	 1	     1
{"theme":"dark","notifications":true}

	 2	     2
{}


SQL> select id from customers;

	ID
----------
	 1
	 2
	 3
```

```sql
target_db=# select * from customer_prefs;
 id | customer_id |                 prefs
----+-------------+---------------------------------------
  1 |           1 | {"theme":"dark","notifications":true}
  2 |           2 | {}
(2 rows)
```

> Update existing data
```sql
SQL> update customer_prefs set customer_id=2 where id=2;

1 row updated.

SQL> commit;

Commit complete.

SQL> select * from customer_prefs;

	ID CUSTOMER_ID
---------- -----------
PREFS
--------------------------------------------------------------------------------
	 1	     1
{"theme":"dark","notifications":true}

	 2	     2
{}

SQL> desc customer_prefs;
 Name					   Null?    Type
 ----------------------------------------- -------- ----------------------------
 ID					       NOT NULL NUMBER
 CUSTOMER_ID					    NUMBER
 PREFS						        JSON
```

```sql
target_db=# select * from customer_prefs;
 id | customer_id |                 prefs
----+-------------+---------------------------------------
  1 |           1 | {"theme":"dark","notifications":true}
  2 |           2 | {}
(2 rows)

target_db=# \d customer_prefs
             Table "public.customer_prefs"
   Column    |  Type  | Collation | Nullable | Default
-------------+--------+-----------+----------+---------
 id          | bigint |           | not null |
 customer_id | bigint |           |          |
 prefs       | json   |           |          |
Indexes:
    "customer_prefs_pkey" PRIMARY KEY, btree (id)
Foreign-key constraints:
    "sys_c008665" FOREIGN KEY (customer_id) REFERENCES customers(id)
```


> Delete data

>> Needs a "new" _source_ and _sink_ for **shadow** table based tracking _(no LogMiner)_

Create a new **shadow** table + trigger in oracle source for tracking deletes, sync it to Postgres via JDBC, and use a Postgres trigger to execute the delete.

- Kafka Source Connector:
Deploy a new oracle source connector to ingest the delete logs:

```json
{
  "name": "jdbc-deletes-source",
  "config": {
    "connector.class": "io.confluent.connect.jdbc.JdbcSourceConnector",
    "connection.url": "jdbc:oracle:thin:@oracle:1521/FREEPDB1",
    "connection.user": "c##dbzuser",
    "connection.password": "oracle",
    "schema.pattern": "C##DBZUSER",
    "table.types": "TABLE",
    "table.whitelist": "C##DBZUSER.CUSTOMER_PREFS_DEL",
    "mode": "timestamp",
    "timestamp.column.name": "DEL_TIME",
    "validate.non.null": "false",
    "topic.prefix": "oracle_deletes_",
    "poll.interval.ms": "5000"
  }
}
```

- DDL for **shadow** tracking table in Oracle source
```sql
CREATE TABLE customer_prefs_del (
  ID NUMBER,
  DEL_TIME TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE OR REPLACE TRIGGER trg_prefs_del
AFTER DELETE ON customer_prefs
FOR EACH ROW
BEGIN
  INSERT INTO customer_prefs_del(ID) VALUES (:old.ID);
END;
/
```

- Kafka Sink Connector:
Deploy a new postgres sink connector to ingest the delete logs:

```json
{
  "name": "jdbc-deletes-sink",
  "config": {
    "connector.class": "io.confluent.connect.jdbc.JdbcSinkConnector",
    "tasks.max": "1",
    "topics": "oracle_deletes_CUSTOMER_PREFS_DEL",
    "connection.url": "jdbc:postgresql://postgres:5432/target_db",
    "connection.user": "postgres",
    "connection.password": "postgres",
    "insert.mode": "insert",
    "table.name.format": "oracle_deletes_customer_prefs_del",
    "auto.create": "false",
    "transforms": "lowercaseFields",
    "transforms.lowercaseFields.type": "org.apache.kafka.connect.transforms.ReplaceField$Value",
    "transforms.lowercaseFields.renames": "ID:id,DEL_TIME:del_time"
  }
}
```
> 1 SMT for lowercase transforms

- DDL for **shadow** table tracking postgres sink

```sql
CREATE TABLE oracle_deletes_customer_prefs_del (
  id bigint, 
  del_time timestamp
);

CREATE OR REPLACE FUNCTION execute_sink_delete() 
RETURNS TRIGGER AS $$
BEGIN
  DELETE FROM customer_prefs WHERE id = NEW.id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pg_delete 
AFTER INSERT ON oracle_deletes_customer_prefs_del
FOR EACH ROW EXECUTE FUNCTION execute_sink_delete();
```
> Remember to redeploy (`DELETE+POST`) or patch (`PUT`) existing postgres-sink-connector with this fix to ignore the source shadow table:

`"topics.regex": "oracle_cdc\\.C__DBZUSER\\.(?!USER_ROLES$|EVENTS_LOG$|CUSTOMER_PREFS_DEL$).*",`

>> p.s. The table in postgres sink is `oracle_deletes_customer_prefs_del`

Deploy source and sink connectors:
```sh
curl -X POST -H "Content-Type: application/json" -d @jdbc-del-source.json \
http://localhost:8083/connectors

curl -X POST -H "Content-Type: application/json" -d @jdbc-del-sink.json \
http://localhost:8083/connectors
```

Check status:
```sh
curl -s localhost:8083/connectors/jdbc-deletes-source/status | jq
curl -s localhost:8083/connectors/jdbc-deletes-sink/status | jq
```

Delete source and sink connectors:
```sh
curl -X DELETE http://localhost:8083/connectors/jdbc-deletes-source
curl -X DELETE http://localhost:8083/connectors/jdbc-deletes-sink
```

Verification:
```sql
SQL> delete from customer_prefs where id=2;

1 row deleted.

SQL> commit;

Commit complete.

SQL> select * from customer_prefs_del;

	ID
----------
DEL_TIME
---------------------------------------------------------------------------
	 2
15-JUL-26 05.53.02.260089 AM
```

```sh
target_db=# select * from customer_prefs;
 id | customer_id |                 prefs
----+-------------+---------------------------------------
  1 |           1 | {"theme":"dark","notifications":true}
(1 row)

target_db=# select * from oracle_deletes_customer_prefs_del;
 id |        del_time
----+------------------------
  2 | 2026-07-15 05:53:02.26
(1 row)
```

To redeploy, delete the connector(s) using curl DELETE as shown above and create them again using curl POST as shown above
## Known Issues (Resolved / Tracked)

| Table | Issue | Resolution |
|---|---|---|
| `audit_log` | `ID` was `GENERATED ALWAYS AS IDENTITY` — Postgres rejects explicit CDC-written values with "cannot insert a non-DEFAULT value" | **Fixed at source**: `create-schema+seed-data.sql` now defines it as `GENERATED BY DEFAULT AS IDENTITY`, which accepts explicit values with no special clause. Standard sink connector handles it normally — no exclusion, no n8n needed. |
| `order_totals` | `TOTAL` was Oracle `VIRTUAL` (computed) — LogMiner never writes virtual column values to redo logs, always ships `null` | **Fixed at source**: now a plain stored `NUMBER` column, backfilled explicitly. Phase 1 (now): replicated as a normal writable column. Phase 2 (at cutover, source decommissioned): `DROP`/re-`ADD` as `GENERATED ALWAYS AS (price * qty) STORED` in Postgres. |
| `user_roles`, `events_log` | No primary key (`user_roles` has only a unique constraint; `events_log` has neither) — sink's `primary.key.mode: record_key` has nothing to build a key from, fails with "cannot have null schema" | **Unresolved** — excluded from both `table.include.list` (source) and `topics.regex` (sink). Needs a data-modeling decision: add a real PK, or handle as keyless/append-only via a different mechanism. |
| `customer_prefs` | Native Oracle `JSON` column — snapshot throws `Invalid column type: getOracleObject not implemented for class oracle.jdbc.driver.T4CJsonAccessor`, aborting the **entire** snapshot transaction (not just this table) | **Excluded, fixable later** — driver bug in bundled `ojdbc11-21.15.0.0`. Fix path: newer driver build with OSON support, or convert column to `CLOB CHECK (col IS JSON)` (legacy JSON storage), which Debezium reads as a plain string. |
| `customer_addresses` (object type `STRUCT`), `customer_phones` (`VARRAY`) | Debezium's Oracle connector does not support user-defined types at all — confirmed directly from Debezium's own docs, unchanged across every version checked: *"you cannot use the Debezium Oracle connector with any of these user-defined types"* | **Excluded, hard limitation, not fixable via config/driver/version.** Only real fix if this data must be captured: flatten `address_type` into plain columns, normalize `phone_list_type` into a child table — schema redesign at the Oracle source, not a migration-tooling fix. |
| `mv_customer_totals` | Materialized view backing table — Debezium's snapshot captures schema for *every* table in the database regardless of `table.include.list` scope (documented behavior), and this MV's table surfaced as a real Kafka topic despite never being intentionally included, causing sink key errors | **Excluded explicitly** in `table.exclude.list` — scoping alone via `include.list` was not sufficient to keep it out. |
| `staging_orders` | Global Temporary Table — LogMiner cannot capture session-scoped data (never written to redo) | Excluded from `table.include.list` by design. Structure only migrates via ora2pg (`pgtt` extension); no row data is ever expected in Postgres. |
| Sink task silently idle after deploy | Task joins consumer group, gets partition assignment, but never calls `poll()` — zero offset commits, no error, `/status` reports `RUNNING` throughout. Not a wait-it-out issue; observed to persist 10+ minutes with no self-recovery. | **Always run step 9** (task/offset verification) after every connector deploy. Fix is an explicit `POST .../tasks/0/restart` — root cause not fully understood, treat as a standard post-deploy step, not an edge case. |

## Known Failure Points (route back to ora2pg, never patch Postgres directly)

- Missing sink table → `postgres-sink-connector` status shows FAILED,
  "relation does not exist" → re-run `ora2pg -t TABLE` for that table.
- Column type mismatch (e.g. JSON vs JSONB, VARRAY vs hstore) → sink
  write fails → adjust `ora2pg.conf` type mapping, regenerate DDL.
- New Oracle column added later → `schema.evolution: none` means sink
  fails on that field → re-run ora2pg DDL export/apply for that table
  BEFORE resuming DBZ DML for it.
- Identity/virtual columns on any future table → check
  `user_tab_identity_cols` / `all_tab_cols.virtual_column` on the
  Oracle source **before** first CDC run — fix at the Oracle DDL level
  (per `audit_log`/`order_totals` pattern above), not downstream.
- Native `JSON`, object types (`STRUCT`), or `VARRAY`/nested tables on
  any future table → check column types before adding to
  `table.include.list` — JSON is fixable (driver/CLOB workaround),
  object types/VARRAY are not (Debezium hard limitation, flatten at
  the Oracle source instead).
- Sink connector `RUNNING` but Postgres stays empty → do not wait,
  check consumer group offsets (step 9) and restart the task.
