from datetime import datetime, timezone

import psycopg2
import requests
from flask import current_app, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.models.common import ErrorResponseBody
from app.services.errors import ServiceError


class RequestValidationError(Exception):
    """Validation failed at the request boundary."""

    def __init__(self, error: ValidationError):
        super().__init__("Validation error")
        self.details = error.errors(include_context=False)


def _server_error(database=False):
    endpoint = request.endpoint
    if endpoint in {"auth.google_callback", "auth.refresh", "auth.logout"}:
        payload = ErrorResponseBody(message="internal server error")
    else:
        message = (
            "Database error occurred" if database else "Internal server error"
        )
        payload = ErrorResponseBody(error=message)
        if endpoint == "auth.login":
            payload.timestamp = datetime.now(timezone.utc).isoformat()
    return jsonify(payload.model_dump(mode="json", exclude_unset=True)), 500


def register_error_handlers(app):
    """Handle failures once while preserving existing API envelopes."""

    @app.errorhandler(ServiceError)
    def handle_service_error(error):
        payload = ErrorResponseBody.model_validate(error.payload)
        response = jsonify(payload.model_dump(mode="json", exclude_unset=True))
        return response, error.status_code

    @app.errorhandler(RequestValidationError)
    def handle_request_validation(error):
        payload = ErrorResponseBody(
            error="Validation error", details=error.details
        )
        response = jsonify(payload.model_dump(mode="json", exclude_unset=True))
        return response, 400

    @app.errorhandler(ValidationError)
    def handle_response_validation(error):
        current_app.logger.exception("Response body validation failed")
        return _server_error()

    @app.errorhandler(psycopg2.Error)
    def handle_database_error(error):
        current_app.logger.exception("Database operation failed")
        return _server_error(database=True)

    @app.errorhandler(requests.RequestException)
    def handle_external_request_error(error):
        current_app.logger.exception("External request failed")
        if request.endpoint == "auth.google_callback":
            payload = ErrorResponseBody(message="google authentication failed")
            response = jsonify(
                payload.model_dump(mode="json", exclude_unset=True)
            )
            return response, 502
        return _server_error()

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        # Preserve native HTTP statuses/headers and Flask-JWT-Extended's more
        # specific handlers for expired/revoked/invalid tokens.
        if isinstance(error, HTTPException):
            return error
        current_app.logger.exception("Unhandled request failure")
        return _server_error()
