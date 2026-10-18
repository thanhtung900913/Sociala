"""Initialize external clients and run the sequential Kafka consumer loop.

SDK imports stay inside main so the package can be tested with the standard library.
"""

import logging
import signal
import threading

from config import Settings
from app.dynamodb_writer import validate_table
from app.kafka_runtime import process_and_commit
from app.postgres_source import PostgresSource
from app.processor import process_value

LOG = logging.getLogger("feed-worker")


def main():
    import boto3
    import psycopg
    from botocore.config import Config
    from confluent_kafka import Consumer, KafkaException
    from psycopg.rows import dict_row

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    client = boto3.client("dynamodb", region_name=settings.region,
                          config=Config(connect_timeout=3, read_timeout=5,
                                        retries={"mode": "standard", "total_max_attempts": 3}))
    validate_table(client, settings)

    consumer = Consumer({
        "bootstrap.servers": settings.bootstrap,
        "group.id": settings.group,
        "enable.auto.commit": False,
        "enable.auto.offset.store": False,
        "auto.offset.reset": "earliest",
        "allow.auto.create.topics": False,
        "max.poll.interval.ms": 300000,
    })
    try:
        with psycopg.connect(settings.pg_dsn, autocommit=True, row_factory=dict_row,
                             connect_timeout=5, options="-c statement_timeout=15000") as conn:
            source = PostgresSource(conn, settings)
            if settings.recipient_mode == "self_test":
                LOG.warning("SELF_TEST: only the author's own feed receives posts")
            consumer.subscribe([settings.topic])
            LOG.info("Started topic=%s group=%s audience=%s", settings.topic,
                     settings.group, settings.recipient_mode)
            while not stop.is_set():
                msg = consumer.poll(1)
                if msg is None:
                    continue
                if msg.error():
                    raise KafkaException(msg.error())
                try:
                    reason, count = process_and_commit(
                        consumer, msg,
                        lambda value, key: process_value(value, key, settings, source, client, stop),
                    )
                    LOG.info("Committed partition=%s offset=%s result=%s recipients=%s",
                             msg.partition(), msg.offset(), reason, count)
                except InterruptedError:
                    LOG.info("Stopped without committing unfinished event")
                    break
                except Exception:
                    LOG.exception("Failed partition=%s offset=%s; stopping without advancing offset",
                                  msg.partition(), msg.offset())
                    raise
    finally:
        # Auto-commit is disabled: close must not acknowledge unfinished work.
        consumer.close()


if __name__ == "__main__":
    main()
