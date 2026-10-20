from contextlib import closing
from functools import lru_cache

import boto3
from botocore.config import Config as S3Config

from app.celery_app.config import Config


@lru_cache(maxsize=1)
def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=Config.S3_ENDPOINT_URL,
        aws_access_key_id=Config.S3_ACCESS_KEY_ID,
        aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
        region_name=Config.S3_REGION,
        config=S3Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if Config.S3_FORCE_PATH_STYLE else "auto"},
            connect_timeout=3,
            read_timeout=10,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )


def upload_object(bucket: str, object_key: str, data: bytes, content_type: str) -> None:
    get_s3_client().put_object(
        Bucket=bucket, Key=object_key, Body=data, ContentType=content_type,
    )


def download_object(
    bucket: str, object_key: str, download_path: str, max_bytes: int = 5 * 1024 * 1024,
) -> None:
    response = get_s3_client().get_object(Bucket=bucket, Key=object_key)
    # Limit the stream too: the staging object may have changed after complete.
    with closing(response["Body"]) as body:
        if response["ContentLength"] > max_bytes:
            raise ValueError("Uploaded file exceeds the byte limit")
        total = 0
        with open(download_path, "wb") as output:
            while chunk := body.read(64 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Uploaded file exceeds the byte limit")
                output.write(chunk)
