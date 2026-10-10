from flask import current_app

from app.db.connection import get_db_connection_context
from app.models.post_model import (
    CreatePostRequestBody, PostMutationResponseBody, PostPageCursor,
    PostPageQuery, PostResponseBody, PostsResponseBody, PutReactionRequestBody,
    ReactionStateResponseBody, ReactionsQuery, ReactionsResponseBody,
    SharePostRequestBody, UpdatePostRequestBody,
)
from app.models.user_model import UserPageQuery, UserPostsCursor
from app.services import user_service
from app.services.errors import ServiceError
from app.services.media_service import visible_media
from app.utils.pagination import decode_cursor, encode_cursor

REACTION_TYPES = ("LIKE", "LOVE", "HAHA", "WOW", "SAD", "ANGRY")


def _require_readable_post(cur, viewer_id, post_id, *, lock=True):
    """Authorize share/source; optionally hold them live during a write."""
    cur.execute(
        """
        SELECT p.id, p.kind, p.shared_post_id, p.created_at
        FROM public.posts p
        WHERE p.id = %(post_id)s
          AND public.can_view_post(p.id, %(viewer_id)s::uuid)
        """ + (" FOR SHARE" if lock else ""),
        {"post_id": post_id, "viewer_id": viewer_id},
    )
    post = cur.fetchone()
    if post is None:
        raise ServiceError({"error": "NOT_FOUND"}, 404)
    if post["kind"] == "SHARE":
        cur.execute(
            """
            SELECT p.id FROM public.posts p
            WHERE p.id = %(post_id)s AND p.kind = 'ORIGINAL'
              AND public.can_view_post(p.id, %(viewer_id)s::uuid)
            """ + (" FOR SHARE" if lock else ""),
            {"post_id": post["shared_post_id"], "viewer_id": viewer_id},
        )
        if cur.fetchone() is None:
            raise ServiceError({"error": "NOT_FOUND"}, 404)
    return post


def _post_data(cur, viewer_id, post):
    ids = [str(post["id"])]
    if post["kind"] == "SHARE":
        ids.append(str(post["shared_post_id"]))
    posts = _load_posts(cur, viewer_id, ids)
    result = posts.get(str(post["id"]))
    if result is None:
        raise ServiceError({"error": "NOT_FOUND"}, 404)
    if result["kind"] == "SHARE":
        original = posts.get(str(result["shared_post_id"]))
        if original is None or original["kind"] != "ORIGINAL":
            raise ServiceError({"error": "NOT_FOUND"}, 404)
        result["original_post"] = original
    return result


def _validate_attachments(cur, actor_id, attachments):
    # Stable lock order prevents opposite attachment orders from deadlocking.
    for item in sorted(attachments, key=lambda item: str(item.media_id)):
        cur.execute(
            """
            SELECT id, status, content_type FROM public.media_assets
            WHERE id = %(media_id)s AND owner_id = %(actor_id)s
              AND deleted_at IS NULL
            FOR SHARE
            """,
            {"media_id": str(item.media_id), "actor_id": actor_id},
        )
        media = cur.fetchone()
        if media is None:
            raise ServiceError({"error": "NOT_FOUND"}, 404)
        if media["status"] != "READY":
            raise ServiceError({"error": "MEDIA_NOT_READY"}, 409)
        if media["content_type"] not in {
            "image/jpeg", "image/png", "image/webp",
        }:
            raise ServiceError({"error": "INVALID_ATTACHMENT"}, 422)


def _insert_attachments(cur, post_id, attachments):
    for position, item in enumerate(attachments):
        cur.execute(
            """
            INSERT INTO public.post_attachments
                (post_id, media_id, position, alt_text)
            VALUES (%(post_id)s, %(media_id)s, %(position)s, %(alt_text)s)
            """,
            {
                "post_id": post_id, "media_id": str(item.media_id),
                "position": position, "alt_text": item.alt_text,
            },
        )


def _owned_post(cur, actor_id, post_id):
    cur.execute(
        """
        SELECT id, author_id, kind, content, visibility, deleted_at
        FROM public.posts WHERE id = %(post_id)s FOR UPDATE
        """,
        {"post_id": post_id},
    )
    post = cur.fetchone()
    if post is None:
        raise ServiceError({"error": "NOT_FOUND"}, 404)
    if str(post["author_id"]) != actor_id:
        raise ServiceError({"error": "FORBIDDEN"}, 403)
    return post


