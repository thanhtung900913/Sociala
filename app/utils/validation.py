from uuid import UUID

from app.services.errors import ServiceError


def parse_user_id(value):
    """Normalize path UUIDs and preserve the existing validation response."""
    try:
        return str(UUID(value))
    except ValueError as error:
        raise ServiceError({"error": "Invalid user ID"}, 400) from error
