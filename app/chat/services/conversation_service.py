from uuid import UUID

from app.chat.db.connection import get_db_connection_context
from app.chat.models.conversation_model import (
    ConversationCreateRequest, ConversationPageQuery, ConversationPageResponse,
    ConversationResponse,
)
from app.auth.services.errors import ServiceError
from app.user.models.user_model import UserPostsCursor
from app.user.utils.pagination import decode_cursor, encode_cursor


def _base_query():
    return """
        SELECT c.id, c.user_low_id, c.user_high_id, c.last_message_seq,
               c.created_at, c.updated_at,
               peer.id AS peer_id, peer.username AS peer_username,
               COALESCE(peer_profile.display_name, peer.username)
                   AS peer_display_name,
               NULL::text AS peer_avatar_url,
               COALESCE((SELECT COUNT(*) FROM public.messages unread
                WHERE unread.conversation_id = c.id
                  AND unread.sender_id <> %(actor_id)s::uuid
                  AND unread.deleted_at IS NULL
                  AND unread.seq > COALESCE(actor_member.last_read_seq, 0)), 0
               )::int AS unread_count,
               (SELECT jsonb_build_object(
                   'id', m.id, 'conversation_id', m.conversation_id,
                   'sender', jsonb_build_object(
                       'id', sender.id, 'username', sender.username,
                       'display_name', COALESCE(sender_profile.display_name,
                                                sender.username),
                       'avatar_url', NULL),
                   'seq', m.seq, 'client_message_id', m.client_message_id,
                   'body', m.body, 'attachments', '[]'::jsonb,
                   'is_deleted', m.deleted_at IS NOT NULL,
                   'created_at', m.created_at, 'updated_at', m.updated_at)
                FROM public.messages m
                JOIN public.users sender ON sender.id = m.sender_id
                LEFT JOIN public.user_profiles sender_profile
                  ON sender_profile.user_id = sender.id
                WHERE m.conversation_id = c.id
                ORDER BY m.seq DESC LIMIT 1) AS last_message
        FROM public.conversations c
        JOIN public.conversation_members actor_member
          ON actor_member.conversation_id = c.id
         AND actor_member.user_id = %(actor_id)s::uuid
        JOIN public.users peer
          ON peer.id = CASE WHEN c.user_low_id = %(actor_id)s::uuid
                            THEN c.user_high_id ELSE c.user_low_id END
        LEFT JOIN public.user_profiles peer_profile
          ON peer_profile.user_id = peer.id
    """


def _members(cur, conversation_id):
    cur.execute(
        """SELECT user_id, last_read_seq, last_read_at
           FROM public.conversation_members
           WHERE conversation_id = %(conversation_id)s ORDER BY user_id""",
        {"conversation_id": conversation_id},
    )
    return [dict(row) for row in cur.fetchall()]


def _response(cur, row):
    return ConversationResponse.model_validate({
        "id": row["id"],
        "peer": {
            "id": row["peer_id"], "username": row["peer_username"],
            "display_name": row["peer_display_name"],
            "avatar_url": row["peer_avatar_url"],
        },
        "members": _members(cur, row["id"]),
        "last_message_seq": row["last_message_seq"],
        "last_message": row["last_message"],
        "unread_count": row["unread_count"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    })


def create_conversation(actor_id, body: ConversationCreateRequest):
    actor_id, peer_id = str(UUID(str(actor_id))), str(body.user_id)
    if actor_id == peer_id:
        raise ServiceError({"error": "SELF_RELATION_NOT_ALLOWED"}, 422)
    low_id, high_id = sorted((actor_id, peer_id))
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM public.users
                   WHERE id = %(id)s AND status = 'ACTIVE'
                     AND deleted_at IS NULL""", {"id": peer_id})
            if cur.fetchone() is None:
                raise ServiceError({"error": "NOT_FOUND"}, 404)
            cur.execute(
                """INSERT INTO public.conversations (user_low_id, user_high_id)
                   VALUES (%(low)s, %(high)s)
                   ON CONFLICT (user_low_id, user_high_id) DO NOTHING
                   RETURNING id""", {"low": low_id, "high": high_id})
            inserted = cur.fetchone()
            created = inserted is not None
            if inserted is None:
                cur.execute(
                    """SELECT id FROM public.conversations
                       WHERE user_low_id = %(low)s AND user_high_id = %(high)s""",
                    {"low": low_id, "high": high_id})
                conversation_id = cur.fetchone()["id"]
            else:
                conversation_id = inserted["id"]
            cur.execute(
                _base_query() + " WHERE c.id = %(conversation_id)s",
                {"actor_id": actor_id, "conversation_id": conversation_id})
            response = _response(cur, cur.fetchone())
        conn.commit()
    return response, created


def list_conversations(actor_id, query: ConversationPageQuery):
    actor_id = str(UUID(str(actor_id)))
    position = decode_cursor(
        query.cursor, "conversations", actor_id, {}, UserPostsCursor)
    params = {"actor_id": actor_id, "limit": query.limit + 1}
    where = ""
    if position:
        where = (" WHERE (c.updated_at, c.id) < "
                 "(%(cursor_created_at)s, %(cursor_id)s)")
        params.update(cursor_created_at=position.created_at,
                      cursor_id=str(position.id))
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(_base_query() + where
                        + " ORDER BY c.updated_at DESC, c.id DESC LIMIT %(limit)s",
                        params)
            rows = cur.fetchall()
            has_more = len(rows) > query.limit
            rows = rows[:query.limit]
            data = [_response(cur, row) for row in rows]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            "conversations", actor_id, {},
            {"created_at": last["updated_at"], "id": str(last["id"])})
    return ConversationPageResponse(
        data=data,
        pagination={"limit": query.limit, "has_more": has_more,
                    "next_cursor": next_cursor})


def get_conversation(actor_id, conversation_id):
    actor_id, conversation_id = str(UUID(str(actor_id))), str(UUID(str(conversation_id)))
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(_base_query() + " WHERE c.id = %(conversation_id)s",
                        {"actor_id": actor_id, "conversation_id": conversation_id})
            row = cur.fetchone()
            if row is None:
                raise ServiceError({"error": "NOT_FOUND"}, 404)
            return _response(cur, row)