from uuid import UUID

from app.user.services.errors import ServiceError


def parse_user_id(value):
    """Normalize path UUIDs and preserve the existing validation response."""
    try:
        return str(UUID(value))
    except ValueError as error:
        raise ServiceError({"error": "Invalid user ID"}, 400) from error


def parse_post_id(value):
    """Normalize post path UUIDs before calling a service."""
    try:
        return str(UUID(value))
    except ValueError as error:
        raise ServiceError({"error": "Invalid post ID"}, 400) from error


def parse_media_id(value):
    """Normalize media path UUIDs before accessing storage or the database."""
    try:
        return str(UUID(value))
    except ValueError as error:
        raise ServiceError({"error": "Invalid media ID"}, 400) from error
