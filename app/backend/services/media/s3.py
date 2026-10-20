from functools import lru_cache

import boto3
from botocore.config import Config

from app.backend.config import Config as AppConfig


@lru_cache(maxsize=1)
def get_s3_client():
    # Defer credential resolution and network setup until storage is used.
    return boto3.client(
        "s3",
        endpoint_url=AppConfig.S3_ENDPOINT_URL,
        aws_access_key_id=AppConfig.S3_ACCESS_KEY_ID,
        aws_secret_access_key=AppConfig.S3_SECRET_ACCESS_KEY,
        region_name=AppConfig.S3_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if AppConfig.S3_FORCE_PATH_STYLE else "auto"},
            connect_timeout=3,
            read_timeout=5,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )


def generate_upload_url(
    bucket: str,
    object_key: str,
    content_type: str,
    expires_in: int = 600,
) -> str:
    return get_s3_client().generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": bucket, "Key": object_key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )


def get_object_metadata(bucket: str, object_key: str) -> dict:
    response = get_s3_client().head_object(Bucket=bucket, Key=object_key)
    return {
        "byte_size": response["ContentLength"],
        "content_type": response.get("ContentType"),
        "etag": response.get("ETag"),
    }
