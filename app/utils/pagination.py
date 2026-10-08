from uuid import UUID

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from pydantic import ValidationError

from app.services.errors import ServiceError


def _cursor_serializer():
    secret = current_app.config.get("SECRET_KEY") or current_app.config["JWT_SECRET_KEY"]
    return URLSafeSerializer(secret, salt="user-pagination-v1")


def encode_cursor(route, viewer_id, filters, position):
    return _cursor_serializer().dumps({
        "version": 1,
        "route": route,
        "viewer_id": str(UUID(str(viewer_id))),
        "filters": filters,
        "position": position,
    })


def decode_cursor(token, route, viewer_id, filters, position_model):
    if token is None:
        return None
    try:
        payload = _cursor_serializer().loads(token)
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or payload.get("route") != route
            or payload.get("viewer_id") != str(UUID(str(viewer_id)))
            or payload.get("filters") != filters
        ):
            raise ValueError("Cursor does not match this request")
        return position_model.model_validate(payload["position"])
    except (BadData, ValidationError, KeyError, ValueError, TypeError) as error:
        raise ServiceError({"error": "Invalid cursor"}, 400) from error
