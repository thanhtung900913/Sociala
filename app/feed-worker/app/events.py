"""Decode Debezium envelopes and build stable feed references."""

import json
from datetime import datetime, timezone
from uuid import UUID


def decode_event(value, key):
    if value is None:
        return None  # Kafka tombstone; not a business event.
    event = json.loads(value)
    if event is None:
        return None
    if not isinstance(event, dict):
        raise ValueError("Expected a Debezium JSON object")
    if "payload" in event:
        event = event["payload"]
        if event is None:
            return None
    if not isinstance(event, dict) or event.get("op") not in {"c", "u", "r", "d"}:
        raise ValueError("Expected raw Debezium envelope with op=c/u/r/d; check SMT/topic")
    source = event.get("source") or {}
    if (not isinstance(source, dict)
            or source.get("table") not in {None, "posts"}
            or source.get("schema") not in {None, "public"}):
        raise ValueError("Worker expects events from public.posts")
    row = event.get("before" if event["op"] == "d" else "after")
    if row is None:
        row = {}
    if not isinstance(row, dict):
        raise ValueError("Expected a Debezium row object")
    post_id = row.get("id")
    key_id = None
    if key is not None:
        decoded_key = json.loads(key)
        if isinstance(decoded_key, dict) and "payload" in decoded_key:
            decoded_key = decoded_key["payload"]
        key_id = decoded_key.get("id") if isinstance(decoded_key, dict) else None
    if post_id is None:
        post_id = key_id
    if post_id is None:
        raise ValueError("Cannot identify post; expected posts primary key 'id'")
    post_id = str(UUID(str(post_id)))
    if key_id is not None and post_id != str(UUID(str(key_id))):
        raise ValueError("Debezium row id does not match Kafka key id")
    return event["op"], post_id


def make_item(post, recipient_id, retention_days):
    created_at = post["created_at"]
    if (not isinstance(created_at, datetime) or created_at.tzinfo is None
            or created_at.utcoffset() is None):
        raise ValueError("posts.created_at must be timezone-aware (use timestamptz)")
    created_at = created_at.astimezone(timezone.utc)
    stamp = created_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    post_id = str(UUID(str(post["id"])))
    item = {
        "PK": f"USER#{UUID(str(recipient_id))}",
        "SK": f"POST#{stamp}#{post_id}",
        "post_id": post_id,
        "author_id": str(UUID(str(post["author_id"]))),
    }
    if retention_days:
        item["expires_at"] = int(created_at.timestamp()) + retention_days * 86400
    return item
