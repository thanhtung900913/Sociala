import re
from uuid import UUID

import psycopg2
from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required, unset_jwt_cookies

from app.models.user_model import (
    DeleteUserRequestBody, SearchUsersQuery, UpdateProfileRequestBody,
    UpdateUserRequestBody, UserPageQuery,
)
from app.services import post_service, user_service
from app.services.errors import ServiceError
from app.utils.decorators import validate_payload, validate_query

user_bp = Blueprint("user", __name__)


def _database_error(action):
    current_app.logger.exception("Database error during %s", action)
    return jsonify({"error": "Database error occurred"}), 500


@user_bp.route("/me", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
def get_current_user():
    try:
        account = user_service.get_current_user(get_jwt_identity())
        return jsonify({"data": account}), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        return _database_error("get current user")
    except Exception:
        current_app.logger.exception("Get current user failed")
        return jsonify({"error": "Internal server error"}), 500


@user_bp.route("/me", methods=["PATCH"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(UpdateUserRequestBody)
def update_current_user(body: UpdateUserRequestBody):
    try:
        account = user_service.update_current_user(get_jwt_identity(), body)
        return jsonify({"data": account}), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        return _database_error("update current user")
    except Exception:
        current_app.logger.exception("Update current user failed")
        return jsonify({"error": "Internal server error"}), 500


@user_bp.route("/me", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(DeleteUserRequestBody)
def delete_current_user(body: DeleteUserRequestBody):
    try:
        user_service.delete_current_user(get_jwt_identity(), body)
        response = current_app.response_class(status=204)
        unset_jwt_cookies(response)
        response.delete_cookie("refresh_token", path="/api/v1/auth")
        return response
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        return _database_error("delete current user")
    except Exception:
        current_app.logger.exception("Delete current user failed")
        return jsonify({"error": "Internal server error"}), 500


@user_bp.route("/<user_id>", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
def get_user_profile(user_id):
    try:
        user_id = str(UUID(user_id))
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400

    try:
        profile = user_service.get_user_profile(get_jwt_identity(), user_id)
        return jsonify({"data": profile}), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        return _database_error("get user profile")
    except Exception:
        current_app.logger.exception("Get user profile failed")
        return jsonify({"error": "Internal server error"}), 500


@user_bp.route("/by-username/<username>", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
def get_user_by_username(username):
    if re.fullmatch(r"[A-Za-z0-9_]{3,30}", username) is None:
        return jsonify({"error": "Invalid username"}), 400
    try:
        profile = user_service.get_user_by_username(get_jwt_identity(), username)
        return jsonify({"data": profile}), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        return _database_error("get user by username")
    except Exception:
        current_app.logger.exception("Get user by username failed")
        return jsonify({"error": "Internal server error"}), 500


@user_bp.route("", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(SearchUsersQuery)
def search_users(query: SearchUsersQuery):
    try:
        return jsonify(user_service.search_users(get_jwt_identity(), query)), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        return _database_error("search users")
    except Exception:
        current_app.logger.exception("Search users failed")
        return jsonify({"error": "Internal server error"}), 500


@user_bp.route("/me/profile", methods=["PATCH"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(UpdateProfileRequestBody)
def update_current_profile(body: UpdateProfileRequestBody):
    try:
        profile = user_service.update_current_profile(get_jwt_identity(), body)
        return jsonify({"data": profile}), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        return _database_error("update current profile")
    except Exception:
        current_app.logger.exception("Update current profile failed")
        return jsonify({"error": "Internal server error"}), 500


@user_bp.route("/<user_id>/posts", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(UserPageQuery)
def list_user_posts(query: UserPageQuery, user_id):
    try:
        user_id = str(UUID(user_id))
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    try:
        result = post_service.list_user_posts(get_jwt_identity(), user_id, query)
        return jsonify(result), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        return _database_error("list user posts")
    except Exception:
        current_app.logger.exception("List user posts failed")
        return jsonify({"error": "Internal server error"}), 500
