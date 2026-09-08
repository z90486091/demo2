# ASB Perf Harness (local: Postgres + ASB Emulator)

Local sandbox to validate the pub/sub perf test script before running it
against real on-prem Postgres + real Azure Service Bus. **This local setup
does NOT measure real network/latency characteristics** — it only proves
the script's logic (outbox commit, publish, consume, correlation, CSV
report) works end-to-end. Rerun against real infra for numbers that matter.

## Folder structure

```
asb-perf-harness/
├── docker-compose.yml       # postgres + sql-edge (ASB emulator's required backing store) + servicebus-emulator
├── config/
│   └── config.json          # ASB emulator queue definitions - EDIT to match your 15 real queue names
├── scripts/
│   └── asb_perf_test.py     # the perf test script
├── .env.example
└── README.md
```

## Why 3 containers, not 1

The Azure Service Bus emulator has **no standalone mode** — Microsoft's
image requires a SQL Server instance as its own metadata backing store.
So "1 container for ASB" isn't possible; it's always emulator + SQL Server,
plus Postgres for the outbox side = 3 containers total here.

## Setup

1. Edit `config/config.json` — replace the 3 sample queue names
   (`order-created`, `order-updated`, `order-cancelled`) with your real
   15 queue names (or a representative subset for this local smoke test).

2. Start everything:
   ```bash
   docker compose up -d
   ```
   Wait ~30-60s for `sql-edge` to report healthy before the emulator
   finishes initializing (`docker compose logs -f servicebus-emulator`
   until you see it's accepted the config).

3. Copy `.env.example` to `.env` and adjust if you changed ports/passwords.

## Run the perf test

```bash
cd scripts
pip install azure-servicebus asyncpg

python asb_perf_test.py \
  --queues order-created,order-updated,order-cancelled \
  --count 50 \
  --delay 5 \
  --asb-conn "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;" \
  --pg-dsn "postgresql://postgres:postgres@localhost:5432/perftest" \
  --out report.csv
```

`--delay` simulates the current fixed queue-delay-before-publish. Set it to
whatever value you're validating (5, 60, 0) to see its effect on
`delay_safety_margin_ms` in the report.

## Reading the report

`report.csv` columns:

| Column | Meaning |
|---|---|
| `committed_at` | When the outbox row's DB transaction actually committed |
| `publish_t0` | When the script called ASB's send (after any `--delay`) |
| `enqueued_time_utc` | ASB broker's own enqueue timestamp (free, from the SDK) |
| `consume_t1` | When the consumer received/processed the message |
| `rt_ms_pub_to_consume` | End-to-end perf: `consume_t1 - publish_t0` |
| `delay_safety_margin_ms` | Safety check: `consume_t1 - committed_at`. Small or negative values here mean the delay setting is NOT safe — the consumer could be acting on data that wasn't reliably committed/visible yet. |
| `consumed` | `False` = message never arrived within `--consumer-timeout` |

## Moving to real infra

- Replace `--asb-conn` with your actual Azure Service Bus connection string
  (no `UseDevelopmentEmulator=true`).
- Replace `--pg-dsn` with the real on-prem Postgres DSN.
- Run this from an on-prem host (not a laptop) so the ASB network hop is
  representative of the real on-prem → Azure path.
- Update `config/config.json` queue names / re-run against all 15 queues,
  not just the sample 3.

## Cleanup

```bash
docker compose down -v
```
