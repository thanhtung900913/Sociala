from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.models.friend_request_model import (
    RespondFriendRequestBody, SendFriendRequestBody, FriendRequestsQuery,
)
from app.services import friend_request_service
from app.utils.decorators import validate_payload, validate_query
from app.utils.validation import parse_user_id

friend_request_bp = Blueprint("friend_request", __name__)


@friend_request_bp.route("", methods=["POST"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(SendFriendRequestBody)
def send_friend_request(body: SendFriendRequestBody):
    response, created = friend_request_service.send_friend_request(
        get_jwt_identity(), body
    )
    status = 201 if created else 200
    return jsonify({"data": response.model_dump(mode="json")}), status


@friend_request_bp.route("", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(FriendRequestsQuery)
def list_friend_requests(query: FriendRequestsQuery):
    response = friend_request_service.list_friend_requests(
        get_jwt_identity(), query
    )
    return jsonify(response.model_dump(mode="json")), 200


@friend_request_bp.route("/<user_id>/accept", methods=["POST"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(RespondFriendRequestBody)
def accept_friend_request(body: RespondFriendRequestBody, user_id):
    user_id = parse_user_id(user_id)
    response = friend_request_service.accept_friend_request(
        get_jwt_identity(), user_id, body
    )
    return jsonify({"data": response.model_dump(mode="json")}), 200


@friend_request_bp.route("/<user_id>/reject", methods=["POST"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(RespondFriendRequestBody)
def reject_friend_request(body: RespondFriendRequestBody, user_id):
    user_id = parse_user_id(user_id)
    response = friend_request_service.reject_friend_request(
        get_jwt_identity(), user_id, body
    )
    return jsonify({"data": response.model_dump(mode="json")}), 200


@friend_request_bp.route("/<user_id>", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(RespondFriendRequestBody)
def cancel_friend_request(query: RespondFriendRequestBody, user_id):
    user_id = parse_user_id(user_id)
    friend_request_service.cancel_friend_request(
        get_jwt_identity(), user_id, query
    )
    return current_app.response_class(status=204)
