# Oracle → Kafka → Postgres CDC Pipeline (Debezium)

End-to-end change data capture pipeline using Debezium LogMiner to stream
Oracle changes through Kafka into Postgres.

## Stack

| Component | Image/Version |
|---|---|
| Zookeeper | quay.io/debezium/zookeeper:2.6 |
| Kafka | quay.io/debezium/kafka:2.6 |
| Oracle | gvenzl/oracle-free:23-slim (ships Oracle 26ai) |
| Postgres | postgres:15 |
| Kafka Connect | quay.io/debezium/connect:3.4 |
| Debezium Oracle connector | 3.4.2.Final |
| Debezium JDBC sink connector | 3.4.2.Final |

## Prerequisites

- Docker + Docker Compose
- `curl`
- Ports free: 1521, 2181, 5432, 8083, 9092

## 1. Project Files

```
debezium-poc/
├── docker-compose.yml
├── Dockerfile.connect
├── init-scripts/
│   └── 01-create-user.sql
├── oracle-source.json
└── postgres-sink.json
```

### docker-compose.yml

```yaml
services:
  zookeeper:
    image: quay.io/debezium/zookeeper:2.6
    ports:
      - 2181:2181
  kafka:
    image: quay.io/debezium/kafka:2.6
    ports:
      - 9092:9092
    environment:
      - ZOOKEEPER_CONNECT=zookeeper:2181
  oracle:
    image: gvenzl/oracle-free:23-slim
    ports:
      - 1521:1521
    environment:
      - ORACLE_PASSWORD=oracle
    volumes:
      - oracle-data:/opt/oracle/oradata
      - ./init-scripts:/container-entrypoint-initdb.d
  postgres:
    image: postgres:15
    ports:
      - 5432:5432
    environment:
      - POSTGRES_DB=target_db
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
  connect:
    build:
      context: .
      dockerfile: Dockerfile.connect
    ports:
      - 8083:8083
    environment:
      - CLASSPATH=/kafka/connect/debezium-connector-oracle/ojdbc11-23.6.0.24.10.jar:/kafka/connect/debezium-connector-oracle/orai18n-23.6.0.24.10.jar
      - BOOTSTRAP_SERVERS=kafka:9092
      - GROUP_ID=1
      - CONFIG_STORAGE_TOPIC=my_connect_configs
      - OFFSET_STORAGE_TOPIC=my_connect_offsets
      - STATUS_STORAGE_TOPIC=my_connect_statuses
    depends_on:
      - kafka
      - oracle

volumes:
  oracle-data:
```

### Dockerfile.connect

```dockerfile
FROM quay.io/debezium/connect:3.4
ENV KAFKA_CONNECT_PLUGINS_DIR=/kafka/connect
USER root
RUN curl -sO https://repo1.maven.org/maven2/io/debezium/debezium-connector-oracle/3.4.2.Final/debezium-connector-oracle-3.4.2.Final-plugin.tar.gz && \
    tar -xzf debezium-connector-oracle-3.4.2.Final-plugin.tar.gz -C $KAFKA_CONNECT_PLUGINS_DIR && \
    rm debezium-connector-oracle-3.4.2.Final-plugin.tar.gz
RUN curl -sO https://repo1.maven.org/maven2/com/oracle/database/jdbc/ojdbc11/23.6.0.24.10/ojdbc11-23.6.0.24.10.jar && \
    curl -sO https://repo1.maven.org/maven2/com/oracle/database/nls/orai18n/23.6.0.24.10/orai18n-23.6.0.24.10.jar && \
    mv ojdbc11-23.6.0.24.10.jar $KAFKA_CONNECT_PLUGINS_DIR/debezium-connector-oracle/ && \
    mv orai18n-23.6.0.24.10.jar $KAFKA_CONNECT_PLUGINS_DIR/debezium-connector-oracle/
RUN rm -f $KAFKA_CONNECT_PLUGINS_DIR/debezium-connector-oracle/ojdbc8-21.11.0.0.jar
RUN curl -sO https://repo1.maven.org/maven2/io/debezium/debezium-connector-jdbc/3.4.2.Final/debezium-connector-jdbc-3.4.2.Final-plugin.tar.gz && \
    tar -xzf debezium-connector-jdbc-3.4.2.Final-plugin.tar.gz -C $KAFKA_CONNECT_PLUGINS_DIR && \
    rm debezium-connector-jdbc-3.4.2.Final-plugin.tar.gz
RUN curl -sO https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar && \
    mv postgresql-42.7.4.jar $KAFKA_CONNECT_PLUGINS_DIR/debezium-connector-jdbc/
RUN chown -R kafka:kafka $KAFKA_CONNECT_PLUGINS_DIR/debezium-connector-oracle $KAFKA_CONNECT_PLUGINS_DIR/debezium-connector-jdbc && \
    chmod -R 755 $KAFKA_CONNECT_PLUGINS_DIR/debezium-connector-oracle $KAFKA_CONNECT_PLUGINS_DIR/debezium-connector-jdbc
USER kafka
```

