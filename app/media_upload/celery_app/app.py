from urllib.parse import quote

from celery import Celery

from app.celery_app.config import Config


def build_redis_url(host: str, port: str, password: str | None, db: int) -> str:
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


broker = build_redis_url(
    Config.REDIS_HOST, Config.REDIS_PORT, Config.REDIS_PASSWORD, Config.REDIS_BROKER_DB,
)
app = Celery(
    Config.CELERY_APP_NAME,
    broker=broker,
    include=["app.celery_app.tasks.media_tasks"],
)
app.conf.update(
    worker_concurrency=Config.CELERY_CONCURRENCY,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
)
