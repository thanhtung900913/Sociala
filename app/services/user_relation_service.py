from app.db.connection import get_db_connection_context
from app.models.user_model import (
    FriendsResponseBody, SearchUsersCursor, UserPageQuery,
    UserRelationsCursor, UserRelationsResponseBody,
)
from app.services import user_service
from app.services.errors import ServiceError
from app.services.relationship_lock import lock_relationship_pair
from app.utils.pagination import decode_cursor, encode_cursor


def _check_actor(actor):
    if (
        actor is None or actor["status"] != "ACTIVE"
        or actor["deleted_at"] is not None
    ):
        raise ServiceError({
            "error": "FORBIDDEN", "message": "Current user is not active",
        }, 403)


def _lock_users(cur, actor_id, peer_id):
    params = lock_relationship_pair(cur, actor_id, peer_id)
    cur.execute(
        """
        SELECT id, status, deleted_at FROM public.users
        WHERE id IN (%(actor_id)s::uuid, %(peer_id)s::uuid)
        ORDER BY id FOR SHARE
        """,
        params,
    )
    users = {str(row["id"]): row for row in cur.fetchall()}
    _check_actor(users.get(params["actor_id"]))
    return params, users.get(params["peer_id"])


def _require_active_actor(cur, actor_id):
    cur.execute(
        """
        SELECT status, deleted_at FROM public.users
        WHERE id = %(actor_id)s
        """,
        {"actor_id": actor_id},
    )
    _check_actor(cur.fetchone())


def _require_peer(peer, active=False):
    if peer is None or (
        active and (
            peer["status"] != "ACTIVE" or peer["deleted_at"] is not None
        )
    ):
        raise ServiceError({
            "error": "NOT_FOUND", "message": "User is unavailable",
        }, 404)