### init-scripts/01-create-user.sql

Runs automatically only on a **fresh** `oracle-data` volume.

```sql
ALTER SESSION SET CONTAINER = CDB$ROOT;
CREATE USER c##dbzuser IDENTIFIED BY oracle CONTAINER=ALL;
GRANT CONNECT, RESOURCE TO c##dbzuser CONTAINER=ALL;
GRANT SELECT ANY DICTIONARY TO c##dbzuser CONTAINER=ALL;
GRANT SELECT ON V_$INSTANCE TO c##dbzuser CONTAINER=ALL;
GRANT SELECT ON V_$DATABASE TO c##dbzuser CONTAINER=ALL;
GRANT SELECT ON V_$PDBS TO c##dbzuser CONTAINER=ALL;
GRANT SELECT ON V_$LOG TO c##dbzuser CONTAINER=ALL;
GRANT SELECT ON V_$LOGFILE TO c##dbzuser CONTAINER=ALL;
GRANT SELECT ON V_$ARCHIVED_LOG TO c##dbzuser CONTAINER=ALL;
GRANT SYSDBA TO c##dbzuser CONTAINER=ALL;
GRANT EXECUTE_CATALOG_ROLE TO c##dbzuser CONTAINER=ALL;
GRANT EXECUTE ON DBMS_LOGMNR TO c##dbzuser CONTAINER=ALL;
GRANT LOGMINING TO c##dbzuser CONTAINER=ALL;
ALTER USER c##dbzuser QUOTA UNLIMITED ON USERS;
```

### oracle-source.json

```json
{
  "name": "oracle-source-connector",
  "config": {
    "connector.class": "io.debezium.connector.oracle.OracleConnector",
    "tasks.max": "1",
    "database.hostname": "oracle",
    "database.port": "1521",
    "database.user": "c##dbzuser",
    "database.password": "oracle",
    "database.dbname": "FREE",
    "database.pdb.name": "FREEPDB1",
    "topic.prefix": "oracle_cdc",
    "schema.history.internal.kafka.bootstrap.servers": "kafka:9092",
    "schema.history.internal.kafka.topic": "schemahistory.oracle",
    "database.connection.adapter": "LogMiner",
    "table.include.list": "C##DBZUSER.TEST_CDC",
    "schema.include.list": "C##DBZUSER"
  }
}
```

### postgres-sink.json

```json
{
  "name": "postgres-sink-connector",
  "config": {
    "connector.class": "io.debezium.connector.jdbc.JdbcSinkConnector",
    "tasks.max": "1",
    "topics": "oracle_cdc.C__DBZUSER.TEST_CDC",
    "connection.url": "jdbc:postgresql://postgres:5432/target_db",
    "connection.username": "postgres",
    "connection.password": "postgres",
    "insert.mode": "upsert",
    "primary.key.mode": "record_key",
    "delete.enabled": "true",
    "schema.evolution": "basic"
  }
}
```

## 2. Installation

```bash
docker compose build --no-cache connect
docker compose up -d
```

Wait ~60s for Oracle to finish first-boot init (longer on a truly fresh volume).

## 3. Database Setup

Enable archive log mode (gvenzl images default to NOARCHIVELOG):

```bash
docker exec -it debezium-poc-oracle-1 sqlplus / as sysdba
```

```sql
SHUTDOWN IMMEDIATE;
STARTUP MOUNT;
ALTER DATABASE ARCHIVELOG;
ALTER DATABASE OPEN;
ARCHIVE LOG LIST;
```

