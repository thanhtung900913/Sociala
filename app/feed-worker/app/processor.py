"""Coordinate fan-out within the processing time and recipient limits."""

import time
from datetime import datetime, timezone

from .dynamodb_writer import write_batch
from .events import decode_event, make_item


def process_value(value, key, settings, source, client, stop,
                  clock=time.monotonic, utcnow=lambda: datetime.now(timezone.utc)):
    started = clock()

    def check():
        if stop.is_set():
            raise InterruptedError("Stopping; leave unfinished message uncommitted")
        if clock() - started >= settings.processing_seconds:
            raise TimeoutError("Fan-out exceeded time budget; split into durable jobs")

    check()
    decoded = decode_event(value, key)
    if decoded is None:
        return "tombstone", 0
    op, post_id = decoded
    if op == "r" and not settings.process_snapshots:
        return "snapshot_skipped", 0
    if op == "d":
        return "delete_no_eager_cleanup", 0

    # Read current authoritative state, not potentially old event content.
    # This also avoids guessing Debezium timestamp units from schema-less JSON.
    with source.snapshot():
        post = source.get_post(post_id)
        check()
        if post is None or post["deleted_at"] is not None:
            return "missing_or_deleted_no_eager_cleanup", 0
        item = make_item(post, str(post["author_id"]), settings.retention_days)
        if item.get("expires_at", float("inf")) <= utcnow().timestamp():
            return "expired", 0
        recipients = source.recipient_ids(post)
    check()
    for offset in range(0, len(recipients), 25):
        # All attributes other than the partition key are identical; format
        # timestamp/UUID/TTL once per event instead of once per recipient.
        items = [dict(item, PK=f"USER#{user_id}")
                 for user_id in recipients[offset:offset + 25]]
        write_batch(client, settings.table, items, check, sleep=stop.wait)
    check()
    return "fanout", len(recipients)
