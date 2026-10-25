from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.chat.models.conversation_model import (
    ConversationCreateRequest, ConversationPageQuery,
)
from app.chat.models.message_model import MessagePageQuery, MessageSyncQuery
from app.chat.services import conversation_service
from app.chat.services import message_service
from app.chat.utils.decorators import validate_payload, validate_query
from app.chat.utils.validation import parse_conversation_id

conversation_bp = Blueprint("conversation", __name__)


@conversation_bp.route("", methods=["POST"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(ConversationCreateRequest)
def create_conversation(body):
    response, created = conversation_service.create_conversation(
        get_jwt_identity(), body)
    return jsonify({"data": response.model_dump(mode="json")}), (
        201 if created else 200), {
            "Location": f"/api/v1/conversations/{response.id}"}


@conversation_bp.route("", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(ConversationPageQuery)
def list_conversations(query):
    response = conversation_service.list_conversations(get_jwt_identity(), query)
    return jsonify(response.model_dump(mode="json")), 200


@conversation_bp.route("/<conversation_id>", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
def get_conversation(conversation_id):
    response = conversation_service.get_conversation(
        get_jwt_identity(), parse_conversation_id(conversation_id))
    return jsonify({"data": response.model_dump(mode="json")}), 200


@conversation_bp.route("/<conversation_id>/messages", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(MessagePageQuery)
def list_messages(query, conversation_id):
    response = message_service.list_messages(
        get_jwt_identity(), parse_conversation_id(conversation_id), query)
    return jsonify(response.model_dump(mode="json")), 200


@conversation_bp.route("/<conversation_id>/messages/sync", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(MessageSyncQuery)
def sync_messages(query, conversation_id):
    response = message_service.sync_messages(
        get_jwt_identity(), parse_conversation_id(conversation_id), query)
    return jsonify(response.model_dump(mode="json")), 200