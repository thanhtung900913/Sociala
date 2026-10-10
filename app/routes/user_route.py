import re

from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import (
    get_jwt_identity, jwt_required, unset_jwt_cookies,
)

from app.models.user_model import (
    DeleteUserRequestBody, SearchUsersQuery, UpdateProfileRequestBody,
    UpdateUserRequestBody, UserPageQuery,
)
from app.services import post_service, user_relation_service, user_service
from app.services.errors import ServiceError
from app.utils.decorators import validate_payload, validate_query
from app.utils.validation import parse_user_id

user_bp = Blueprint("user", __name__)


@user_bp.route("/me", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
def get_current_user():
    response = user_service.get_current_user(get_jwt_identity())
    return jsonify({"data": response.model_dump(mode="json")}), 200


@user_bp.route("/me", methods=["PATCH"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(UpdateUserRequestBody)
def update_current_user(body: UpdateUserRequestBody):
    response = user_service.update_current_user(get_jwt_identity(), body)
    return jsonify({"data": response.model_dump(mode="json")}), 200


@user_bp.route("/me", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(DeleteUserRequestBody)
def delete_current_user(body: DeleteUserRequestBody):
    user_service.delete_current_user(get_jwt_identity(), body)
    response = current_app.response_class(status=204)
    unset_jwt_cookies(response)
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return response


@user_bp.route("/<user_id>", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
def get_user_profile(user_id):
    user_id = parse_user_id(user_id)
    response = user_service.get_user_profile(get_jwt_identity(), user_id)
    return jsonify({"data": response.model_dump(mode="json")}), 200


@user_bp.route("/by-username/<username>", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
def get_user_by_username(username):
    if re.fullmatch(r"[A-Za-z0-9_]{3,30}", username) is None:
        raise ServiceError({"error": "Invalid username"}, 400)
    response = user_service.get_user_by_username(get_jwt_identity(), username)
    return jsonify({"data": response.model_dump(mode="json")}), 200


@user_bp.route("", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(SearchUsersQuery)
def search_users(query: SearchUsersQuery):
    response = user_service.search_users(get_jwt_identity(), query)
    return jsonify(response.model_dump(mode="json")), 200


@user_bp.route("/me/profile", methods=["PATCH"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(UpdateProfileRequestBody)
def update_current_profile(body: UpdateProfileRequestBody):
    response = user_service.update_current_profile(get_jwt_identity(), body)
    return jsonify({"data": response.model_dump(mode="json")}), 200


@user_bp.route("/<user_id>/posts", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(UserPageQuery)
def list_user_posts(query: UserPageQuery, user_id):
    user_id = parse_user_id(user_id)
    response = post_service.list_user_posts(get_jwt_identity(), user_id, query)
    return jsonify(response.model_dump(mode="json")), 200


@user_bp.route("/me/friends", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(UserPageQuery)
def list_friends(query: UserPageQuery):
    response = user_relation_service.list_friends(get_jwt_identity(), query)
    return jsonify(response.model_dump(mode="json")), 200


@user_bp.route("/me/friends/<user_id>", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
def remove_friend(user_id):
    user_id = parse_user_id(user_id)
    user_relation_service.remove_friend(get_jwt_identity(), user_id)
    return current_app.response_class(status=204)


@user_bp.route("/me/blocks", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(UserPageQuery)
def list_blocks(query: UserPageQuery):
    response = user_relation_service.list_blocks(get_jwt_identity(), query)
    return jsonify(response.model_dump(mode="json")), 200


@user_bp.route("/me/blocks/<user_id>", methods=["PUT"])
@jwt_required(locations=["headers", "cookies"])
def block_user(user_id):
    user_id = parse_user_id(user_id)
    user_relation_service.block_user(get_jwt_identity(), user_id)
    return current_app.response_class(status=204)


@user_bp.route("/me/blocks/<user_id>", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
def unblock_user(user_id):
    user_id = parse_user_id(user_id)
    user_relation_service.unblock_user(get_jwt_identity(), user_id)
    return current_app.response_class(status=204)


@user_bp.route("/me/restrictions", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(UserPageQuery)
def list_restrictions(query: UserPageQuery):
    response = user_relation_service.list_restrictions(
        get_jwt_identity(), query
    )
    return jsonify(response.model_dump(mode="json")), 200


@user_bp.route("/me/restrictions/<user_id>", methods=["PUT"])
@jwt_required(locations=["headers", "cookies"])
def restrict_user(user_id):
    user_id = parse_user_id(user_id)
    user_relation_service.restrict_user(get_jwt_identity(), user_id)
    return current_app.response_class(status=204)


@user_bp.route("/me/restrictions/<user_id>", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
def unrestrict_user(user_id):
    user_id = parse_user_id(user_id)
    user_relation_service.unrestrict_user(get_jwt_identity(), user_id)
    return current_app.response_class(status=204)