def create_post(actor_id, body: CreatePostRequestBody) -> PostResponseBody:
    if body.content is None and not body.attachments:
        raise ServiceError({"error": "EMPTY_POST"}, 422)
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            _validate_attachments(cur, actor_id, body.attachments)
            cur.execute(
                """
                INSERT INTO public.posts (author_id, content, visibility)
                VALUES (%(actor_id)s, %(content)s, %(visibility)s)
                RETURNING id
                """,
                {
                    "actor_id": actor_id, "content": body.content,
                    "visibility": body.visibility,
                },
            )
            post_id = str(cur.fetchone()["id"])
            _insert_attachments(cur, post_id, body.attachments)
            post = _require_readable_post(cur, actor_id, post_id)
            data = _post_data(cur, actor_id, post)
        conn.commit()
    return PostResponseBody.model_validate(data)


def get_post(viewer_id, post_id) -> PostResponseBody:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            post = _require_readable_post(cur, viewer_id, post_id, lock=False)
            data = _post_data(cur, viewer_id, post)
        conn.commit()
    return PostResponseBody.model_validate(data)


def update_post(
    actor_id, post_id, body: UpdatePostRequestBody
) -> PostMutationResponseBody:
    changes = body.model_fields_set
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            post = _owned_post(cur, actor_id, post_id)
            if post["deleted_at"] is not None:
                raise ServiceError({"error": "RESOURCE_DELETED"}, 409)
            content = body.content if "content" in changes else post["content"]
            visibility = (
                body.visibility if "visibility" in changes
                else post["visibility"]
            )
            if "attachments" in changes:
                if post["kind"] == "SHARE":
                    raise ServiceError(
                        {"error": "SHARE_ATTACHMENTS_NOT_ALLOWED"}, 422
                    )
                _validate_attachments(cur, actor_id, body.attachments)
                has_attachments = bool(body.attachments)
            else:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM public.post_attachments
                        WHERE post_id = %(post_id)s
                    ) AS has_attachments
                    """,
                    {"post_id": post_id},
                )
                has_attachments = cur.fetchone()["has_attachments"]
            if (
                post["kind"] == "ORIGINAL" and not content
                and not has_attachments
            ):
                raise ServiceError({"error": "EMPTY_POST"}, 422)
            if "attachments" in changes:
                cur.execute(
                    "DELETE FROM public.post_attachments "
                    "WHERE post_id = %(post_id)s", {"post_id": post_id},
                )
                _insert_attachments(cur, post_id, body.attachments)
            cur.execute(
                """
                UPDATE public.posts
                SET content = %(content)s, visibility = %(visibility)s
                WHERE id = %(post_id)s RETURNING id, updated_at
                """,
                {
                    "post_id": post_id, "content": content,
                    "visibility": visibility,
                },
            )
            data = cur.fetchone()
        conn.commit()
    return PostMutationResponseBody.model_validate(data)


def delete_post(actor_id, post_id):
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            post = _owned_post(cur, actor_id, post_id)
            if post["deleted_at"] is None:
                cur.execute(
                    """
                    UPDATE public.posts SET deleted_at = statement_timestamp()
                    WHERE id = %(post_id)s
                    """,
                    {"post_id": post_id},
                )
        conn.commit()


def hide_post(actor_id, post_id):
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            _require_readable_post(cur, actor_id, post_id)
            cur.execute(
                """
                INSERT INTO public.hidden_posts (user_id, post_id)
                VALUES (%(actor_id)s, %(post_id)s) ON CONFLICT DO NOTHING
                """,
                {"actor_id": actor_id, "post_id": post_id},
            )
        conn.commit()


def unhide_post(actor_id, post_id):
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM public.hidden_posts
                WHERE user_id = %(actor_id)s AND post_id = %(post_id)s
                """,
                {"actor_id": actor_id, "post_id": post_id},
            )
        conn.commit()


def share_post(
    actor_id, post_id, body: SharePostRequestBody
) -> PostResponseBody:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            post = _require_readable_post(cur, actor_id, post_id)
            original_id = (
                post["shared_post_id"] if post["kind"] == "SHARE"
                else post["id"]
            )
            cur.execute(
                """
                INSERT INTO public.posts
                    (author_id, kind, content, visibility, shared_post_id)
                VALUES (%(actor_id)s, 'SHARE', %(content)s,
                        %(visibility)s, %(original_id)s) RETURNING id
                """,
                {
                    "actor_id": actor_id, "content": body.content,
                    "visibility": body.visibility,
                    "original_id": str(original_id),
                },
            )
            new_id = str(cur.fetchone()["id"])
            share = _require_readable_post(cur, actor_id, new_id)
            data = _post_data(cur, actor_id, share)
        conn.commit()
    return PostResponseBody.model_validate(data)


