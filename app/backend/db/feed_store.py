"""DynamoDB access and data mapping for the materialized feed."""

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
import boto3
from botocore.config import Config

from flask import current_app

_client_lock = Lock()


class FeedStoreError(Exception):
    """The feed repository could not access or decode its stored data."""


def partition_key(viewer_id):
    return f"USER#{UUID(str(viewer_id))}"


def sort_key(created_at, post_id):
    stamp = created_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return f"POST#{stamp.replace('+00:00', 'Z')}#{UUID(str(post_id))}"


def parse_sort_key(key):
    """Decode the timestamp and UUID encoded in a stored sort key."""
    prefix, stamp, post_id = key.split("#")
    created_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if (prefix != "POST" or created_at.utcoffset() is None
            or sort_key(created_at, post_id) != key):
        raise ValueError("Invalid materialized feed sort key")
    return created_at, str(UUID(post_id))


@dataclass(frozen=True)
class FeedKey:
    pk: str
    sk: str

    @classmethod
    def from_item(cls, item):
        return cls(pk=item["PK"]["S"], sk=item["SK"]["S"])


@dataclass(frozen=True)
class FeedReference:
    key: FeedKey
    post_id: str
    author_id: str
    created_at: datetime
    expires_at: int | None = None


@dataclass(frozen=True)
class FeedPage:
    references: list[FeedReference]
    last_key: FeedKey | None


def _map_reference(item):
    key = FeedKey.from_item(item)
    created_at, _ = parse_sort_key(key.sk)
    return FeedReference(
        key=key,
        post_id=str(UUID(item["post_id"]["S"])),
        author_id=str(UUID(item["author_id"]["S"])),
        created_at=created_at,
        expires_at=int(item["expires_at"]["N"]) if "expires_at" in item else None,
    )


class FeedStore:
    def __init__(self, client, table):
        self.client = client
        self.table = table

    def query(self, viewer_id, limit, after=None):
        pk = partition_key(viewer_id)
        params = {
            "TableName": self.table,
            "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
            "ExpressionAttributeNames": {"#pk": "PK", "#sk": "SK"},
            "ExpressionAttributeValues": {
                ":pk": {"S": pk}, ":prefix": {"S": "POST#"},
            },
            "ScanIndexForward": False,
            "ConsistentRead": True,
            "Limit": limit,
        }
        if after is not None:
            params["ExclusiveStartKey"] = {"PK": {"S": pk}, "SK": {"S": after}}
        try:
            response = self.client.query(**params)
        except (BotoCoreError, ClientError) as error:
            raise FeedStoreError("DynamoDB feed query failed") from error
        try:
            last = response.get("LastEvaluatedKey") or {}
            return FeedPage(
                references=[_map_reference(item) for item in response.get("Items", [])],
                last_key=FeedKey.from_item(last) if last else None,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FeedStoreError("Could not decode DynamoDB feed data") from error


def get_feed_store():
    """Reuse one thread-safe low-level SDK client per Flask app/process."""
    app = current_app._get_current_object()
    if "feed_store" not in app.extensions:
        with _client_lock:
            if "feed_store" not in app.extensions:
                region = app.config.get("AWS_REGION")
                table = app.config.get("DYNAMODB_TABLE", "user_feeds")
                if not region or not table:
                    raise FeedStoreError("Missing DynamoDB feed region or table")
                try:
                    client = boto3.client("dynamodb", region_name=region, config=Config(
                        connect_timeout=2, read_timeout=3,
                        retries={"mode": "standard", "total_max_attempts": 2},
                    ))
                except (BotoCoreError, ClientError, ValueError) as error:
                    raise FeedStoreError("Could not initialize DynamoDB feed client") from error
                app.extensions["feed_store"] = FeedStore(client, table)
    return app.extensions["feed_store"]
