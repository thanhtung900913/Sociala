from urllib.parse import quote

from celery import Celery
from flask import current_app

from app.backend.config import Config


def build_redis_url(host: str, port: int, password: str | None, db: int) -> str:
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


def init_celery(app):
    broker_url = build_redis_url(
        app.config.get("REDIS_HOST", Config.REDIS_HOST),
        app.config.get("REDIS_PORT", Config.REDIS_PORT),
        app.config.get("REDIS_PASSWORD", Config.REDIS_PASSWORD),
        app.config.get("REDIS_BROKER_DB", Config.REDIS_BROKER_DB),
    )
    client = Celery("media_api", broker=broker_url)
    client.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        task_publish_retry=False,
        broker_connection_timeout=3,
        broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
        timezone="UTC",
        enable_utc=True,
    )
    app.extensions["celery_clients"] = {"default": client}


def get_celery_client(name: str = "default") -> Celery:
    return current_app.extensions["celery_clients"][name]