def _page_params(viewer_id, post_id, query, position):
    return {
        "viewer_id": viewer_id, "post_id": post_id,
        "after_created_at": position.created_at if position else None,
        "after_id": str(position.id) if position else None,
        "fetch_limit": query.limit + 1,
    }


def _pagination(rows, query, route, viewer_id, filters):
    has_more = len(rows) > query.limit
    next_cursor = None
    if has_more:
        last = rows[query.limit - 1]
        next_cursor = encode_cursor(
            route, viewer_id, filters,
            {
                "created_at": last["created_at"].isoformat(),
                "id": str(last["id"]),
            },
        )
    return {
        "limit": query.limit, "has_more": has_more,
        "next_cursor": next_cursor,
    }


def list_shares(viewer_id, post_id, query: PostPageQuery) -> PostsResponseBody:
    filters = {"post_id": post_id}
    position = decode_cursor(
        query.cursor, "post-shares", viewer_id, filters, PostPageCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            post = _require_readable_post(cur, viewer_id, post_id, lock=False)
            original_id = (
                post["shared_post_id"] if post["kind"] == "SHARE"
                else post["id"]
            )
            params = _page_params(viewer_id, post_id, query, position)
            params["original_id"] = str(original_id)
            cur.execute(
                """
                SELECT p.id, p.kind, p.shared_post_id, p.created_at
                FROM public.posts p
                WHERE p.kind = 'SHARE'
                  AND p.shared_post_id = %(original_id)s
                  AND public.can_view_post(p.id, %(viewer_id)s::uuid)
                  AND (%(after_created_at)s::timestamptz IS NULL
                       OR (p.created_at, p.id) <
                          (%(after_created_at)s::timestamptz,
                           %(after_id)s::uuid))
                ORDER BY p.created_at DESC, p.id DESC LIMIT %(fetch_limit)s
                """,
                params,
            )
            rows = cur.fetchall()
            ids = [str(row["id"]) for row in rows[:query.limit]]
            posts = _load_posts(
                cur, viewer_id, ids + [str(original_id)]
            ) if ids else {}
            data = []
            for row in rows[:query.limit]:
                share = posts.get(str(row["id"]))
                original = posts.get(str(original_id))
                if share is not None and original is not None:
                    share["original_post"] = original
                    data.append(share)
        conn.commit()
    return PostsResponseBody.model_validate({
        "data": data,
        "pagination": _pagination(
            rows, query, "post-shares", viewer_id, filters
        ),
    })


def put_reaction(
    actor_id, post_id, body: PutReactionRequestBody
) -> ReactionStateResponseBody:
    if body.reaction_type not in current_app.config.get(
        "POST_ENABLED_REACTIONS", REACTION_TYPES
    ):
        raise ServiceError({"error": "REACTION_NOT_ENABLED"}, 422)
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            post = _require_readable_post(cur, actor_id, post_id)
            cur.execute(
                """
                INSERT INTO public.post_reactions
                    (post_id, user_id, reaction_type)
                VALUES (%(post_id)s, %(actor_id)s, %(reaction_type)s)
                ON CONFLICT (post_id, user_id) DO UPDATE
                SET reaction_type = %(reaction_type)s
                """,
                {
                    "post_id": post_id, "actor_id": actor_id,
                    "reaction_type": body.reaction_type,
                },
            )
            data = _post_data(cur, actor_id, post)
        conn.commit()
    return ReactionStateResponseBody.model_validate({
        "post_id": post_id, "reaction_type": body.reaction_type,
        "counts": data["counts"],
    })


def remove_reaction(actor_id, post_id):
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM public.post_reactions
                WHERE post_id = %(post_id)s AND user_id = %(actor_id)s
                """,
                {"post_id": post_id, "actor_id": actor_id},
            )
        conn.commit()


def list_reactions(
    viewer_id, post_id, query: ReactionsQuery
) -> ReactionsResponseBody:
    filters = {"post_id": post_id, "reaction_type": query.reaction_type}
    position = decode_cursor(
        query.cursor, "post-reactions", viewer_id, filters, PostPageCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            _require_readable_post(cur, viewer_id, post_id, lock=False)
            params = _page_params(viewer_id, post_id, query, position)
            params["reaction_type"] = query.reaction_type
            params["enabled_types"] = list(current_app.config.get(
                "POST_ENABLED_REACTIONS", REACTION_TYPES
            ))
            cur.execute(
                """
                SELECT r.user_id AS id, r.created_at, r.reaction_type,
                       u.username,
                       COALESCE(profile.display_name, u.username)
                           AS display_name,
                       to_jsonb(avatar) AS avatar
                FROM public.post_reactions r
                JOIN public.users u ON u.id = r.user_id
                LEFT JOIN public.user_profiles profile
                  ON profile.user_id = u.id
                LEFT JOIN public.media_assets avatar
                  ON avatar.id = profile.avatar_media_id
                WHERE r.post_id = %(post_id)s
                  AND r.reaction_type = ANY(%(enabled_types)s::text[])
                  AND u.status = 'ACTIVE' AND u.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM public.user_blocks b
                      WHERE (b.blocker_id = %(viewer_id)s
                             AND b.blocked_id = r.user_id)
                         OR (b.blocker_id = r.user_id
                             AND b.blocked_id = %(viewer_id)s)
                  )
                  AND (%(reaction_type)s::text IS NULL
                       OR r.reaction_type = %(reaction_type)s)
                  AND (%(after_created_at)s::timestamptz IS NULL
                       OR (r.created_at, r.user_id) <
                          (%(after_created_at)s::timestamptz,
                           %(after_id)s::uuid))
                ORDER BY r.created_at DESC, r.user_id DESC
                LIMIT %(fetch_limit)s
                """,
                params,
            )
            rows = cur.fetchall()
            data = [{
                "user": user_service.build_user_summary(row),
                "reaction_type": row["reaction_type"],
                "created_at": row["created_at"],
            } for row in rows[:query.limit]]
        conn.commit()
    return ReactionsResponseBody.model_validate({
        "data": data,
        "pagination": _pagination(
            rows, query, "post-reactions", viewer_id, filters
        ),
    })


def _load_posts(cur, viewer_id, post_ids):
    """Load posts and share originals in batches in the caller's snapshot."""
    params = {"viewer_id": viewer_id, "post_ids": post_ids}
    cur.execute(
        """
        SELECT p.id, p.author_id, p.content, p.visibility, p.kind,
               p.shared_post_id,
               p.created_at, p.updated_at,
               u.username AS author_username,
               COALESCE(profile.display_name, u.username)
                   AS author_display_name,
               to_jsonb(avatar) AS author_avatar
        FROM public.posts p
        JOIN public.users u ON u.id = p.author_id
        LEFT JOIN public.user_profiles profile ON profile.user_id = u.id
        LEFT JOIN public.media_assets avatar
          ON avatar.id = profile.avatar_media_id
        WHERE p.id = ANY(%(post_ids)s::uuid[])
          AND public.can_view_post(p.id, %(viewer_id)s::uuid)
        """,
        params,
    )
    posts = {}
    for row in cur.fetchall():
        post = {
            **{name: row[name] for name in (
                "id", "content", "visibility", "kind", "shared_post_id",
                "created_at", "updated_at",
            )},
            "author": user_service.build_user_summary({
                "id": row["author_id"],
                "username": row["author_username"],
                "display_name": row["author_display_name"],
                "avatar": row["author_avatar"],
            }),
            "attachments": [],
            "counts": {
                "reactions": 0, "comments": 0, "shares": 0,
                "by_reaction": dict.fromkeys(REACTION_TYPES, 0),
            },
            "my_reaction": None,
            "original_post": None,
        }
        posts[str(row["id"])] = post

    cur.execute(
        """
        SELECT a.post_id, a.position, a.alt_text, to_jsonb(m) AS media
        FROM public.post_attachments a
        JOIN public.posts p ON p.id = a.post_id
        JOIN public.media_assets m ON m.id = a.media_id
        WHERE a.post_id = ANY(%(post_ids)s::uuid[])
          AND p.kind = 'ORIGINAL' AND a.position < 10
          AND m.owner_id = p.author_id AND m.status = 'READY'
          AND m.deleted_at IS NULL
          AND public.can_view_post(p.id, %(viewer_id)s::uuid)
        ORDER BY a.post_id, a.position
        """,
        params,
    )
    for row in cur.fetchall():
        post = posts.get(str(row["post_id"]))
        if post is None:
            continue
        media = visible_media(row["media"], post["author"]["id"])
        if media:
            post["attachments"].append({
                "position": row["position"], "alt_text": row["alt_text"],
                "media": media,
            })

    cur.execute(
        """
        SELECT r.post_id, r.reaction_type, COUNT(*) AS count,
               BOOL_OR(r.user_id = %(viewer_id)s::uuid) AS reacted_by_me
        FROM public.post_reactions r
        JOIN public.users reactor ON reactor.id = r.user_id
        WHERE r.post_id = ANY(%(post_ids)s::uuid[])
          AND reactor.status = 'ACTIVE' AND reactor.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM public.user_blocks b
              WHERE (b.blocker_id = %(viewer_id)s AND b.blocked_id = r.user_id)
                 OR (b.blocker_id = r.user_id AND b.blocked_id = %(viewer_id)s)
          )
        GROUP BY r.post_id, r.reaction_type
        """,
        params,
    )
    for row in cur.fetchall():
        post = posts.get(str(row["post_id"]))
        if post is None:
            continue
        post["counts"]["by_reaction"][row["reaction_type"]] = row["count"]
        post["counts"]["reactions"] += row["count"]
        if row["reacted_by_me"]:
            post["my_reaction"] = row["reaction_type"]

    cur.execute(
        """
        SELECT c.post_id, 'comments' AS category, COUNT(*) AS count
        FROM public.comments c
        JOIN public.users commenter ON commenter.id = c.author_id
        WHERE c.post_id = ANY(%(post_ids)s::uuid[]) AND c.deleted_at IS NULL
          AND commenter.status = 'ACTIVE' AND commenter.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM public.user_blocks b
              WHERE (b.blocker_id = %(viewer_id)s
                     AND b.blocked_id = c.author_id)
                 OR (b.blocker_id = c.author_id
                     AND b.blocked_id = %(viewer_id)s)
          )
        GROUP BY c.post_id
        UNION ALL
        SELECT s.shared_post_id AS post_id, 'shares' AS category,
               COUNT(*) AS count
        FROM public.posts s
        WHERE s.shared_post_id = ANY(%(post_ids)s::uuid[]) AND s.kind = 'SHARE'
          AND public.can_view_post(s.id, %(viewer_id)s::uuid)
        GROUP BY s.shared_post_id
        """,
        params,
    )
    for row in cur.fetchall():
        post = posts.get(str(row["post_id"]))
        if post:
            post["counts"][row["category"]] = row["count"]
    return posts


