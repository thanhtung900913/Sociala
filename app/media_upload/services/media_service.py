from mimetypes import guess_extension
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app
from kombu.exceptions import OperationalError

from app.media_upload.config import Config
from app.media_upload.db.connection import get_db_connection_context
from app.media_upload.models.media_model import (
    MediaCompleteResponseBody,
    MediaUploadInfo,
    MediaUploadRequestBody,
    MediaUploadResponseBody,
)
from app.media_upload.services.errors import ServiceError
from app.media_upload.utils.s3 import generate_upload_url, get_object_metadata
from app.media_upload.utils.celery_client import get_celery_client


def upload_media(owner_id: UUID | str, body: MediaUploadRequestBody) -> MediaUploadResponseBody:
    media_id = uuid4()
    bucket = Config.MEDIA_BUCKET
    storage_provider = Config.STORAGE_PROVIDER
    extension = guess_extension(body.content_type) or ""
    object_key = f"staging/users/{owner_id}/media/{media_id}/original{extension}"
    expires_in = Config.MEDIA_EXPIRES_IN

    try:
        upload_url = generate_upload_url(
            bucket=bucket,
            object_key=object_key,
            content_type=body.content_type,
            expires_in=expires_in,
        )
    except (BotoCoreError, ClientError) as error:
        current_app.logger.exception("Could not create media upload URL")
        raise ServiceError({"error": "STORAGE_UNAVAILABLE"}, 503) from error

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
        response = MediaUploadResponseBody(
            media_id=row["id"],
            status=row["status"],
            upload=MediaUploadInfo(
                url=upload_url,
                method="PUT",
                headers={"Content-Type": body.content_type},
                expires_in=expires_in,
            ),
        )
        conn.commit()

    return response


def complete_media_upload(owner_id: UUID | str, media_id: UUID | str) -> MediaCompleteResponseBody:
    with get_db_connection_context() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bucket, object_key, byte_size, content_type, status
            FROM public.media_assets
            WHERE id = %s AND owner_id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (str(media_id), str(owner_id)),
        )
        row = cur.fetchone()

        if row is None:
            raise ServiceError({"error": "NOT_FOUND"}, 404)

        status = row["status"]
        if status in {"PROCESSING", "READY"}:
            response = MediaCompleteResponseBody(media_id=media_id, status=status)
            conn.commit()
            return response

        if status != "UPLOADING":
            raise ServiceError({"error": "INVALID_MEDIA_STATUS"}, 409)

        try:
            metadata = get_object_metadata(row["bucket"], row["object_key"])
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise ServiceError({"error": "UPLOAD_NOT_FOUND"}, 409) from error
            current_app.logger.exception("Could not inspect media upload")
            raise ServiceError({"error": "STORAGE_UNAVAILABLE"}, 503) from error
        except BotoCoreError as error:
            current_app.logger.exception("Could not inspect media upload")
            raise ServiceError({"error": "STORAGE_UNAVAILABLE"}, 503) from error

        content_type = (metadata.get("content_type") or "").split(";", 1)[0].strip().lower()
        if (metadata["byte_size"] != row["byte_size"]
                or content_type != row["content_type"]
                or content_type not in {"image/jpeg", "image/png", "image/webp"}
                or not 0 < metadata["byte_size"] <= 5 * 1024 * 1024):
            raise ServiceError({"error": "FILE_VALIDATION_FAILED"}, 422)

        cur.execute(
            """
            UPDATE public.media_assets
            SET status = 'PROCESSING', updated_at = NOW()
            WHERE id = %s AND owner_id = %s AND status = 'UPLOADING'
              AND deleted_at IS NULL
            RETURNING id
            """,
            (str(media_id), str(owner_id)),
        )
        updated = cur.fetchone()

        if updated is None:
            raise ServiceError({"error": "INVALID_MEDIA_STATUS"}, 409)

        response = MediaCompleteResponseBody(media_id=media_id, status="PROCESSING")
        # The worker also takes FOR UPDATE, so it can only read PROCESSING
        # after this transaction commits. Publishing while locked allows a
        # broker failure to roll back to UPLOADING for a safe client retry.
        try:
            get_celery_client().send_task(
                "media.process", args=[str(media_id)], ignore_result=True, retry=False,
            )
        except (OperationalError, OSError) as error:
            current_app.logger.exception("Could not queue media processing")
            raise ServiceError({"error": "MEDIA_PROCESSING_UNAVAILABLE"}, 503) from error
        conn.commit()

    return response