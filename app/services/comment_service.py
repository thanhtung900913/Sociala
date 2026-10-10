from flask import current_app

from app.db.connection import get_db_connection_context
from app.models.post_model import (
    CommentResponseBody, CommentsResponseBody, CreateCommentRequestBody,
    PostPageCursor, PostPageQuery,
)
from app.services import post_service, user_service
from app.services.errors import ServiceError
from app.utils.pagination import decode_cursor


# The same actor policy is used for membership, tombstones and reply counts.
_READABLE_COMMENT = """
    c.deleted_at IS NULL AND u.status = 'ACTIVE' AND u.deleted_at IS NULL
    AND NOT EXISTS (
        SELECT 1 FROM public.user_blocks b
        WHERE (b.blocker_id = %(viewer_id)s AND b.blocked_id = c.author_id)
           OR (b.blocker_id = c.author_id AND b.blocked_id = %(viewer_id)s)
    )
"""

_READABLE_REPLY = """
    reply.deleted_at IS NULL AND ru.status = 'ACTIVE'
    AND ru.deleted_at IS NULL
    AND NOT EXISTS (
        SELECT 1 FROM public.user_blocks rb
        WHERE (rb.blocker_id = %(viewer_id)s
               AND rb.blocked_id = reply.author_id)
           OR (rb.blocker_id = reply.author_id
               AND rb.blocked_id = %(viewer_id)s)
    )
"""

_COMMENT_SELECT = f"""
    SELECT c.id, c.post_id, c.parent_comment_id, c.content,
           c.created_at, c.updated_at, c.deleted_at,
           c.author_id, u.username AS author_username,
           COALESCE(profile.display_name, u.username) AS author_display_name,
           to_jsonb(avatar) AS author_avatar,
           ({_READABLE_COMMENT}) AS is_readable,
           (SELECT COUNT(*) FROM public.comments reply
            JOIN public.users ru ON ru.id = reply.author_id
            WHERE reply.parent_comment_id = c.id
              AND reply.post_id = c.post_id
              AND {_READABLE_REPLY}) AS reply_count,
           (SELECT COUNT(*) FROM public.comment_likes cl
            JOIN public.users liker ON liker.id = cl.user_id
            WHERE cl.comment_id = c.id
              AND liker.status = 'ACTIVE' AND liker.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM public.user_blocks lb
                  WHERE (lb.blocker_id = %(viewer_id)s
                         AND lb.blocked_id = cl.user_id)
                     OR (lb.blocker_id = cl.user_id
                         AND lb.blocked_id = %(viewer_id)s)
              )) AS like_count,
           EXISTS (SELECT 1 FROM public.comment_likes mine
                   WHERE mine.comment_id = c.id
                     AND mine.user_id = %(viewer_id)s) AS liked_by_me
    FROM public.comments c
    JOIN public.users u ON u.id = c.author_id
    LEFT JOIN public.user_profiles profile ON profile.user_id = u.id
    LEFT JOIN public.media_assets avatar ON avatar.id = profile.avatar_media_id
"""


def _comment_data(row):
    readable = row["is_readable"]
    author = None
    if readable:
        author = user_service.build_user_summary({
            "id": row["author_id"], "username": row["author_username"],
            "display_name": row["author_display_name"],
            "avatar": row["author_avatar"],
        })
    return {
        "id": row["id"], "post_id": row["post_id"], "author": author,
        "parent_comment_id": row["parent_comment_id"],
        "content": row["content"] if readable else None,
        "is_deleted": row["deleted_at"] is not None,
        "is_unavailable": not readable, "reply_count": row["reply_count"],
        "like_count": row["like_count"] if readable else 0,
        "liked_by_me": row["liked_by_me"] if readable else False,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _require_parent(cur, actor_id, post_id, parent_id):
    cur.execute(
        f"""
        SELECT c.post_id, c.parent_comment_id,
               ({_READABLE_COMMENT}) AS is_readable
        FROM public.comments c
        JOIN public.users u ON u.id = c.author_id
        WHERE c.id = %(parent_id)s FOR SHARE OF c
        """,
        {"parent_id": str(parent_id), "viewer_id": actor_id},
    )
    parent = cur.fetchone()
    if parent is None:
        raise ServiceError({"error": "PARENT_UNAVAILABLE"}, 409)
    if str(parent["post_id"]) != post_id or parent["parent_comment_id"]:
        raise ServiceError({"error": "INVALID_COMMENT_PARENT"}, 422)
    if not parent["is_readable"]:
        raise ServiceError({"error": "PARENT_UNAVAILABLE"}, 409)


def create_comment(
    actor_id, post_id, body: CreateCommentRequestBody
) -> CommentResponseBody:
    if body.parent_comment_id is not None and not current_app.config.get(
        "COMMENT_REPLIES_ENABLED", True
    ):
        raise ServiceError({"error": "REPLIES_NOT_ENABLED"}, 422)
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            post_service._require_readable_post(cur, actor_id, post_id)
            if body.parent_comment_id is not None:
                _require_parent(
                    cur, actor_id, post_id, body.parent_comment_id
                )
            cur.execute(
                """
                INSERT INTO public.comments
                    (post_id, author_id, content, parent_comment_id)
                VALUES (%(post_id)s, %(actor_id)s, %(content)s, %(parent_id)s)
                RETURNING id
                """,
                {
                    "post_id": post_id, "actor_id": actor_id,
                    "content": body.content,
                    "parent_id": (
                        str(body.parent_comment_id)
                        if body.parent_comment_id else None
                    ),
                },
            )
            comment_id = cur.fetchone()["id"]
            cur.execute(
                _COMMENT_SELECT + " WHERE c.id = %(comment_id)s",
                {"comment_id": comment_id, "viewer_id": actor_id},
            )
            data = _comment_data(cur.fetchone())
        conn.commit()
    return CommentResponseBody.model_validate(data)


def list_comments(
    viewer_id, post_id, query: PostPageQuery
) -> CommentsResponseBody:
    filters = {"post_id": post_id}
    position = decode_cursor(
        query.cursor, "post-comments", viewer_id, filters, PostPageCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            post_service._require_readable_post(
                cur, viewer_id, post_id, lock=False
            )
            cur.execute(
                _COMMENT_SELECT + f"""
                WHERE c.post_id = %(post_id)s AND c.parent_comment_id IS NULL
                  AND (({_READABLE_COMMENT}) OR EXISTS (
                      SELECT 1 FROM public.comments reply
                      JOIN public.users ru ON ru.id = reply.author_id
                      WHERE reply.parent_comment_id = c.id
                        AND reply.post_id = c.post_id
                        AND {_READABLE_REPLY}
                  ))
                  AND (%(after_created_at)s::timestamptz IS NULL
                       OR (c.created_at, c.id) >
                          (%(after_created_at)s::timestamptz,
                           %(after_id)s::uuid))
                ORDER BY c.created_at ASC, c.id ASC LIMIT %(fetch_limit)s
                """,
                post_service._page_params(viewer_id, post_id, query, position),
            )
            rows = cur.fetchall()
            data = [_comment_data(row) for row in rows[:query.limit]]
        conn.commit()
    return CommentsResponseBody.model_validate({
        "data": data,
        "pagination": post_service._pagination(
            rows, query, "post-comments", viewer_id, filters
        ),
    })
