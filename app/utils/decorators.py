from functools import wraps

from flask import request
from pydantic import ValidationError

from app.services.errors import ServiceError
from app.utils.error_handlers import RequestValidationError


def validate_payload(model):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            payload = request.get_json(silent=True)

            if payload is None:
                raise ServiceError(
                    {"error": "Invalid or missing JSON payload"}, 400
                )

            try:
                validated_data = model.model_validate(payload)
            except ValidationError as error:
                raise RequestValidationError(error) from error

            return func(validated_data, *args, **kwargs)

        return wrapper
    return decorator


def validate_query(model):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                query = model.model_validate(request.args.to_dict())
            except ValidationError as error:
                raise RequestValidationError(error) from error
            return func(query, *args, **kwargs)
        return wrapper
    return decorator
