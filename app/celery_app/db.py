# app/db.py
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection as PGConnection
from psycopg2.extras import RealDictCursor

from config import Config
import redis as redis_lib


logger = logging.getLogger(__name__)


def dsn_for_env() -> str:

    return (
        f"host={Config.DBHOST} port={Config.DBPORT} "
        f"dbname={Config.DBNAME} user={Config.DBUSER} "
        f"password={Config.DBPASSWORD}"
    )



@contextmanager
def get_conn() -> Iterator[PGConnection]:
    """
    Open/close a fresh connection (no pooling).
    - rollback on exception
    - always close
    """
    conn: PGConnection | None = None
    try:
        conn = psycopg2.connect(dsn_for_env(), cursor_factory=RealDictCursor)
        yield conn
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                logger.exception("Rollback failed (env=%s)", Config.STATUS)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                logger.exception("Close failed (env=%s)", Config.STATUS)

def get_redis_client() -> redis_lib.Redis:
    return redis_lib.Redis(
        host=Config.REDIS_HOST,
        port=int(Config.REDIS_PORT),
        password=Config.REDIS_PASSWORD,
        db=Config.REDIS_DB,
        decode_responses=True,
    )


def get_progress_ids(redis_client: redis_lib.Redis, user_id: str, class_id: str) -> list:
    session_key = f"session_progresses:{user_id}:{class_id}:{class_id}"
    return redis_client.lrange(session_key, 0, -1)


def cleanup_session(redis_client: redis_lib.Redis, user_id: str, class_id: str) -> None:
    session_key = f"session_progresses:{user_id}:{class_id}:{class_id}"
    redis_client.delete(session_key)
    keys = redis_client.keys(f"progress:{user_id}:*:{class_id}")
    if keys:
        redis_client.delete(*keys)

if __name__ == "__main__":
    redis_client = get_redis_client()
    print(redis_client.keys("progress:*"))


if __file__ == "__main__":
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                assert result == (1,)
        print("Connection test successful!")
    except Exception as e:
        print(f"Connection test failed: {str(e)}")

    redis_client = get_redis_client()
    print(redis_client.keys("progress:*"))