def list_user_posts(
    viewer_id, user_id, query: UserPageQuery
) -> PostsResponseBody:
    """List readable profile posts without the home feed's hidden filter."""
    filters = {"user_id": str(user_id)}
    position = decode_cursor(
        query.cursor, "user-posts", viewer_id, filters, UserPostsCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            # Keep page membership, originals and counts in one snapshot.
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            user_service._get_public_profile(
                cur, viewer_id, "u.id = %(user_id)s", {"user_id": user_id}
            )
            cur.execute(
                """
                SELECT p.id, p.kind, p.shared_post_id, p.created_at
                FROM public.posts p
                WHERE p.author_id = %(user_id)s
                  AND public.can_view_post(p.id, %(viewer_id)s::uuid)
                  AND (
                      %(after_created_at)s::timestamptz IS NULL
                      OR (p.created_at, p.id) <
                         (%(after_created_at)s::timestamptz,
                          %(after_id)s::uuid)
                  )
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT %(fetch_limit)s
                """,
                {
                    "viewer_id": viewer_id, "user_id": user_id,
                    "after_created_at": (
                        position.created_at if position else None
                    ),
                    "after_id": str(position.id) if position else None,
                    "fetch_limit": query.limit + 1,
                },
            )
            rows = cur.fetchall()
            has_more = len(rows) > query.limit
            rows = rows[:query.limit]
            ids = {str(row["id"]) for row in rows}
            ids.update(
                str(row["shared_post_id"]) for row in rows
                if row["kind"] == "SHARE" and row["shared_post_id"] is not None
            )
            posts = _load_posts(cur, viewer_id, sorted(ids)) if ids else {}
        conn.commit()

    data = []
    for row in rows:
        post = posts.get(str(row["id"]))
        if post is None:
            continue
        if post["kind"] == "SHARE":
            original = posts.get(str(post["shared_post_id"]))
            if original is None or original["kind"] != "ORIGINAL":
                continue
            post["original_post"] = original
        data.append(post)

    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = encode_cursor(
            "user-posts", viewer_id, filters,
            {
                "created_at": last["created_at"].isoformat(),
                "id": str(last["id"]),
            },
        )
    return PostsResponseBody.model_validate({
        "data": data,
        "pagination": {
            "limit": query.limit, "has_more": has_more,
            "next_cursor": next_cursor,
        },
    })
