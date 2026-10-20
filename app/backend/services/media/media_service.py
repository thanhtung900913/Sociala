from mimetypes import guess_extension
from uuid import UUID, uuid4

from app.backend.config import Config
from app.backend.db.connection import get_db_connection_context
from app.backend.models.media_model import (
    MediaUploadInfo,
    MediaUploadRequestBody,
    MediaUploadResponseBody,
)
from app.backend.services.media.s3 import generate_upload_url, get_object_metadata


def upload_media(owner_id: UUID, body: MediaUploadRequestBody) -> MediaUploadResponseBody:
    media_id = uuid4()
    bucket = Config.MEDIA_BUCKET
    storage_provider = Config.STORAGE_PROVIDER
    extension = guess_extension(body.content_type) or ""
    object_key = f"users/{owner_id}/media/{media_id}/original{extension}"
    expires_in = Config.MEDIA_EXPIRES_IN

    upload_url = generate_upload_url(
        bucket=bucket,
        object_key=object_key,
        content_type=body.content_type,
        expires_in=expires_in,
    )

    with get_db_connection_context() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.media_assets (
                id, owner_id, storage_provider, bucket, object_key,
                content_type, byte_size, width, height, status
            )
            VALUES (
                %(id)s::uuid, %(owner_id)s::uuid, %(storage_provider)s,
                %(bucket)s, %(object_key)s, %(content_type)s,
                %(byte_size)s, %(width)s, %(height)s, 'UPLOADING'
            )
            RETURNING id, status
            """,
            {
                "id": str(media_id),
                "owner_id": str(owner_id),
                "storage_provider": storage_provider,
                "bucket": bucket,
                "object_key": object_key,
                "content_type": body.content_type,
                "byte_size": body.byte_size,
                "width": body.width,
                "height": body.height,
            },
        )
        row = cur.fetchone()

    return MediaUploadResponseBody(
        media_id=row[0],
        status=row[1],
        upload=MediaUploadInfo(
            url=upload_url,
            method="PUT",
            headers={"Content-Type": body.content_type},
            expires_in=expires_in,
        ),
    )

