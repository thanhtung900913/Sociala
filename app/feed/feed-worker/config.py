"""Environment configuration and validation."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    bootstrap: str
    topic: str
    group: str
    pg_dsn: str
    region: str
    table: str = "user_feeds"
    recipient_mode: str = "friends"
    recipients_file: str = str(Path(__file__).resolve().parent / "sql" / "recipients.sql")
    process_snapshots: bool = False
    retention_days: int = 0
    max_recipients: int = 5000
    processing_seconds: int = 120

    def __post_init__(self):
        for name in ("bootstrap", "topic", "group", "pg_dsn", "region", "table"):
            if not getattr(self, name).strip():
                raise ValueError(f"Missing setting: {name}")
        if self.recipient_mode not in {"friends", "self_test", "custom_sql"}:
            raise ValueError("RECIPIENT_MODE must be friends, self_test or custom_sql")
        if "REPLACE_WITH" in self.topic:
            raise ValueError("Set KAFKA_TOPIC to the exact existing posts topic")
        if self.retention_days < 0 or self.max_recipients < 1:
            raise ValueError("Invalid retention or recipient limit")
        if not 1 <= self.processing_seconds <= 120:
            raise ValueError("PROCESSING_TIMEOUT_SECONDS must be 1..120")
        path = Path(self.recipients_file)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        object.__setattr__(self, "recipients_file", str(path.resolve()))

    @classmethod
    def from_env(cls):
        def required(name):
            value = os.environ.get(name, "").strip()
            if not value:
                raise ValueError(f"Missing environment variable: {name}")
            return value

        snapshot = os.environ.get("PROCESS_SNAPSHOTS", "false").strip().lower()
        if snapshot not in {"true", "false"}:
            raise ValueError("PROCESS_SNAPSHOTS must be true or false")
        settings = cls(
            bootstrap=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092"),
            topic=required("KAFKA_TOPIC"),
            group=os.environ.get("KAFKA_GROUP_ID", "feed-fanout-v1"),
            pg_dsn=required("PG_DSN"),
            region=required("AWS_REGION"),
            table=os.environ.get("DYNAMODB_TABLE", "user_feeds"),
            recipient_mode=os.environ.get("RECIPIENT_MODE", "friends").strip(),
            recipients_file=os.environ.get("RECIPIENTS_SQL_FILE", cls.recipients_file),
            process_snapshots=snapshot == "true",
            retention_days=int(os.environ.get("RETENTION_DAYS", "0")),
            max_recipients=int(os.environ.get("MAX_RECIPIENTS_PER_EVENT", "5000")),
            processing_seconds=int(os.environ.get("PROCESSING_TIMEOUT_SECONDS", "120")),
        )
        return settings
