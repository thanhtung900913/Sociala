from datetime import datetime, timezone

from flask import current_app

from app.backend.db.connection import get_db_connection_context
from app.backend.db.feed_store import (
    FeedStoreError, get_feed_store, parse_sort_key, partition_key, sort_key,
)
from app.backend.models.post_model import PostPageCursor, PostPageQuery, PostsResponseBody
from app.backend.services import post_service
from app.backend.services.errors import ServiceError
from app.backend.utils.pagination import decode_cursor, encode_cursor


CURSOR_FILTERS = {"source": "dynamodb-v1"}


def _cursor_position(key):
    created_at, post_id = parse_sort_key(key)
    return {"created_at": created_at.isoformat(), "id": post_id}


def _validate_page(page, viewer_id, after):
    """Reject inconsistent ownership, post identities or pagination progress."""
    expected_pk = partition_key(viewer_id)
    try:
        if page.last_key is not None:
            key = page.last_key
            if key.pk != expected_pk or (after is not None and key.sk >= after):
                raise ValueError("Feed pagination did not advance within the viewer partition")
            parse_sort_key(key.sk)
        for ref in page.references:
            if (ref.key.pk != expected_pk
                    or sort_key(ref.created_at, ref.post_id) != ref.key.sk
                    or (after is not None and ref.key.sk >= after)):
                raise ValueError("Feed reference does not match its owner, post or position")
    except ValueError as error:
        current_app.logger.exception("Invalid materialized feed page")
        raise ServiceError({"error": "Feed temporarily unavailable"}, 503) from error


def _load_feed_posts(viewer_id, references, limit):
    """Authorize and hydrate only indexed IDs, using one snapshot per batch."""
    if not references:
        return []
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            # Membership, originals and counts must use the same read snapshot.
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            cur.execute(
                """
                SELECT p.id, p.author_id, p.kind, p.shared_post_id, p.created_at
                FROM public.posts p
                WHERE p.id = ANY(%(post_ids)s::uuid[])
                  AND (
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
                """,
                {
                    "viewer_id": viewer_id,
                    "post_ids": list({ref.post_id for ref in references}),
                },
            )
            rows = {str(row["id"]): row for row in cur.fetchall()}
            ordered = []
            selected_ids = set()
            for ref in references:
                row = rows.get(ref.post_id)
                if (row is not None and row["created_at"] == ref.created_at
                        and str(row["author_id"]) == ref.author_id
                        and ref.post_id not in selected_ids):
                    ordered.append((ref, row))
                    selected_ids.add(ref.post_id)
            # Include one hydrated lookahead, so a missing SHARE original cannot
            # incorrectly advertise a readable next page.
            ordered = ordered[:limit]
            page_rows = [row for _, row in ordered]
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
            for ref, row in ordered:
                post = posts.get(str(row["id"]))
                if post is None:
                    continue
                if post["kind"] == "SHARE":
                    original = posts.get(str(post["shared_post_id"]))
                    if original is None or original["kind"] != "ORIGINAL":
                        continue
                    post["original_post"] = original
                data.append((ref, post))
        conn.commit()
    return data


def _read_feed(viewer_id, query, position, store, page_size, max_pages):
    after = sort_key(position.created_at, position.id) if position else None
    now = int(datetime.now(timezone.utc).timestamp())
    loaded = []
    seen = set()
    continuation = None
    for _ in range(max_pages):
        # No PostgreSQL connection is held while querying DynamoDB.
        page = store.query(viewer_id, page_size, after)
        _validate_page(page, viewer_id, after)
        references = [ref for ref in page.references
                      if ref.post_id not in seen
                      and (ref.expires_at is None or ref.expires_at > now)]
        posts = _load_feed_posts(viewer_id, references, query.limit + 1 - len(loaded))
        seen.update(ref.post_id for ref, _ in posts)
        loaded.extend(posts)
        if len(loaded) > query.limit:
            # Resume after the last returned post, not after the entire AWS
            # page: otherwise its unread items/lookahead would be lost.
            continuation = loaded[query.limit - 1][0].key.sk
            break
        if page.last_key is None:
            continuation = None
            break
        after = page.last_key.sk
        continuation = after
    # A short or empty page can still have a continuation when stale/hidden
    # references exhausted the per-request work budget.
    has_more = continuation is not None
    next_cursor = (encode_cursor("feed", viewer_id, CURSOR_FILTERS,
                                 _cursor_position(continuation)) if has_more else None)
    return PostsResponseBody.model_validate({
        "data": [post for _, post in loaded[:query.limit]],
        "pagination": {"limit": query.limit, "has_more": has_more, "next_cursor": next_cursor},
    })


def get_feed(viewer_id, query: PostPageQuery) -> PostsResponseBody:
    position = decode_cursor(
        query.cursor, "feed", viewer_id, CURSOR_FILTERS, PostPageCursor
    )
    page_size = current_app.config.get("FEED_QUERY_PAGE_SIZE", 100)
    max_pages = current_app.config.get("FEED_MAX_QUERY_PAGES", 10)
    if not 1 <= page_size <= 1000 or not 1 <= max_pages <= 100:
        raise ValueError("Invalid feed query limits")
    try:
        return _read_feed(viewer_id, query, position, get_feed_store(), page_size, max_pages)
    except FeedStoreError as error:
        current_app.logger.exception("Feed repository unavailable")
        raise ServiceError({"error": "Feed temporarily unavailable"}, 503) from error
