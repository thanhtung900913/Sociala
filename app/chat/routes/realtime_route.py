import json
from threading import Lock

from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_sock import Sock
from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import ValidationError
from uuid import UUID

from app.auth.services.errors import ServiceError
from app.chat.models.message_model import MessageCreateRequest
from app.chat.services import message_service

realtime_bp = Blueprint("realtime", __name__)
sock = Sock()
_connections = {}
_connections_lock = Lock()


@realtime_bp.route("/tickets", methods=["POST"])
@jwt_required(locations=["headers", "cookies"])
def create_realtime_ticket():
    ticket = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"] or current_app.config["JWT_SECRET_KEY"],
        salt="realtime-ticket-v1",
    ).dumps({"user_id": str(get_jwt_identity())})
    return jsonify({"data": {"ticket": ticket}}), 201


def _send(connection, message):
    connection.send(json.dumps(message, default=str))


def _broadcast(conversation_id, message):
    with _connections_lock:
        recipients = list(_connections.get(conversation_id, set()))
    for connection in recipients:
        try:
            _send(connection, message)
        except Exception:
            _remove(connection)


def _remove(connection):
    with _connections_lock:
        for connections in _connections.values():
            connections.discard(connection)


def _subscribe(connection, actor_id, conversation_id):
    from app.chat.db.connection import get_db_connection_context

    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM public.conversation_members
                   WHERE conversation_id = %(conversation_id)s
                     AND user_id = %(actor_id)s""",
                {"conversation_id": conversation_id, "actor_id": actor_id},
            )
            if cur.fetchone() is None:
                raise ServiceError({"error": "NOT_FOUND"}, 404)
    with _connections_lock:
        _connections.setdefault(conversation_id, set()).add(connection)


@sock.route("/api/v1/ws")
def websocket_handler(connection):
    actor_id = None
    try:
        initial = json.loads(connection.receive())
        ticket = initial.get("ticket") if isinstance(initial, dict) else None
        serializer = URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"] or current_app.config["JWT_SECRET_KEY"],
            salt="realtime-ticket-v1",
        )
        claims = serializer.loads(
            ticket,
            max_age=int(current_app.config["REALTIME_TICKET_EXPIRES"].total_seconds()),
        ) if ticket else None
        if not claims or not claims.get("user_id"):
            _send(connection, {"type": "error", "payload": {"error": "UNAUTHORIZED"}})
            return
        actor_id = claims["user_id"]
        while True:
            raw = connection.receive()
            if raw is None:
                break
            request = json.loads(raw)
            request_id = request.get("request_id")
            if request.get("type") == "conversation.subscribe":
                try:
                    conversation_id = str(UUID(request["payload"]["conversation_id"]))
                    _subscribe(connection, actor_id, conversation_id)
                    _send(connection, {
                        "type": "conversation.subscribed",
                        "request_id": request_id,
                        "payload": {"conversation_id": conversation_id},
                    })
                except (KeyError, TypeError, ValueError):
                    _send(connection, {
                        "type": "error", "request_id": request_id,
                        "payload": {"error": "VALIDATION_ERROR"},
                    })
                except ServiceError as error:
                    _send(connection, {
                        "type": "error", "request_id": request_id,
                        "payload": error.payload,
                    })
                continue
            if request.get("type") != "message.send":
                _send(connection, {
                    "type": "error", "request_id": request_id,
                    "payload": {"error": "UNSUPPORTED_EVENT"},
                })
                continue
            try:
                payload = MessageCreateRequest.model_validate(request.get("payload", {}))
                conversation_id = str(UUID(request["payload"]["conversation_id"]))
                response, status = message_service.send_message(
                    actor_id, conversation_id, payload)
                _send(connection, {
                    "type": "message.ack", "request_id": request_id,
                    "payload": {
                        "client_message_id": str(payload.client_message_id),
                        "message_id": str(response.id),
                        "status": "accepted",
                    },
                })
                if status == 201:
                    with _connections_lock:
                        _connections.setdefault(conversation_id, set()).add(connection)
                    _broadcast(conversation_id, {
                        "type": "message.created",
                        "payload": response.model_dump(mode="json"),
                    })
            except (KeyError, TypeError, ValueError, ValidationError) as error:
                _send(connection, {
                    "type": "error", "request_id": request_id,
                    "payload": {"error": "VALIDATION_ERROR"},
                })
            except ServiceError as error:
                _send(connection, {
                    "type": "error", "request_id": request_id,
                    "payload": error.payload,
                })
    except (BadData, TypeError, ValueError, json.JSONDecodeError):
        _send(connection, {"type": "error", "payload": {"error": "UNAUTHORIZED"}})
    finally:
        if actor_id:
            _remove(connection)
