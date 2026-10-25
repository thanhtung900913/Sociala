from uuid import UUID

from app.auth.services.errors import ServiceError
from app.chat.db.connection import get_db_connection_context
from app.chat.models.message_model import (
    MessageCreateRequest, MessagePageQuery, MessagePageResponse,
    MessageResponse, MessageSyncQuery,
)
from app.user.models.user_model import UserPostsCursor
from app.user.utils.pagination import decode_cursor, encode_cursor


def _message(cur, row):
    return MessageResponse.model_validate({
        "id": row["id"], "conversation_id": row["conversation_id"],
        "sender": ({
            "id": row["sender_id"], "username": row["username"],
            "display_name": row["display_name"], "avatar_url": None
        } if row["sender_id"] else None),
        "seq": row["seq"], "client_message_id": row["client_message_id"],
        "body": None if row["deleted_at"] else row["body"],
        "attachments": [] if row["deleted_at"] else row["attachments"],
        "is_deleted": row["deleted_at"] is not None,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    })


def _message_query():
    return """
        SELECT m.id, m.conversation_id, m.sender_id, m.seq,
               m.client_message_id, m.body, m.created_at, m.updated_at,
               m.deleted_at, u.username,
               COALESCE(profile.display_name, u.username) AS display_name,
               COALESCE((SELECT jsonb_agg(jsonb_build_object(
                   'media_id', ma.media_id, 'position', ma.position)
                   ORDER BY ma.position)
                   FROM public.message_attachments ma
                   WHERE ma.message_id = m.id), '[]'::jsonb) AS attachments
        FROM public.messages m
        LEFT JOIN public.users u ON u.id = m.sender_id
        LEFT JOIN public.user_profiles profile ON profile.user_id = u.id
    """


def _require_member(cur, actor_id, conversation_id):
    cur.execute(
        """SELECT 1 FROM public.conversation_members
           WHERE conversation_id = %(conversation_id)s AND user_id = %(actor_id)s""",
        {"conversation_id": conversation_id, "actor_id": actor_id},
    )
    if cur.fetchone() is None:
        raise ServiceError({"error": "NOT_FOUND"}, 404)


def send_message(actor_id, conversation_id, body: MessageCreateRequest):
    actor_id = str(UUID(str(actor_id)))
    conversation_id = str(UUID(str(conversation_id)))
    media_ids = [str(item) for item in body.media_ids]
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            _require_member(cur, actor_id, conversation_id)
            cur.execute(
                _message_query() + """
                WHERE m.conversation_id = %(conversation_id)s
                  AND m.sender_id = %(actor_id)s
                  AND m.client_message_id = %(client_message_id)s
                """,
                {"conversation_id": conversation_id, "actor_id": actor_id,
                 "client_message_id": str(body.client_message_id)},
            )
            existing = cur.fetchone()
            if existing:
                if existing["body"] != body.body:
                    raise ServiceError({"error": "IDEMPOTENCY_CONFLICT"}, 409)
                cur.execute(
                    """SELECT media_id FROM public.message_attachments
                       WHERE message_id = %(message_id)s ORDER BY position""",
                    {"message_id": existing["id"]},
                )
                if [str(row["media_id"]) for row in cur.fetchall()] != media_ids:
                    raise ServiceError({"error": "IDEMPOTENCY_CONFLICT"}, 409)
                response = _message(cur, existing)
                status = 200
            else:
                cur.execute(
                    """INSERT INTO public.messages
                       (conversation_id, sender_id, client_message_id, body)
                       VALUES (%(conversation_id)s, %(actor_id)s,
                               %(client_message_id)s, %(body)s)
                       RETURNING id""",
                    {"conversation_id": conversation_id, "actor_id": actor_id,
                     "client_message_id": str(body.client_message_id),
                     "body": body.body},
                )
                message_id = cur.fetchone()["id"]
                for position, media_id in enumerate(media_ids):
                    cur.execute(
                        """INSERT INTO public.message_attachments
                           (message_id, media_id, position)
                           SELECT %(message_id)s, id, %(position)s
                           FROM public.media_assets
                           WHERE id = %(media_id)s AND owner_id = %(actor_id)s
                             AND status = 'READY' AND deleted_at IS NULL""",
                        {"message_id": message_id, "media_id": media_id,
                         "position": position, "actor_id": actor_id},
                    )
                    if cur.rowcount != 1:
                        raise ServiceError({"error": "INVALID_ATTACHMENT"}, 422)
                cur.execute(
                    _message_query() + " WHERE m.id = %(message_id)s",
                    {"message_id": message_id},
                )
                response = _message(cur, cur.fetchone())
                status = 201
        conn.commit()
    return response, status


def list_messages(actor_id, conversation_id, query: MessagePageQuery):
    actor_id, conversation_id = str(UUID(str(actor_id))), str(UUID(str(conversation_id)))
    position = decode_cursor(
        query.cursor, "messages", actor_id, {"conversation_id": conversation_id},
        UserPostsCursor)
    params = {"conversation_id": conversation_id, "limit": query.limit + 1}
    where = ""
    if position:
        where = " AND (m.created_at, m.id) < (%(cursor_created_at)s, %(cursor_id)s)"
        params.update(cursor_created_at=position.created_at, cursor_id=str(position.id))
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            _require_member(cur, actor_id, conversation_id)
            cur.execute(_message_query() + """
                WHERE m.conversation_id = %(conversation_id)s""" + where
                + " ORDER BY m.created_at DESC, m.id DESC LIMIT %(limit)s", params)
            rows = cur.fetchall()
            has_more = len(rows) > query.limit
            rows = rows[:query.limit]
            data = [_message(cur, row) for row in rows]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            "messages", actor_id, {"conversation_id": conversation_id},
            {"created_at": last["created_at"], "id": str(last["id"])})
    return MessagePageResponse(
        data=data, pagination={"limit": query.limit, "has_more": has_more,
                               "next_cursor": next_cursor})


def sync_messages(actor_id, conversation_id, query: MessageSyncQuery):
    actor_id, conversation_id = str(UUID(str(actor_id))), str(UUID(str(conversation_id)))
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            _require_member(cur, actor_id, conversation_id)
            cur.execute(_message_query() + """
                WHERE m.conversation_id = %(conversation_id)s AND m.seq > %(after_seq)s
                ORDER BY m.seq ASC LIMIT %(limit)s""",
                {"conversation_id": conversation_id, "after_seq": query.after_seq,
                 "limit": query.limit + 1})
            rows = cur.fetchall()
    has_more = len(rows) > query.limit
    rows = rows[:query.limit]
    return MessagePageResponse(
        data=[_message(None, row) for row in rows],
        pagination={"limit": query.limit, "has_more": has_more, "next_cursor": None})