def list_friends(actor_id, query: UserPageQuery) -> FriendsResponseBody:
    position = decode_cursor(
        query.cursor, "user-friends", actor_id, {}, SearchUsersCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            _require_active_actor(cur, actor_id)
            cur.execute(
                """
                SELECT u.id, u.username, LOWER(u.username) AS sort_username,
                       COALESCE(p.display_name, u.username) AS display_name,
                       to_jsonb(avatar) AS avatar,
                       f.responded_at AS friends_since
                FROM public.friendships f
                JOIN public.users u ON u.id = CASE
                    WHEN f.user_low_id = %(actor_id)s::uuid THEN f.user_high_id
                    ELSE f.user_low_id END
                LEFT JOIN public.user_profiles p ON p.user_id = u.id
                LEFT JOIN public.media_assets avatar
                  ON avatar.id = p.avatar_media_id
                WHERE %(actor_id)s::uuid IN (f.user_low_id, f.user_high_id)
                  AND f.status = 'ACCEPTED'
                  AND u.status = 'ACTIVE' AND u.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM public.user_blocks b
                      WHERE (b.blocker_id = %(actor_id)s
                             AND b.blocked_id = u.id)
                         OR (b.blocker_id = u.id
                             AND b.blocked_id = %(actor_id)s)
                  )
                  AND (%(cursor_username)s::text IS NULL
                    OR (LOWER(u.username), u.id) >
                       (%(cursor_username)s::text, %(cursor_id)s::uuid))
                ORDER BY LOWER(u.username) ASC, u.id ASC
                LIMIT %(limit)s
                """,
                {
                    "actor_id": actor_id,
                    "cursor_username": position.username if position else None,
                    "cursor_id": str(position.id) if position else None,
                    "limit": query.limit + 1,
                },
            )
            rows = cur.fetchall()
        conn.commit()
    has_more = len(rows) > query.limit
    rows = rows[:query.limit]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = encode_cursor(
            "user-friends", actor_id, {},
            {"username": last["sort_username"], "id": str(last["id"])},
        )
    return FriendsResponseBody.model_validate({
        "data": [{
            "user": user_service.build_user_summary(row),
            "friends_since": row["friends_since"],
        } for row in rows],
        "pagination": {
            "limit": query.limit, "has_more": has_more,
            "next_cursor": next_cursor,
        },
    })


def remove_friend(actor_id, peer_id) -> None:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            params, _ = _lock_users(cur, actor_id, peer_id)
            cur.execute(
                """
                UPDATE public.friendships
                SET status = 'REMOVED', responded_at = clock_timestamp()
                WHERE user_low_id = %(low_id)s AND user_high_id = %(high_id)s
                  AND status = 'ACCEPTED'
                """,
                params,
            )
        conn.commit()


def _private_summary(row):
    if row["status"] != "ACTIVE" or row["deleted_at"] is not None:
        return {
            "id": row["id"], "username": "unavailable",
            "display_name": "Unavailable user", "avatar_url": None,
        }
    return user_service.build_user_summary(row)


def _list_private_relations(actor_id, query, kind):
    # SQL identifiers are internal constants, never request input.
    table, owner, peer = {
        "blocks": ("user_blocks", "blocker_id", "blocked_id"),
        "restrictions": (
            "user_restrictions", "restrictor_id", "restricted_id"
        ),
    }[kind]
    route = f"user-{kind}"
    position = decode_cursor(
        query.cursor, route, actor_id, {}, UserRelationsCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            _require_active_actor(cur, actor_id)
            cur.execute(
                f"""
                SELECT r.{peer} AS id, r.created_at, u.username, u.status,
                       u.deleted_at,
                       COALESCE(p.display_name, u.username) AS display_name,
                       to_jsonb(avatar) AS avatar
                FROM public.{table} r
                LEFT JOIN public.users u ON u.id = r.{peer}
                LEFT JOIN public.user_profiles p ON p.user_id = u.id
                LEFT JOIN public.media_assets avatar
                  ON avatar.id = p.avatar_media_id
                WHERE r.{owner} = %(actor_id)s
                  AND (%(cursor_time)s::timestamptz IS NULL
                    OR (r.created_at, r.{peer}) <
                       (%(cursor_time)s::timestamptz, %(cursor_id)s::uuid))
                ORDER BY r.created_at DESC, r.{peer} DESC
                LIMIT %(limit)s
                """,
                {
                    "actor_id": actor_id,
                    "cursor_time": position.created_at if position else None,
                    "cursor_id": str(position.id) if position else None,
                    "limit": query.limit + 1,
                },
            )
            rows = cur.fetchall()
        conn.commit()
    has_more = len(rows) > query.limit
    rows = rows[:query.limit]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = encode_cursor(route, actor_id, {}, {
            "created_at": last["created_at"].isoformat(),
            "id": str(last["id"]),
        })
    return UserRelationsResponseBody.model_validate({
        "data": [{
            "user": _private_summary(row), "created_at": row["created_at"],
        } for row in rows],
        "pagination": {
            "limit": query.limit, "has_more": has_more,
            "next_cursor": next_cursor,
        },
    })


def list_blocks(actor_id, query: UserPageQuery) -> UserRelationsResponseBody:
    return _list_private_relations(actor_id, query, "blocks")


def block_user(actor_id, peer_id) -> None:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            params, peer = _lock_users(cur, actor_id, peer_id)
            _require_peer(peer)
            cur.execute(
                """
                INSERT INTO public.user_blocks (blocker_id, blocked_id)
                VALUES (%(actor_id)s, %(peer_id)s)
                ON CONFLICT (blocker_id, blocked_id) DO NOTHING
                """,
                params,
            )
            cur.execute(
                """
                UPDATE public.friendships
                SET status = 'REMOVED', responded_at = clock_timestamp()
                WHERE user_low_id = %(low_id)s AND user_high_id = %(high_id)s
                  AND status IN ('PENDING', 'ACCEPTED')
                """,
                params,
            )
        conn.commit()


def unblock_user(actor_id, peer_id) -> None:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            params, _ = _lock_users(cur, actor_id, peer_id)
            cur.execute(
                """
                DELETE FROM public.user_blocks
                WHERE blocker_id = %(actor_id)s AND blocked_id = %(peer_id)s
                """,
                params,
            )
        conn.commit()


def list_restrictions(
    actor_id, query: UserPageQuery
) -> UserRelationsResponseBody:
    return _list_private_relations(actor_id, query, "restrictions")


def restrict_user(actor_id, peer_id) -> None:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            params, peer = _lock_users(cur, actor_id, peer_id)
            _require_peer(peer, active=True)
            cur.execute(
                """
                SELECT 1 FROM public.user_blocks b
                WHERE (b.blocker_id = %(actor_id)s
                       AND b.blocked_id = %(peer_id)s)
                   OR (b.blocker_id = %(peer_id)s
                       AND b.blocked_id = %(actor_id)s)
                LIMIT 1
                """,
                params,
            )
            if cur.fetchone() is not None:
                raise ServiceError({
                    "error": "NOT_FOUND", "message": "User is unavailable",
                }, 404)
            cur.execute(
                """
                INSERT INTO public.user_restrictions
                    (restrictor_id, restricted_id)
                VALUES (%(actor_id)s, %(peer_id)s)
                ON CONFLICT (restrictor_id, restricted_id) DO NOTHING
                """,
                params,
            )
        conn.commit()


def unrestrict_user(actor_id, peer_id) -> None:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            params, _ = _lock_users(cur, actor_id, peer_id)
            cur.execute(
                """
                DELETE FROM public.user_restrictions
                WHERE restrictor_id = %(actor_id)s
                  AND restricted_id = %(peer_id)s
                """,
                params,
            )
        conn.commit()