If `init-scripts` didn't fire (existing volume), run the contents of
`01-create-user.sql` manually via `sqlplus / as sysdba` in `CDB$ROOT`.

Create the test table in **FREEPDB1** (not CDB$ROOT):

```bash
sqlplus c##dbzuser/oracle@//localhost:1521/FREEPDB1
```

```sql
CREATE TABLE test_cdc (id NUMBER PRIMARY KEY, name VARCHAR2(50));
ALTER TABLE test_cdc ADD SUPPLEMENTAL LOG DATA (ALL) COLUMNS;
INSERT INTO test_cdc VALUES (1, 'hello');
COMMIT;
```

## 4. Deploy Connectors

```bash
curl -X POST -H "Content-Type: application/json" \
  --data @oracle-source.json http://localhost:8083/connectors

curl -X POST -H "Content-Type: application/json" \
  --data @postgres-sink.json http://localhost:8083/connectors
```

Check status:

```bash
curl http://localhost:8083/connectors/oracle-source-connector/status
curl http://localhost:8083/connectors/postgres-sink-connector/status
```

## 5. Verification

Consume raw CDC events from Kafka:

```bash
docker exec -it debezium-poc-kafka-1 /kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 \
  --topic oracle_cdc.C__DBZUSER.TEST_CDC \
  --from-beginning
```

Check the sink table in Postgres (auto-created name is
`oracle_cdc_c__dbzuser_test_cdc`):

```bash
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "\dt"
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT * FROM oracle_cdc_c__dbzuser_test_cdc ORDER BY id;"
```

## 6. CRUD Test

Run against Oracle (FREEPDB1, as c##dbzuser):

```sql
INSERT INTO test_cdc VALUES (2, 'row2');
INSERT INTO test_cdc VALUES (3, 'row3');
INSERT INTO test_cdc VALUES (4, 'row4');
INSERT INTO test_cdc VALUES (5, 'row5');
INSERT INTO test_cdc VALUES (6, 'row6');
INSERT INTO test_cdc VALUES (7, 'row7');
INSERT INTO test_cdc VALUES (8, 'row8');
INSERT INTO test_cdc VALUES (9, 'row9');
INSERT INTO test_cdc VALUES (10, 'row10');
INSERT INTO test_cdc VALUES (11, 'row11');
COMMIT;

UPDATE test_cdc SET name = 'updated2' WHERE id = 2;
UPDATE test_cdc SET name = 'updated3' WHERE id = 3;
COMMIT;

DELETE FROM test_cdc WHERE id IN (7, 8, 9, 10, 11);
COMMIT;
```

Re-check Postgres:

```bash
docker exec -it debezium-poc-postgres-1 psql -U postgres -d target_db \
  -c "SELECT * FROM oracle_cdc_c__dbzuser_test_cdc ORDER BY id;"
```

Expected result: rows 1–6 present, with 2 and 3 showing updated names,
7–11 absent.

## Known Gotchas

- `oracle-free:23-slim` still reports banner `Oracle AI Database 26ai` —
  requires Debezium Oracle connector ≥ 3.4.x, older versions fail on
  `resolveOracleDatabaseVersion`.
- Common users (`c##...`) must be created while connected to `CDB$ROOT`,
  not `FREEPDB1` — otherwise `ORA-65094`.
- `CONTAINER=ALL` grants only work when the session container is
  `CDB$ROOT`.
- No `oracle-data` volume = full user/table wipe on every
  `docker compose down` / restart.
- `ALTER USER ... QUOTA UNLIMITED ON USERS` needed or LogMiner's flush
  table creation fails with `ORA-01950`.
- `EXECUTE_CATALOG_ROLE` + `EXECUTE ON DBMS_LOGMNR` needed beyond
  `LOGMINING` role or streaming fails with `PLS-00201`.
- Sink table name defaults to `<topic>` with `.` replaced by `_`
  (lowercased) — not the original table name — unless a topic-routing
  SMT or custom naming strategy is configured.

## Teardown

```bash
docker compose down -v
```

`-v` removes the `oracle-data` volume — next `up` re-runs
`init-scripts/01-create-user.sql` from scratch.
