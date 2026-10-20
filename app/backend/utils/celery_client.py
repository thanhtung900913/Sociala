from celery import Celery
from config import Config
from flask import current_app

CELERY_CLIENT_CONFIG = {
    # Inner Redis (DB 2) — broker shared with the in-app Celery worker.
    "default": {"host": Config.REDIS_HOST, "port": Config.REDIS_PORT, "password": Config.REDIS_PASSWORD, "db": 2, "client_name": "main_celery_client"},
    # Inner Redis (DB 2) — dispatches meshy.task to the scan Celery worker.
    "meshy": {"host": Config.REDIS_HOST, "port": Config.REDIS_PORT, "password": Config.REDIS_PASSWORD, "db": 2, "client_name": "meshy_client"},
    # Outer Redis (BROKER_HOST) — for external workers such as the email service.
    "email": {"host": Config.BROKER_HOST, "port": Config.BROKER_PORT, "password": Config.BROKER_PASSWORD, "db": 2, "client_name": "email_tasks"},
}

def build_redis_url(
    host: str,
    port: str,
    password: str | None,
    db: str,
) -> str:
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"
    
def make_celery(db: int, client_name: str) -> Celery:
    '''Create Celery client using outer Redis as the broker.'''
    host = Config.BROKER_HOST
    port = Config.BROKER_PORT
    password = Config.BROKER_PASSWORD
    broker_url = build_redis_url(host, port, password, db)

    c = Celery(client_name, broker=broker_url, backend=broker_url)
    c.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )
    return c

def make_celery_with_broker(*, host: str, port: str, password: str | None, db: int, client_name: str) -> Celery:
    broker_url = build_redis_url(host, port, password, db)
    client = Celery(client_name, broker=broker_url, backend=broker_url)
    client.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )
    return client


def _build_celery_clients() -> dict[str, Celery]:
    return {
        name: make_celery_with_broker(
            host=config["host"],
            port=config["port"],
            password=config["password"],
            db=config["db"],
            client_name=config["client_name"],
        )
        for name, config in CELERY_CLIENT_CONFIG.items()
    }

def init_celery(app):
    '''Register named Celery clients for different task brokers.'''
    with app.app_context():
        app.extensions["celery_clients"] = _build_celery_clients()


def get_celery_client(name: str = "default") -> Celery:
    return current_app.extensions["celery_clients"][name]
