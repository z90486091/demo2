#!/usr/bin/env python3
"""
ASB pub/sub perf + delay-safety test.

Simulates the real pipeline: DB txn commit (outbox row) -> optional queue delay
-> ASB publish -> ASB consume -> correlate against Postgres commit timestamp.

Answers the actual question that matters: for a given queue delay (e.g. 5s),
was the outbox row's commit always visible/safe by the time the consumer
processed the message? Also reports end-to-end RT per queue.

Usage:
    python asb_perf_test.py --queues order-created,order-updated,order-cancelled \
        --count 200 --delay 5 \
        --asb-conn "$ASB_CONN_STR" --pg-dsn "$PG_DSN" \
        --out report.csv

Requires: pip install azure-servicebus asyncpg
"""
import argparse
import asyncio
import csv
import time
import uuid
from dataclasses import dataclass, field

import asyncpg
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage

DDL = """
CREATE TABLE IF NOT EXISTS outbox_perf_test (
    id UUID PRIMARY KEY,
    queue_name TEXT NOT NULL,
    payload JSONB NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
"""


@dataclass
class Record:
    msg_id: str
    queue: str
    publish_t0: float = None
    committed_at: float = None
    enqueued_time_utc: str = None
    consume_t1: float = None


records: dict[str, Record] = {}
lock = asyncio.Lock()


async def publish_one(pg: asyncpg.Pool, sb_client: ServiceBusClient, queue: str, delay: float):
    msg_id = str(uuid.uuid4())
    async with pg.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO outbox_perf_test (id, queue_name, payload) "
                "VALUES ($1, $2, $3) RETURNING committed_at",
                uuid.UUID(msg_id), queue, '{"test": true}',
            )
    committed_at = row["committed_at"].timestamp()

    if delay > 0:
        await asyncio.sleep(delay)  # simulate the current fixed queue delay

    t0 = time.time()
    async with sb_client.get_queue_sender(queue) as sender:
        msg = ServiceBusMessage(body=b"{}", message_id=msg_id, application_properties={"queue": queue})
        await sender.send_messages(msg)

    async with lock:
        records[msg_id] = Record(msg_id=msg_id, queue=queue, publish_t0=t0, committed_at=committed_at)


async def consume_loop(sb_client: ServiceBusClient, queue: str, expected: int, timeout: float):
    received = 0
    async with sb_client.get_queue_receiver(queue, max_wait_time=timeout) as receiver:
        async for msg in receiver:
            t1 = time.time()
            msg_id = msg.message_id
            async with lock:
                if msg_id in records:
                    records[msg_id].consume_t1 = t1
                    records[msg_id].enqueued_time_utc = str(msg.enqueued_time_utc)
            await receiver.complete_message(msg)
            received += 1
            if received >= expected:
                break


async def run(args):
    pg = await asyncpg.create_pool(dsn=args.pg_dsn, min_size=2, max_size=10)
    async with pg.acquire() as conn:
        await conn.execute(DDL)

    sb_client = ServiceBusClient.from_connection_string(args.asb_conn)
    queues = args.queues.split(",")

    async with sb_client:
        consumers = [
            asyncio.create_task(consume_loop(sb_client, q, args.count, args.consumer_timeout))
            for q in queues
        ]

        publishers = []
        for q in queues:
            for _ in range(args.count):
                publishers.append(publish_one(pg, sb_client, q, args.delay))
        await asyncio.gather(*publishers)

        await asyncio.gather(*consumers)

    await pg.close()
    write_report(args.out)


def write_report(path: str):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "queue", "msg_id", "committed_at", "publish_t0", "enqueued_time_utc",
            "consume_t1", "rt_ms_pub_to_consume", "delay_safety_margin_ms", "consumed"
        ])
        for r in records.values():
            consumed = r.consume_t1 is not None
            rt_ms = (r.consume_t1 - r.publish_t0) * 1000 if consumed else ""
            margin_ms = (r.consume_t1 - r.committed_at) * 1000 if consumed else ""
            w.writerow([
                r.queue, r.msg_id, r.committed_at, r.publish_t0, r.enqueued_time_utc,
                r.consume_t1, rt_ms, margin_ms, consumed
            ])
    total = len(records)
    consumed = sum(1 for r in records.values() if r.consume_t1 is not None)
    print(f"Wrote {path}: {consumed}/{total} messages consumed.")
    if consumed < total:
        print(f"WARNING: {total - consumed} messages never arrived within consumer_timeout.")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--queues", required=True, help="comma-separated ASB queue names")
    p.add_argument("--count", type=int, default=100, help="messages per queue")
    p.add_argument("--delay", type=float, default=0.0, help="simulated queue delay in seconds before publish")
    p.add_argument("--consumer-timeout", type=float, default=30.0, help="seconds to wait per queue for messages")
    p.add_argument(
        "--asb-conn", required=True,
        help=(
            "Azure Service Bus connection string. For the local emulator use: "
            '"Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;'
            'SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"'
        ),
    )
    p.add_argument("--pg-dsn", required=True, help="Postgres DSN, e.g. postgresql://postgres:postgres@localhost:5432/perftest")
    p.add_argument("--out", default="report.csv")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
