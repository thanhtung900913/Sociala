from app.backend.db.connection import get_db_connection_context
from app.backend.models.post_model import PostPageCursor, PostPageQuery, PostsResponseBody
from app.backend.services import post_service
from app.backend.utils.pagination import decode_cursor


def get_feed(viewer_id, query: PostPageQuery) -> PostsResponseBody:
    filters = {}
    position = decode_cursor(
        query.cursor, "feed", viewer_id, filters, PostPageCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            # Membership, originals and counts must use the same read snapshot.
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            cur.execute(
                """
                SELECT p.id, p.kind, p.shared_post_id, p.created_at
                FROM public.posts p
                WHERE (
                    p.author_id = %(viewer_id)s::uuid
                    OR EXISTS (
                        SELECT 1 FROM public.friendships f
                        WHERE f.user_low_id = LEAST(%(viewer_id)s::uuid, p.author_id)
                          AND f.user_high_id = GREATEST(%(viewer_id)s::uuid, p.author_id)
                          AND f.status = 'ACCEPTED'
                    )
                )
                  AND public.can_view_post(p.id, %(viewer_id)s::uuid)
                  AND NOT EXISTS (
                      SELECT 1 FROM public.hidden_posts h
                      WHERE h.user_id = %(viewer_id)s::uuid AND h.post_id = p.id
                  )
                  AND (%(after_created_at)s::timestamptz IS NULL
                       OR (p.created_at, p.id) <
                          (%(after_created_at)s::timestamptz,
                           %(after_id)s::uuid))
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT %(fetch_limit)s
                """,
                {
                    "viewer_id": viewer_id,
                    "after_created_at": position.created_at if position else None,
                    "after_id": str(position.id) if position else None,
                    "fetch_limit": query.limit + 1,
                },
            )
            rows = cur.fetchall()
            page_rows = rows[:query.limit]
            ids = {str(row["id"]) for row in page_rows}
            ids.update(
                str(row["shared_post_id"]) for row in page_rows
                if row["kind"] == "SHARE" and row["shared_post_id"] is not None
            )
            posts = (
                post_service._load_posts(cur, viewer_id, sorted(ids))
                if ids else {}
            )
            data = []
            for row in page_rows:
                post = posts.get(str(row["id"]))
                if post is None:
                    continue
                if post["kind"] == "SHARE":
                    original = posts.get(str(post["shared_post_id"]))
                    if original is None or original["kind"] != "ORIGINAL":
                        continue
                    post["original_post"] = original
                data.append(post)
        conn.commit()
    return PostsResponseBody.model_validate({
        "data": data,
        "pagination": post_service._pagination(
            rows, query, "feed", viewer_id, filters
        ),
    })
