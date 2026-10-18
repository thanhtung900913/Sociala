"""Write DynamoDB batches with bounded retries for unprocessed items."""

import random
import time


def validate_table(client, settings):
    """Fail at startup if keys or the configured retention policy cannot work."""
    table = client.describe_table(TableName=settings.table)["Table"]
    keys = {entry["AttributeName"]: entry["KeyType"] for entry in table["KeySchema"]}
    types = {entry["AttributeName"]: entry["AttributeType"]
             for entry in table["AttributeDefinitions"]}
    if keys != {"PK": "HASH", "SK": "RANGE"} or types.get("PK") != "S" or types.get("SK") != "S":
        raise ValueError("Expected DynamoDB table with String PK (HASH) and String SK (RANGE)")
    if settings.retention_days:
        ttl = client.describe_time_to_live(TableName=settings.table)["TimeToLiveDescription"]
        if (ttl.get("AttributeName") != "expires_at"
                or ttl.get("TimeToLiveStatus") not in {"ENABLED", "ENABLING"}):
            raise ValueError("RETENTION_DAYS requires DynamoDB TTL enabled on expires_at")


def _serialize(item):
    result = {}
    for name, value in item.items():
        if isinstance(value, str):
            result[name] = {"S": value}
        elif type(value) is int:
            result[name] = {"N": str(value)}
        else:
            raise ValueError(f"Feed attribute {name} must be a string or integer")
    for name, limit in (("PK", 2048), ("SK", 1024)):
        value = item.get(name)
        if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= limit:
            raise ValueError(f"Invalid DynamoDB {name}")
    return result


def write_batch(client, table, items, check, sleep=time.sleep, jitter=random.uniform):
    """Bounded retries for DynamoDB's partial successes, in batches <= 25."""
    if not items:
        return
    if len(items) > 25:
        raise ValueError("DynamoDB batch must have at most 25 items")
    requests = [{"PutRequest": {"Item": _serialize(item)}} for item in items]
    if len({(item["PK"], item["SK"]) for item in items}) != len(items):
        raise ValueError("DynamoDB batch cannot contain duplicate primary keys")
    pending = {table: requests}
    for attempt in range(8):
        check()
        response = client.batch_write_item(RequestItems=pending)
        check()
        pending = response.get("UnprocessedItems") or {}
        if not any(pending.values()):
            return
        if attempt < 7:
            sleep(jitter(0, min(4, 0.25 * 2 ** attempt)))
    raise RuntimeError("DynamoDB still has unprocessed writes; offset will not be committed")
