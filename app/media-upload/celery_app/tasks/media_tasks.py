from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from celery import shared_task
from PIL import Image, ImageOps, UnidentifiedImageError

from app.celery_app.db import get_conn
from app.celery_app.tasks.s3 import download_object, upload_object

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 32_000_000
IMAGE_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def set_media_status(media_id: UUID, status: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public.media_assets
            SET status = %s, updated_at = NOW()
            WHERE id = %s AND status = 'PROCESSING' AND deleted_at IS NULL
            """,
            (status, str(media_id)),
        )
        conn.commit()


def validate_image(source_path: Path, media: dict) -> tuple[int, int]:
    if source_path.stat().st_size != media["byte_size"]:
        raise ValueError("Uploaded file size does not match")
    try:
        with Image.open(source_path) as image:
            width, height = image.size
            if IMAGE_TYPES.get(image.format) != media["content_type"]:
                raise ValueError("Uploaded image type does not match")
            if width * height > MAX_PIXELS:
                raise ValueError("Image exceeds the pixel limit")
            if ((media["width"] is not None and media["width"] != width)
                    or (media["height"] is not None and media["height"] != height)):
                raise ValueError("Uploaded image dimensions do not match")
            image.verify()
        # verify() alone does not decode all image data.
        with Image.open(source_path) as image:
            image.load()
    except OSError as error:
        raise ValueError("Invalid image data") from error
    return width, height


def create_thumbnail(source_path: str) -> bytes:
    with Image.open(source_path) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail((320, 320))
        output = BytesIO()
        mode = "RGBA" if "A" in image.getbands() else "RGB"
        image.convert(mode).save(output, format="WEBP", quality=85)
        return output.getvalue()


def _process_media(media_id: str) -> None:
    # This lock also waits for the API's publish transaction to commit.
    # Duplicate deliveries cannot process a READY asset a second time.
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT owner_id, bucket, object_key, content_type, byte_size,
                   width, height, status
            FROM public.media_assets
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (media_id,),
        )
        media = cur.fetchone()
        if media is None or media["status"] != "PROCESSING":
            conn.commit()
            return

        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "original"
            download_object(media["bucket"], media["object_key"], str(source_path), MAX_BYTES)
            width, height = validate_image(source_path, media)
            prefix = f"users/{media['owner_id']}/media/{media_id}/processed"
            final_key = f"{prefix}/original{EXTENSIONS[media['content_type']]}"
            thumbnail = create_thumbnail(str(source_path))
            upload_object(
                media["bucket"], final_key, source_path.read_bytes(), media["content_type"],
            )
            upload_object(
                media["bucket"], f"{prefix}/thumbnail_320.webp", thumbnail, "image/webp",
            )

        # Serve a separate key so the old signed PUT URL cannot overwrite READY media.
        cur.execute(
            """
            UPDATE public.media_assets
            SET object_key = %s, width = %s, height = %s,
                status = 'READY', updated_at = NOW()
            WHERE id = %s AND status = 'PROCESSING' AND deleted_at IS NULL
            """,
            (final_key, width, height, media_id),
        )
        conn.commit()


@shared_task(
    bind=True,
    name="media.process",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_media(self, media_id: str) -> None:
    media_uuid = UUID(media_id)
    try:
        _process_media(str(media_uuid))
    except (UnidentifiedImageError, ValueError, Image.DecompressionBombError):
        set_media_status(media_uuid, "FAILED")
        raise
    except Exception as error:
        if self.request.retries >= self.max_retries:
            set_media_status(media_uuid, "FAILED")
            raise
        raise self.retry(exc=error, countdown=2 ** self.request.retries)
