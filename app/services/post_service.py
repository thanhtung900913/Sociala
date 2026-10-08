from app.db.connection import get_db_connection_context
from app.models.user_model import UserPageQuery, UserPostsCursor
from app.services import user_service
from app.utils.pagination import decode_cursor, encode_cursor

REACTION_TYPES = ("LIKE", "LOVE", "HAHA", "WOW", "SAD", "ANGRY")


def _load_posts(cur, viewer_id, post_ids):
    """Load page posts and share originals in batches within the caller's snapshot."""
    params = {"viewer_id": viewer_id, "post_ids": post_ids}
    cur.execute(
        """
        SELECT p.id, p.author_id, p.content, p.visibility, p.kind, p.shared_post_id,
               p.created_at, p.updated_at,
               u.username AS author_username,
               COALESCE(profile.display_name, u.username) AS author_display_name,
               to_jsonb(avatar) AS author_avatar
        FROM public.posts p
        JOIN public.users u ON u.id = p.author_id
        LEFT JOIN public.user_profiles profile ON profile.user_id = u.id
        LEFT JOIN public.media_assets avatar ON avatar.id = profile.avatar_media_id
        WHERE p.id = ANY(%(post_ids)s::uuid[])
          AND public.can_view_post(p.id, %(viewer_id)s::uuid)
        """,
        params,
    )
    posts = {}
    for row in cur.fetchall():
        post = {
            field: row[field]
            for field in ("id", "content", "visibility", "kind", "shared_post_id",
                          "created_at", "updated_at")
        }
        post.update({
            "author": user_service._serialize_user_summary({
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
        })
        posts[str(row["id"])] = post

    cur.execute(
        """
        SELECT a.post_id, a.position, a.alt_text, to_jsonb(m) AS media
        FROM public.post_attachments a
        JOIN public.posts p ON p.id = a.post_id
        JOIN public.media_assets m ON m.id = a.media_id
        WHERE a.post_id = ANY(%(post_ids)s::uuid[])
          AND p.kind = 'ORIGINAL' AND a.position < 10
          AND m.owner_id = p.author_id AND m.status = 'READY' AND m.deleted_at IS NULL
          AND public.can_view_post(p.id, %(viewer_id)s::uuid)
        ORDER BY a.post_id, a.position
        """,
        params,
    )
    for row in cur.fetchall():
        post = posts.get(str(row["post_id"]))
        if post is None:
            continue
        media = user_service._serialize_media(row["media"], post["author"]["id"])
        if media:
            post["attachments"].append({
                "position": row["position"], "alt_text": row["alt_text"], "media": media,
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
              WHERE (b.blocker_id = %(viewer_id)s AND b.blocked_id = c.author_id)
                 OR (b.blocker_id = c.author_id AND b.blocked_id = %(viewer_id)s)
          )
        GROUP BY c.post_id
        UNION ALL
        SELECT s.shared_post_id AS post_id, 'shares' AS category, COUNT(*) AS count
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


def list_user_posts(viewer_id, user_id, query: UserPageQuery):
    """List readable profile posts, without applying the home feed's hidden-post filter."""
    filters = {"user_id": str(user_id)}
    position = decode_cursor(
        query.cursor, "user-posts", viewer_id, filters, UserPostsCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            # Keep page membership, originals and counts in one consistent read snapshot.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
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
                         (%(after_created_at)s::timestamptz, %(after_id)s::uuid)
                  )
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT %(fetch_limit)s
                """,
                {
                    "viewer_id": viewer_id, "user_id": user_id,
                    "after_created_at": position.created_at if position else None,
                    "after_id": str(position.id) if position else None,
                    "fetch_limit": query.limit + 1,
                },
            )
            rows = cur.fetchall()
            has_more = len(rows) > query.limit
            rows = rows[:query.limit]
            ids = {str(row["id"]) for row in rows}
            ids.update(str(row["shared_post_id"]) for row in rows
                       if row["kind"] == "SHARE" and row["shared_post_id"] is not None)
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
        data.append(user_service._serialize(post))

    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = encode_cursor(
            "user-posts", viewer_id, filters,
            {"created_at": last["created_at"].isoformat(), "id": str(last["id"])},
        )
    return {
        "data": data,
        "pagination": {
            "limit": query.limit, "has_more": has_more, "next_cursor": next_cursor,
        },
    }
