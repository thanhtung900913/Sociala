import boto3
from botocore.config import Config
from app.backend.config import Config as AppConfig

s3_client = boto3.client(
    "s3",
    endpoint_url=AppConfig.S3_ENDPOINT_URL,  # MinIO endpoint
    aws_access_key_id=AppConfig.S3_ACCESS_KEY_ID,
    aws_secret_access_key=AppConfig.S3_SECRET_ACCESS_KEY,
    region_name=AppConfig.AWS_REGION,
    config=Config(signature_version="s3v4"),
)

def generate_upload_url(
    bucket: str,
    object_key: str,
    content_type: str,
    expires_in: int = 600,
) -> str:
    return s3_client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": bucket,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )

