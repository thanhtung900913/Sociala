from functools import wraps
from flask import request, jsonify
from pydantic import ValidationError

def validate_payload(model):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            payload = request.get_json(silent=True)

            if payload is None:
                return jsonify({
                    "error": "Invalid or missing JSON payload"
                }), 400

            try:
                validated_data = model.model_validate(payload)

            except ValidationError as ve:
                return jsonify({
                    "error": "Validation error",
                    "details": ve.errors(include_context=False)
                }), 400

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
                return jsonify({
                    "error": "Validation error",
                    "details": error.errors(include_context=False),
                }), 400
            return func(query, *args, **kwargs)
        return wrapper
    return decorator
